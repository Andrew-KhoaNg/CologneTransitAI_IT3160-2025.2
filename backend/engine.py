import heapq
import networkx as nx
import json
import os
import math
import requests

def haversine(lat1, lon1, lat2, lon2):
    """Calculate the great circle distance in meters between two points on the earth."""
    R = 6371000 # Radius of Earth in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def _normalize_line(line):
    """Normalize a line value to a list of strings (handles str, list, None)."""
    if line is None:
        return []
    if isinstance(line, list):
        return [str(l) for l in line]
    return [str(line)]


def classify_line(line_name, osm_route=None):
    """Classify a transit line name strictly from scratch."""
    if not line_name:
        return 'rail'

    name = str(line_name).strip()
    if name == 'Walk':
        return 'walk'

    name_upper = name.upper()

    # 1. FIRST PRIORITY (Sub): Numeric 1-99 OR starts with 'U'
    if name_upper.startswith('U'):
        return 'sub'

    import re
    m_sub = re.match(r'^(\d{1,2})[a-zA-Z]$', name)
    if m_sub and 1 <= int(m_sub.group(1)) <= 99:
        return 'sub'

    try:
        n = int(name)
        if 1 <= n <= 99:
            return 'sub'
    except ValueError:
        pass

    # 2. SECOND PRIORITY (Train): starts with 'S', 'RE', 'RB', or 4-digit
    if re.match(r'^(S|RE|RB)\s*\d+', name_upper):
        return 'train'

    try:
        n = int(name)
        if 1000 <= n <= 9999:
            return 'train'
    except ValueError:
        pass
        
    if name_upper in ("REGIONAL/S-BAHN", "TRAIN TRACK"):
        return 'train'

    # 3. THIRD PRIORITY (Rail): Contains "Tram", "LightRail", or alphabetic
    if "TRAM" in name_upper or "LIGHTRAIL" in name_upper:
        return 'rail'

    if osm_route in ('tram', 'light_rail'):
        return 'rail'

    alpha_start = re.match(r'^([A-Z]+)', name_upper)
    if alpha_start:
        prefix = alpha_start.group(1)
        if prefix not in ('S', 'U', 'RE', 'RB'):
            return 'rail'

    # 4. FALLBACK
    return 'train'


