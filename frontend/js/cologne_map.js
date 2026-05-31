let map;
let networkData = null;
let pathLayer = null;
let markers = {};
let selectedStart = null;
let selectedEnd = null;
let isAdminPage = false;
let isAdminAuthenticated = false;

// Tile layers for dark/light mode
window._darkTile  = null;
window._lightTile = null;
window._tileLayer = null;

// ===== Color by line_type (from backend classify_line) =====
// Must match the 3 categories returned by engine.py classify_line():
//   'rail'  — named infrastructure (Innenstadttunnel, SB-Nord …)
//   'sub'   — KVB Stadtbahn 1-99, U-lines, 22a/24a variants
//   'train' — 4-digit OSM relation IDs (S-Bahn / Regional)
const LINE_COLORS = {
    rail:  '#0085c8',   // xanh dương     (Rail / others)
    sub:   '#00c666',   // xanh lá        (Sub  / KVB Stadtbahn 1-99)
    train: '#ffd600',   // vàng           (Train / regional routes)
    walk:  '#9e9e9e',   // xám            (Walk)
};

const INACTIVE_COLOR = '#3d444d';
const PATH_COLOR     = '#f44336';   // đỏ — đường ngắn nhất

function getLineTypeColor(lineType) {
    return LINE_COLORS[lineType] || LINE_COLORS.sub;
}

// ===== Init Map =====
async function initCologneMap() {
    const savedTheme = localStorage.getItem('kvb-theme') || 'dark';
    isAdminPage = window.location.pathname.replace(/\/+$/, '') === '/admin';
    configurePageMode();

    map = L.map('map', { zoomControl: true }).setView([50.9375, 6.9603], 13);

    window._darkTile = L.tileLayer(
        'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
        {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
            subdomains: 'abcd', maxZoom: 20
        }
    );

    window._lightTile = L.tileLayer(
        'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
        {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
            subdomains: 'abcd', maxZoom: 20
        }
    );

    window._tileLayer = savedTheme === 'dark' ? window._darkTile : window._lightTile;
    window._tileLayer.addTo(map);

    try {
        await refreshNetwork();
        if (isAdminPage) {
            await refreshAdminState();
        }
    } catch (e) {
        console.error("Failed to load network:", e);
    }
}

function configurePageMode() {
    const adminPanel = document.getElementById('admin-panel');
    const modeLink = document.getElementById('mode-link');
    const userHint = document.getElementById('user-hint');
    const adminHint = document.getElementById('admin-hint');

    if (modeLink) {
        modeLink.href = isAdminPage ? '/' : '/admin';
        modeLink.textContent = isAdminPage ? 'User' : 'Admin';
    }
    if (adminPanel) adminPanel.classList.toggle('hidden', !isAdminPage);
    if (userHint) userHint.classList.toggle('hidden', isAdminPage);
    if (adminHint) adminHint.classList.toggle('hidden', !isAdminPage);
}

async function refreshAdminState() {
    const status = await TransitAPI.getAdminStatus();
    isAdminAuthenticated = !!status.authenticated;
    renderAdminAuthState();
    if (isAdminAuthenticated) {
        await loadLineControls();
    }
}

function renderAdminAuthState() {
    const loginBox = document.getElementById('admin-login');
    const controlsBox = document.getElementById('admin-controls');
    if (loginBox) loginBox.classList.toggle('hidden', isAdminAuthenticated);
    if (controlsBox) controlsBox.classList.toggle('hidden', !isAdminAuthenticated);
}

async function loginAdmin(event) {
    event.preventDefault();
    const passwordInput = document.getElementById('admin-password');
    const errorEl = document.getElementById('admin-error');
    if (errorEl) errorEl.textContent = '';

    try {
        await TransitAPI.adminLogin(passwordInput.value);
        passwordInput.value = '';
        await refreshAdminState();
    } catch (error) {
        if (errorEl) errorEl.textContent = error.message;
    }
}

async function logoutAdmin() {
    await TransitAPI.adminLogout();
    isAdminAuthenticated = false;
    renderAdminAuthState();
}

// ===== Network =====
async function refreshNetwork() {
    networkData = await TransitAPI.getNetwork();
    renderNetwork();
}

