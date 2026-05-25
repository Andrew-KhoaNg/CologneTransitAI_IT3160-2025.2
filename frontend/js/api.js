const API_BASE_URL = `${window.location.origin}/api`;

const TransitAPI = {
    async getNetwork() {
        const response = await fetch(`${API_BASE_URL}/network`);
        return await response.json();
    },

    async getLines() {
        const response = await fetch(`${API_BASE_URL}/lines`);
        return await response.json();
    },

    async findPath(startNode, endNode) {
        const response = await fetch(`${API_BASE_URL}/find-path`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ start_node: startNode, end_node: endNode })
        });
        return await response.json();
    },

    async getAdminStatus() {
        const response = await fetch(`${API_BASE_URL}/admin/status`, {
            credentials: 'same-origin'
        });
        return await response.json();
    },

    async adminLogin(password) {
        const response = await fetch(`${API_BASE_URL}/admin/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ password })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Admin login failed');
        return data;
    },

    async adminLogout() {
        const response = await fetch(`${API_BASE_URL}/admin/logout`, {
            method: 'POST',
            credentials: 'same-origin'
        });
        return await response.json();
    },

    async toggleLine(lineName, disabled) {
        const response = await fetch(`${API_BASE_URL}/admin/toggle-line`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ line: lineName, disabled: disabled })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Cannot update line');
        return data;
    }
};
