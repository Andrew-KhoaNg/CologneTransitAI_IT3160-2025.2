import heapq
import networkx as nx
import json
import os


def _normalize_line(line):
    """Normalize a line value to a list of strings (handles str, list, None)."""
    if line is None:
        return []
    if isinstance(line, list):
        return [str(l) for l in line]
    return [str(line)]


def classify_line(line_name, encoded_unknown_lines=None):
    """Classify a line name into 'rail', 'sub', or 'train'.
    - rail  : named lines (SB-*, Nord-Süd-Stadtbahn, Innenstadttunnel, ...)
    - sub   : numeric 1-99  (KVB Stadtbahn / light-rail, e.g. 18, 20 ...)
    - train : numeric 4-digit (regional / S-Bahn, e.g. 2600, 7454 ...)
    """
    if not line_name or line_name == 'Unknown Line':
        return 'sub'          # default fallback
    if encoded_unknown_lines and str(line_name) in encoded_unknown_lines:
        return 'sub'
    try:
        n = int(line_name)
        if 1 <= n <= 99:
            return 'sub'
        return 'train'
    except ValueError:
        return 'rail'


class TransitEngine:
    def __init__(self, data_path, disabled_lines=None, encoded_unknown_lines=None):
        self.data_path = data_path
        self.graph = nx.Graph()
        self.disabled_lines = set(disabled_lines or [])
        self.encoded_unknown_lines = set(encoded_unknown_lines or [])
        self.node_coords = {}
        self.load_network()

    def classify_line(self, line_name):
        return classify_line(line_name, self.encoded_unknown_lines)

    def load_network(self):
        if not os.path.exists(self.data_path):
            print(f"Warning: Data file {self.data_path} not found.")
            return

        with open(self.data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Add nodes and cache their coordinates for heuristic evaluation
        for node in data['nodes']:
            self.graph.add_node(node['id'], **node)
            lat = node.get('lat')
            lon = node.get('lon')
            if lat is not None and lon is not None:
                try:
                    self.node_coords[node['id']] = (float(lat), float(lon))
                except (TypeError, ValueError):
                    pass

        # Add edges
        for edge in data['edges']:
            self.graph.add_edge(
                edge['source'],
                edge['target'],
                line=edge['line'],
                weight=edge['length'],
                length=edge['length'],
                geometry=edge.get('geometry', [])
            )

        print(f"Loaded graph with {self.graph.number_of_nodes()} nodes and {self.graph.number_of_edges()} edges.")

    def _is_edge_disabled(self, edge_data):
        """Return True if ALL lines of this edge are disabled (or has no lines)."""
        lines = _normalize_line(edge_data.get('line'))
        if not lines:
            return False  # unknown line, keep active
        # Edge is disabled only when every line it belongs to is disabled
        return all(line in self.disabled_lines for line in lines)

    @staticmethod
    def haversine_distance(lat1, lon1, lat2, lon2):
        """Return great-circle distance between two points in meters."""
        import math
        radius = 6371000.0  # Earth radius in meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return radius * c

    def heuristic(self, node_id, target_node_id):
        """Admissible heuristic using geographic straight-line distance."""
        if node_id == target_node_id:
            return 0.0
        coords_a = self.node_coords.get(node_id)
        coords_b = self.node_coords.get(target_node_id)
        if coords_a is None or coords_b is None:
            return 0.0
        return self.haversine_distance(coords_a[0], coords_a[1], coords_b[0], coords_b[1])

    def get_all_lines(self):
        """Return sorted list of dicts: {name, type} for each unique line."""
        lines = {}
        for u, v, data in self.graph.edges(data=True):
            for line in _normalize_line(data.get('line')):
                if line not in lines:
                    lines[line] = self.classify_line(line)
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
        """Shortest path with transfer penalty using A* search.
        Adds TRANSFER_PENALTY meters to cost each time the line changes,
        so paths with fewer line switches are preferred if distances are similar.
        """
        TRANSFER_PENALTY = 300  # metres — tolerate up to 300 m extra to avoid 1 transfer
        INF = float('inf')

        if start_node_id == end_node_id:
            return {"success": True, "path": [start_node_id], "details": [], "total_distance": 0}

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

        start_lines = {ln for (_, ln, _, _) in adj.get(start_node_id, [])}
        if not start_lines:
            return {"success": False, "error": "Start node has no active connections"}

        g_score = {}
        prev = {}
        heap = []
        h_cache = {}
        counter = 0
        target_h = self.heuristic(start_node_id, end_node_id)
        h_cache[start_node_id] = target_h

        for line in start_lines:
            state = (start_node_id, line)
            g_score[state] = 0
            prev[state] = None
            heapq.heappush(heap, (target_h, counter, start_node_id, line))
            counter += 1

        visited = set()
        best_state = None

        while heap:
            f_cost, _, node, cur_line = heapq.heappop(heap)
            state = (node, cur_line)
            if state in visited:
                continue
            visited.add(state)

            if node == end_node_id:
                best_state = state
                break

            current_g = g_score[state]
            for nbr, next_line, length, edge_data in adj.get(node, []):
                penalty = TRANSFER_PENALTY if next_line != cur_line else 0
                tentative_g = current_g + length + penalty
                nstate = (nbr, next_line)

                if tentative_g < g_score.get(nstate, INF):
                    g_score[nstate] = tentative_g
                    prev[nstate] = (node, cur_line, edge_data, next_line)
                    h = h_cache.get(nbr)
                    if h is None:
                        h = self.heuristic(nbr, end_node_id)
                        h_cache[nbr] = h
                    f_score = tentative_g + h
                    heapq.heappush(heap, (f_score, counter, nbr, next_line))
                    counter += 1

        if best_state is None:
            # If A* terminated without reaching goal, fall back to best known end state
            best_cost = INF
            for (node, line), c in g_score.items():
                if node == end_node_id and c < best_cost:
                    best_cost = c
                    best_state = (node, line)

        if best_state is None:
            return {"success": False, "error": "No path found (lines might be disabled)"}

        details = []
        path_nodes = []
        state = best_state

        while state is not None and prev.get(state) is not None:
            node, line = state
            prev_node, prev_line, edge_data, used_line = prev[state]
            length = edge_data.get('length', 0)
            edge_geometry = edge_data.get('geometry', [])
            if edge_geometry and len(edge_geometry) > 1:
                prev_lat = self.graph.nodes[prev_node].get('lat', 0)
                prev_lon = self.graph.nodes[prev_node].get('lon', 0)
                geo_start = edge_geometry[0]
                geo_end = edge_geometry[-1]
                dist_to_start = (prev_lat - geo_start[0])**2 + (prev_lon - geo_start[1])**2
                dist_to_end = (prev_lat - geo_end[0])**2 + (prev_lon - geo_end[1])**2
                if dist_to_end < dist_to_start:
                    edge_geometry = list(reversed(edge_geometry))

            details.append({
                "from":      prev_node,
                "to":        node,
                "line":      None if used_line == '__unknown__' else used_line,
                "line_type": self.classify_line(None if used_line == '__unknown__' else used_line),
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
                "line_type": self.classify_line(display_line),
                "length": data.get('length'),
                "active": active,
                "geometry": data.get('geometry', [])
            })

        return {"nodes": nodes, "edges": edges, "disabled_lines": list(self.disabled_lines)}