function renderNetwork() {
    Object.values(markers).forEach(m => m.remove());
    markers = {};
    if (pathLayer) { pathLayer.remove(); pathLayer = null; }

    // Build a quick node lookup map for fallback
    const nodeMap = {};
    networkData.nodes.forEach(n => { nodeMap[n.id] = n; });

    // Draw edges — colored by line_type, using geometry for curves
    networkData.edges.forEach(edge => {
        const active  = edge.active !== false;
        const color   = active ? getLineTypeColor(edge.line_type) : INACTIVE_COLOR;
        const weight  = active ? 3 : 1;
        const opacity = active ? 0.75 : 0.15;

        // Use detailed geometry if available, otherwise fall back to straight line
        let coords;
        if (edge.geometry && edge.geometry.length > 0) {
            coords = edge.geometry; // Already [[lat, lon], ...]
        } else {
            const u = nodeMap[edge.source];
            const v = nodeMap[edge.target];
            if (!u || !v) return;
            coords = [[u.lat, u.lon], [v.lat, v.lon]];
        }

        const dashArray = edge.line_type === 'walk' ? '5, 5' : null;
        L.polyline(coords, { color, weight, opacity, dashArray }).addTo(map);
    });

    // Draw station markers
    networkData.nodes.forEach(node => {
        const marker = L.circleMarker([node.lat, node.lon], {
            radius: 7,
            fillColor: '#ffffff',
            color: '#00000040',
            weight: 2,
            fillOpacity: 0.9
        }).addTo(map);

        marker.bindPopup(
            `<b style="font-family:Inter,sans-serif;">${node.name}</b>`
        );
        marker.on('click', () => selectNode(node));
        markers[node.id] = marker;
    });

    populateStationDropdowns();
}

function populateStationDropdowns() {
    const startSelect = document.getElementById('start-select');
    const endSelect = document.getElementById('end-select');
    
    if (!startSelect || !endSelect) return;

    let optionsHTML = '<option value="" disabled selected>Chọn trạm...</option>';

    // Sort nodes alphabetically (safeguard against missing names)
    const sortedNodes = [...networkData.nodes].sort((a, b) => {
        const nameA = a.name || "";
        const nameB = b.name || "";
        return nameA.localeCompare(nameB);
    });

    sortedNodes.forEach(node => {
        optionsHTML += `<option value="${node.id}">${node.name}</option>`;
    });

    startSelect.innerHTML = optionsHTML;
    endSelect.innerHTML = optionsHTML;

    // Add event listeners (if not already added)
    if (!startSelect.dataset.listenerAdded) {
        startSelect.addEventListener('change', handleDropdownChange);
        endSelect.addEventListener('change', handleDropdownChange);
        startSelect.dataset.listenerAdded = 'true';
    }
}

function handleDropdownChange(e) {
    const isStart = e.target.id === 'start-select';
    const nodeId = e.target.value;
    const node = networkData.nodes.find(n => String(n.id) === String(nodeId));
    if (!node) return;

    if (isStart) {
        if (selectedStart && markers[selectedStart.id]) {
            markers[selectedStart.id].setStyle({ fillColor: '#ffffff', radius: 7, weight: 2 });
        }
        selectedStart = node;
        markers[node.id].setStyle({ fillColor: '#28a745', radius: 12, weight: 3 });
    } else {
        if (selectedEnd && markers[selectedEnd.id]) {
            markers[selectedEnd.id].setStyle({ fillColor: '#ffffff', radius: 7, weight: 2 });
        }
        selectedEnd = node;
        markers[node.id].setStyle({ fillColor: PATH_COLOR, radius: 12, weight: 3 });
    }

    if (selectedStart && selectedEnd) {
        findPath();
    }
}