class TransitEngine:
    def __init__(self, data_path, disabled_lines=None, encoded_unknown_lines=None):
        self.data_path = data_path
        self.graph = nx.Graph()
        self.disabled_lines = set(disabled_lines or [])
        self.encoded_unknown_lines = set(encoded_unknown_lines or [])
        self.load_network()

    def classify_line(self, line_name, osm_route=None):
        return classify_line(line_name, osm_route)

    def load_network(self):
        """Load transit network from JSON, filtering out rail lines and preserving valid nodes."""
        if not os.path.exists(self.data_path):
            print(f"Warning: Data file {self.data_path} not found.")
            return

        with open(self.data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        raw_nodes = data['nodes']
        raw_edges = data['edges']

        # Add all nodes EXACTLY as they appear
        for node in raw_nodes:
            self.graph.add_node(
                node['id'],
                id=node['id'],
                lat=node['lat'],
                lon=node['lon'],
                name=node['name']
            )

        # Merge edges and filter out non-sub/train lines
        merged_edges = {}
        for edge in raw_edges:
            u, v = edge['source'], edge['target']
            if u == v:
                continue  # self-loop -> skip

            lines = _normalize_line(edge['line'])
            
            edge_key = (min(u, v), max(u, v))

            if edge_key not in merged_edges:
                merged_edges[edge_key] = {
                    'u': u, 'v': v,
                    'lines': set(lines),
                    'length': edge['length'],
                    'geometry': edge.get('geometry', []),
                    'osm_route': edge.get('osm_route')
                }
            else:
                merged_edges[edge_key]['lines'].update(lines)
                # Keep shortest length & its geometry
                if edge['length'] < merged_edges[edge_key]['length']:
                    merged_edges[edge_key]['length'] = edge['length']
                    merged_edges[edge_key]['geometry'] = edge.get('geometry', [])
                    merged_edges[edge_key]['osm_route'] = edge.get('osm_route')

        for e in merged_edges.values():
            self.graph.add_edge(
                e['u'], e['v'],
                line=list(e['lines']),
                weight=e['length'],
                length=e['length'],
                geometry=e['geometry'],
                osm_route=e['osm_route']
            )

        # Add walking edges
        nodes = list(self.graph.nodes(data=True))
        for i in range(len(nodes)):
            u, u_data = nodes[i]
            for j in range(i + 1, len(nodes)):
                v, v_data = nodes[j]
                if not self.graph.has_edge(u, v):
                    dist = haversine(u_data.get('lat', 0), u_data.get('lon', 0), v_data.get('lat', 0), v_data.get('lon', 0))
                    if dist <= 400:
                        self.graph.add_edge(
                            u, v,
                            line=['Walk'],
                            weight=dist,
                            length=dist,
                            geometry=[]
                        )
            
        # Clean up: Remove nodes that became disconnected because their rail edges were deleted
        isolated_nodes = list(nx.isolates(self.graph))
        self.graph.remove_nodes_from(isolated_nodes)

        print(f"Graph loaded: {len(raw_nodes)} raw nodes -> {self.graph.number_of_nodes()} active nodes, "
              f"{len(raw_edges)} raw edges -> {self.graph.number_of_edges()} valid merged edges.")

    def _is_edge_disabled(self, edge_data):
        """Return True if ALL lines of this edge are disabled (or has no lines)."""
        lines = _normalize_line(edge_data.get('line'))
        if not lines:
            return False  # unknown line, keep active
        # Edge is disabled only when every line it belongs to is disabled
        return all(line in self.disabled_lines for line in lines)

    def get_all_lines(self):
        """Return sorted list of dicts: {name, type} for each unique line."""
        lines = {}
        for u, v, data in self.graph.edges(data=True):
            osm_route = data.get('osm_route')
            for line in _normalize_line(data.get('line')):
                if line not in lines:
                    lines[line] = self.classify_line(line, osm_route)
        result = [{'name': name, 'type': ltype} for name, ltype in lines.items()]
        result.sort(key=lambda x: (x['type'], x['name']))
        return result

    def toggle_line(self, line_name, disabled=True):
        if disabled:
            self.disabled_lines.add(line_name)
        else:
            self.disabled_lines.discard(line_name)
        return list(self.disabled_lines)

    def find_path(self, start_node_id, end_node_id):
        """Shortest path using A* algorithm with transfer penalty."""
        TRANSFER_PENALTY = 600  # metres
        INF = float('inf')

        if start_node_id == end_node_id:
            return {"success": True, "path": [start_node_id], "details": [], "total_distance": 0}

        end_lat = self.graph.nodes[end_node_id].get('lat', 0)
        end_lon = self.graph.nodes[end_node_id].get('lon', 0)
        
        def heuristic(node_id):
            """Straight-line Haversine distance to the target node."""
            lat = self.graph.nodes[node_id].get('lat', 0)
            lon = self.graph.nodes[node_id].get('lon', 0)
            return haversine(lat, lon, end_lat, end_lon)

        # Build adjacency list restricted to active edges
        adj = {}
        for u, v, d in self.graph.edges(data=True):
            if self._is_edge_disabled(d):
                continue
            lines = _normalize_line(d.get('line')) or ['__unknown__']
            length = d.get('length', 0)
            for line in lines:
                adj.setdefault(u, []).append((v, line, length, d))
                adj.setdefault(v, []).append((u, line, length, d))

        # State: (node_id, current_line)
        # heap entry: (f_cost, g_cost, counter, node, current_line)
        dist = {}   # state -> penalised g_cost
        prev = {}   # state -> (prev_node, prev_line, edge_data, used_line)
        counter = 0
        heap = []

        start_lines = {ln for (_, ln, _, _) in adj.get(start_node_id, [])}
        if not start_lines:
            return {"success": False, "error": "Start node has no active connections"}

        for line in start_lines:
            state = (start_node_id, line)
            dist[state] = 0
            prev[state] = None
            f_cost = heuristic(start_node_id)
            heapq.heappush(heap, (f_cost, 0, counter, start_node_id, line))
            counter += 1

        visited = set()

        while heap:
            f_cost, g_cost, _, node, cur_line = heapq.heappop(heap)
            state = (node, cur_line)
            
            if state in visited:
                continue
            visited.add(state)

            if node == end_node_id:
                break

            for nbr, edge_line, length, edge_data in adj.get(node, []):
                penalty = 0
                prev_line = cur_line
                if prev_line and prev_line != edge_line:
                    if prev_line != 'Walk' and edge_line != 'Walk':
                        penalty = TRANSFER_PENALTY

                cost_length = length * 1.5 if edge_line == 'Walk' else length
                new_g_cost = g_cost + cost_length + penalty
                nstate = (nbr, edge_line)
                
                if new_g_cost < dist.get(nstate, INF):
                    dist[nstate] = new_g_cost
                    prev[nstate] = (node, cur_line, edge_data, edge_line)
                    new_f_cost = new_g_cost + heuristic(nbr)
                    heapq.heappush(heap, (new_f_cost, new_g_cost, counter, nbr, edge_line))
                    counter += 1

        # Pick the best arriving state at end_node
        best_cost = INF
        best_state = None
        for (node, line), c in dist.items():
            if node == end_node_id and c < best_cost:
                best_cost = c
                best_state = (node, line)

        if best_state is None:
            return {"success": False, "error": "No path found (lines might be disabled)"}

        # Reconstruct path backwards
        details = []
        path_nodes = []
        state = best_state

        while state is not None and prev.get(state) is not None:
            node, line = state
            prev_node, prev_line, edge_data, used_line = prev[state]
            length = edge_data.get('length', 0)
            # Get geometry from edge data, with direction awareness
            edge_geometry = edge_data.get('geometry', [])
            # If the edge is stored source->target but we traverse target->source,
            # reverse the geometry so coordinates flow in the correct direction.
            if edge_geometry and len(edge_geometry) > 1:
                # Check if geometry starts closer to prev_node
                prev_lat = self.graph.nodes[prev_node].get('lat', 0)
                prev_lon = self.graph.nodes[prev_node].get('lon', 0)
                geo_start = edge_geometry[0]
                geo_end = edge_geometry[-1]
                dist_to_start = (prev_lat - geo_start[0])**2 + (prev_lon - geo_start[1])**2
                dist_to_end = (prev_lat - geo_end[0])**2 + (prev_lon - geo_end[1])**2
                if dist_to_end < dist_to_start:
                    edge_geometry = list(reversed(edge_geometry))

            # Fetch OSRM pedestrian geometry for Walk edges
            if used_line == 'Walk':
                lat1 = self.graph.nodes[prev_node].get('lat', 0)
                lon1 = self.graph.nodes[prev_node].get('lon', 0)
                lat2 = self.graph.nodes[node].get('lat', 0)
                lon2 = self.graph.nodes[node].get('lon', 0)
                if length < 400:
                    edge_geometry = [[lat1, lon1], [lat2, lon2]]
                else:
                    try:
                        osrm_url = f"http://router.project-osrm.org/route/v1/foot/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
                        res = requests.get(osrm_url, timeout=2)
                        if res.status_code == 200:
                            osrm_data = res.json()
                            osrm_distance = osrm_data['routes'][0]['distance']
                            if osrm_distance > length * 2.5:
                                edge_geometry = [[lat1, lon1], [lat2, lon2]]
                            else:
                                coords = osrm_data['routes'][0]['geometry']['coordinates']
                                # OSRM returns [lon, lat], Leaflet wants [lat, lon]
                                edge_geometry = [[lat, lon] for lon, lat in coords]
                        else:
                            edge_geometry = [[lat1, lon1], [lat2, lon2]]
                    except Exception:
                        edge_geometry = [[lat1, lon1], [lat2, lon2]]

            details.append({
                "from":      prev_node,
                "to":        node,
                "line":      None if used_line == '__unknown__' else used_line,
                "line_type": self.classify_line(None if used_line == '__unknown__' else used_line, edge_data.get('osm_route')),
                "distance":  length,
                "from_name": self.graph.nodes[prev_node].get('name'),
                "to_name":   self.graph.nodes[node].get('name'),
                "geometry":  edge_geometry,
            })
            path_nodes.append(node)
            state = (prev_node, prev_line)

        if state:
            path_nodes.append(state[0])

        path_nodes.reverse()
        details.reverse()

        # 1. Strip Terminal Same-Station Walks
        if details:
            # Check FIRST segment
            first_seg = details[0]
            if first_seg.get('line') == 'Walk' and str(first_seg.get('from_name', '')).lower() == str(first_seg.get('to_name', '')).lower():
                details.pop(0)
                if path_nodes:
                    path_nodes.pop(0)

        if details:
            # Check LAST segment
            last_seg = details[-1]
            if last_seg.get('line') == 'Walk' and str(last_seg.get('from_name', '')).lower() == str(last_seg.get('to_name', '')).lower():
                details.pop(-1)
                if path_nodes:
                    path_nodes.pop(-1)

        total_distance = sum(d['distance'] for d in details)
        return {
            "success": True,
            "path": path_nodes,
            "details": details,
            "total_distance": total_distance,
        }



    def get_network_data(self):
        """Return nodes and edges for visualization."""
        nodes = []
        for node_id, data in self.graph.nodes(data=True):
            nodes.append(data)

        edges = []
        for u, v, data in self.graph.edges(data=True):
            lines = _normalize_line(data.get('line'))
            display_line = lines[0] if lines else None
            active = not self._is_edge_disabled(data)
            edges.append({
                "source": u,
                "target": v,
                "line": display_line,
                "line_type": self.classify_line(display_line, data.get('osm_route')),
                "length": data.get('length'),
                "active": active,
                "geometry": data.get('geometry', [])
            })

        return {"nodes": nodes, "edges": edges, "disabled_lines": list(self.disabled_lines)}