// ===== Selection =====
function selectNode(node) {
    if (!selectedStart) {
        selectedStart = node;
        const startSelect = document.getElementById('start-select');
        if (startSelect) startSelect.value = node.id;
        markers[node.id].setStyle({ fillColor: '#28a745', radius: 12, weight: 3 });

    } else if (!selectedEnd) {
        selectedEnd = node;
        const endSelect = document.getElementById('end-select');
        if (endSelect) endSelect.value = node.id;
        markers[node.id].setStyle({ fillColor: PATH_COLOR, radius: 12, weight: 3 });
        findPath();

    } else {
        resetSelection();
        selectedStart = node;
        const startSelect = document.getElementById('start-select');
        if (startSelect) startSelect.value = node.id;
        markers[node.id].setStyle({ fillColor: '#28a745', radius: 12, weight: 3 });
    }
}

function resetSelection() {
    if (selectedStart && markers[selectedStart.id])
        markers[selectedStart.id].setStyle({ fillColor: '#ffffff', radius: 7, weight: 2 });
    if (selectedEnd && markers[selectedEnd.id])
        markers[selectedEnd.id].setStyle({ fillColor: '#ffffff', radius: 7, weight: 2 });

    selectedStart = null;
    selectedEnd   = null;
    
    const startSelect = document.getElementById('start-select');
    const endSelect = document.getElementById('end-select');
    if (startSelect) startSelect.value = '';
    if (endSelect) endSelect.value = '';

    document.getElementById('distInfo').innerText  = '\u2014';

    if (pathLayer) { pathLayer.remove(); pathLayer = null; }

    // Clear itinerary
    const box = document.getElementById('route-details-box');
    if (box) box.style.display = 'none';
    const steps = document.getElementById('route-steps');
    if (steps) steps.innerHTML = '';
}

// ===== Path Finding =====
async function findPath() {
    if (!selectedStart || !selectedEnd) return;

    const result = await TransitAPI.findPath(selectedStart.id, selectedEnd.id);

    if (result.success) {
        const pathCoords = [];
        result.details.forEach(step => {
            // Use detailed geometry if available for map-matched curves
            if (step.geometry && step.geometry.length > 0) {
                step.geometry.forEach((coord, idx) => {
                    // Avoid duplicating the junction point between segments
                    if (idx === 0 && pathCoords.length > 0) {
                        const last = pathCoords[pathCoords.length - 1];
                        if (last[0] === coord[0] && last[1] === coord[1]) return;
                    }
                    pathCoords.push(coord);
                });
            } else {
                // Fallback: straight line from node to node
                const u = networkData.nodes.find(n => n.id === step.from);
                if (u) {
                    if (pathCoords.length === 0 ||
                        pathCoords[pathCoords.length - 1][0] !== u.lat ||
                        pathCoords[pathCoords.length - 1][1] !== u.lon) {
                        pathCoords.push([u.lat, u.lon]);
                    }
                }
            }
        });
        // Ensure the final destination node is included
        const lastNode = networkData.nodes.find(n => n.id === result.path[result.path.length - 1]);
        if (lastNode) {
            if (pathCoords.length === 0 ||
                pathCoords[pathCoords.length - 1][0] !== lastNode.lat ||
                pathCoords[pathCoords.length - 1][1] !== lastNode.lon) {
                pathCoords.push([lastNode.lat, lastNode.lon]);
            }
        }

        if (pathLayer) pathLayer.remove();
        pathLayer = L.polyline(pathCoords, {
            color: PATH_COLOR,
            weight: 6,
            opacity: 0.95,
            dashArray: '12, 8',
            lineJoin: 'round',
            lineCap: 'round'
        }).addTo(map);

        map.fitBounds(pathLayer.getBounds(), { padding: [40, 40] });
        document.getElementById('distInfo').innerText =
            (result.total_distance / 1000).toFixed(2) + ' km';

        // Render itinerary
        renderItinerary(result.details);
    } else {
        alert('Kh\u00f4ng t\u00ecm th\u1ea5y \u0111\u01b0\u1eddng \u0111i: ' + (result.error || 'L\u1ed7i kh\u00f4ng x\u00e1c \u0111\u1ecbnh'));
    }
}

// ===== Itinerary Renderer =====
function classifyLine(lineName) {
    if (!lineName || lineName === 'Unknown Line') return 'rail';
    const name = String(lineName).trim();
    if (name === 'Walk') return 'walk';
    const upper = name.toUpperCase();

    // 1. FIRST PRIORITY (Sub)
    if (upper.startsWith('U')) return 'sub';
    const m = name.match(/^(\d{1,2})[a-zA-Z]$/);
    if (m && parseInt(m[1], 10) >= 1 && parseInt(m[1], 10) <= 99) return 'sub';
    
    const n = parseInt(name, 10);
    if (!isNaN(n) && String(n) === name) {
        if (n >= 1 && n <= 99) return 'sub';
    }
    if (/^\d+$/.test(name)) {
        if (n >= 1 && n <= 99) return 'sub';
    }

    // 2. SECOND PRIORITY (Train)
    if (/^(S|RE|RB)\s*\d+/.test(upper)) return 'train';
    if (!isNaN(n) && String(n) === name) {
        if (n >= 1000 && n <= 9999) return 'train';
    }
    if (/^\d+$/.test(name)) {
        if (n >= 1000 && n <= 9999) return 'train';
    }
    if (upper === "REGIONAL/S-BAHN" || upper === "TRAIN TRACK") return 'train';

    // 3. THIRD PRIORITY (Rail)
    if (upper === "TRAM TRACK" || upper === "LIGHT RAIL TRACK" || upper.includes("TRAM")) {
        return 'rail';
    }
    const alphaStart = upper.match(/^([A-Z]+)/);
    if (alphaStart) {
        const prefix = alphaStart[1];
        if (!['S', 'U', 'RE', 'RB'].includes(prefix)) {
            return 'rail';
        }
    }

    // 4. FALLBACK
    return 'train';
}

const TYPE_LABEL = { rail: 'Rail', sub: 'Sub', train: 'Train', walk: 'Walk' };
const TYPE_ICON  = { rail: '🚇', sub: '🚇', train: '🚆', walk: '🚶' };

function renderItinerary(details) {
    const box   = document.getElementById('route-details-box');
    const steps = document.getElementById('route-steps');
    if (!box || !steps) return;

    // Group consecutive steps with the same line into segments
    const segments = [];
    let cur = null;

    details.forEach(step => {
        const line = step.line || 'Unknown Line';
        if (!cur || cur.line !== line) {
            cur = {
                line,
                type: step.line_type || classifyLine(line),
                from_name: step.from_name || `ID ${step.from}`,
                to_name:   step.to_name   || `ID ${step.to}`,
                distance:  step.distance || 0,
                stops: 1
            };
            segments.push(cur);
        } else {
            cur.to_name  = step.to_name || `ID ${step.to}`;
            cur.distance += (step.distance || 0);
            cur.stops++;
        }
    });

    steps.innerHTML = '';
    segments.forEach((seg, idx) => {
        const color = LINE_COLORS[seg.type] || LINE_COLORS.sub;
        const km    = (seg.distance / 1000).toFixed(2);

        // Segment block — colored header + station list
        const el = document.createElement('div');
        el.className = 'route-step';
        el.style.setProperty('--seg-color', color);
        
        const lineText = seg.type === 'walk' ? 'Đi bộ' : `Tuy&#7871;n ${seg.line}`;
        
        el.innerHTML = `
            <div class="step-header" style="background:${color};">
                <span class="step-type-icon">${TYPE_ICON[seg.type]}</span>
                <span class="step-line-name">${TYPE_LABEL[seg.type]} &bull; ${lineText}</span>
                <span class="step-km">${km} km</span>
            </div>
            <div class="step-route">
                <div class="step-station step-from">
                    <span class="step-dot dot-green"></span>
                    <span>${seg.from_name}</span>
                </div>
                <div class="step-midline" style="border-color:${color};"></div>
                <div class="step-station step-to">
                    <span class="step-dot dot-red"></span>
                    <span>${seg.to_name}</span>
                </div>
            </div>
        `;
        steps.appendChild(el);
    });

    box.style.display = 'block';
}


// ===== Admin Line Controls — grouped by type =====
async function loadLineControls() {
    if (!isAdminPage || !isAdminAuthenticated) return;

    const linesData = await TransitAPI.getLines();
    const container = document.getElementById('line-controls');
    if (!container) return;

    container.innerHTML = '';

    if (!linesData.all_lines || linesData.all_lines.length === 0) {
        container.innerHTML = '<p style="font-size:0.78rem;color:var(--text-subtle);text-align:center;padding:12px 0;">Không có tuyến nào.</p>';
        return;
    }

    // Group by type (must match backend classify_line output: rail / sub / train)
    const groups = { rail: [], sub: [], train: [] };
    linesData.all_lines.forEach(line => {
        const t = line.type || 'rail';
        if (groups[t]) groups[t].push(line);
        else groups.rail.push(line);  // fallback for any unknown type
    });

    const groupMeta = {
        rail:  { label: '🚇 Rail',  color: LINE_COLORS.rail,  desc: 'Tàu điện ngầm/Khác' },
        sub:   { label: '🚇 Sub',   color: LINE_COLORS.sub,   desc: 'KVB Stadtbahn' },
        train: { label: '🚆 Train', color: LINE_COLORS.train, desc: 'Tàu vùng (Regional)' },
    };

    ['rail', 'sub', 'train'].forEach(type => {
        const lines = groups[type];
        if (lines.length === 0) return;

        const meta = groupMeta[type];

        // Group header
        const header = document.createElement('div');
        header.className = 'line-group-header';
        const allDisabled = lines.every(line => linesData.disabled_lines.includes(line.name));
        header.innerHTML = `
            <span class="group-dot" style="background:${meta.color};box-shadow:0 0 8px ${meta.color}88;"></span>
            <span class="group-label">${meta.label}</span>
            <span class="group-desc">${meta.desc} (${lines.length})</span>
            <label class="switch" style="margin-left: auto; margin-right: 10px;" title="Toggle all ${meta.label} lines">
                <input type="checkbox" class="master-switch" ${allDisabled ? '' : 'checked'}>
                <span class="slider"></span>
            </label>
            <button class="btn-group-toggle" onclick="toggleGroup('${type}', this)">▼</button>
        `;
        container.appendChild(header);

        const masterSwitch = header.querySelector('.master-switch');
        masterSwitch.addEventListener('change', async (e) => {
            const isActive = e.target.checked;
            try {
                await Promise.all(lines.map(line => TransitAPI.toggleLine(line.name, !isActive)));
                await refreshNetwork();
                if (selectedStart && selectedEnd) findPath();
                
                const wrapper = document.getElementById(`group-${type}`);
                if (wrapper) {
                    const childSwitches = wrapper.querySelectorAll('input[type="checkbox"]');
                    childSwitches.forEach(sw => sw.checked = isActive);
                }
            } catch (error) {
                alert(error.message);
                await refreshAdminState();
            }
        });

        // Line items wrapper
        const wrapper = document.createElement('div');
        wrapper.className = 'line-group-items';
        wrapper.id = `group-${type}`;

        lines.forEach(line => {
            const isDisabled = linesData.disabled_lines.includes(line.name);
            const div = document.createElement('div');
            div.className = 'line-item';
            const label = document.createElement('div');
            label.className = 'line-label';

            const dot = document.createElement('div');
            dot.className = 'line-dot';
            dot.style.background = meta.color;

            const name = document.createElement('span');
            name.textContent = line.name;

            label.appendChild(dot);
            label.appendChild(name);

            const switchLabel = document.createElement('label');
            switchLabel.className = 'switch';

            const input = document.createElement('input');
            input.type = 'checkbox';
            input.checked = !isDisabled;
            input.addEventListener('change', () => toggleLine(line.name, input.checked));

            const slider = document.createElement('span');
            slider.className = 'slider';

            switchLabel.appendChild(input);
            switchLabel.appendChild(slider);
            div.appendChild(label);
            div.appendChild(switchLabel);
            wrapper.appendChild(div);
        });

        container.appendChild(wrapper);
    });
}

// Collapse/expand a group
function toggleGroup(type, btn) {
    const wrapper = document.getElementById(`group-${type}`);
    const collapsed = wrapper.classList.toggle('collapsed');
    btn.textContent = collapsed ? '▶' : '▼';
}

async function toggleLine(lineName, active) {
    try {
        await TransitAPI.toggleLine(lineName, !active);
        await refreshNetwork();
        if (selectedStart && selectedEnd) findPath();
    } catch (error) {
        alert(error.message);
        await refreshAdminState();
    }
}
