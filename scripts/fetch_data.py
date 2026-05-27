import osmnx as ox
import networkx as nx
import json
import os
import hashlib
from collections import defaultdict, deque, Counter

UNKNOWN_LINE = "Unknown Line"


def _generate_unknown_line_codes(nodes_data, edges_data):
    nodes = {node["id"]: node for node in nodes_data}
    unknown_edges = [edge for edge in edges_data if edge.get("line") == UNKNOWN_LINE]
    used_codes = {
        str(edge.get("line"))
        for edge in edges_data
        if str(edge.get("line", "")).isdigit() and len(str(edge.get("line"))) == 4
    }

    adjacency = defaultdict(set)
    for edge in unknown_edges:
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])

    seen = set()
    components = []
    for start in adjacency:
        if start in seen:
            continue

        queue = deque([start])
        seen.add(start)
        component = []

        while queue:
            node_id = queue.popleft()
            component.append(node_id)
            for neighbor in adjacency[node_id]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)

        components.append(component)

    node_to_code = {}
    codes = []
    for component in components:
        lat = sum(nodes[node_id]["lat"] for node_id in component) / len(component)
        lon = sum(nodes[node_id]["lon"] for node_id in component) / len(component)
        lat_q = round((lat + 90) * 100000)
        lon_q = round((lon + 180) * 100000)
        seed = f"{lat_q}:{lon_q}:" + ",".join(map(str, sorted(component)))
        preferred = int.from_bytes(
            hashlib.blake2s(
                seed.encode("utf-8"),
                digest_size=2,
            ).digest(),
            "big",
        ) % 10000

        value = preferred
        while True:
            code = f"{value:04d}"
            if code not in used_codes:
                break
            value = (value + 1) % 10000
            if value == preferred:
                raise ValueError("No free 4-digit code left for unknown lines")

        used_codes.add(code)
        codes.append(code)
        for node_id in component:
            node_to_code[node_id] = code

    duplicated_codes = [code for code, count in Counter(codes).items() if count > 1]
    if duplicated_codes:
        raise ValueError(f"Duplicate generated unknown line codes: {duplicated_codes[:10]}")

    changed = 0
    for edge in edges_data:
        if edge.get("line") == UNKNOWN_LINE:
            edge["line"] = node_to_code[edge["source"]]
            changed += 1

    print(f"Generated {len(codes)} 4-digit unknown-line codes for {changed} edges.")
    return sorted(codes)

def fetch_cologne_transit():
    print("Fetching Cologne transit data...")
    place_name = "Cologne, Germany"
    
    # Define transit tags
    custom_filter = '["railway"~"subway|tram|light_rail|rail"]'
    
    try:
        # Get graph from OSM
        G = ox.graph_from_place(place_name, custom_filter=custom_filter, retain_all=True)
        
        print(f"Retrieved {G.number_of_nodes()} nodes and {G.number_of_edges()} edges.")
        
        # 1. Giữ lại thành phần liên thông lớn nhất (optional, nhưng tốt cho pathfinding)
        # Đối với transit, có thể có nhiều thành phần rời rạc (ví dụ: các tuyến không nối nhau)
        # Nhưng thường chúng nối nhau qua các trạm trung chuyển.
        
        # 2. Chuyển đổi sang định dạng có thể lưu JSON
        # Chúng ta cần: Danh sách trạm (nodes) và Danh sách kết nối (edges)
        
        nodes_data = []
        for node, data in G.nodes(data=True):
            nodes_data.append({
                "id": node,
                "lat": data.get('y'),
                "lon": data.get('x'),
                "name": data.get('name', f"Station {node}")
            })
            
        edges_data = []
        for u, v, data in G.edges(data=True):
            # Lấy tên tuyến (ví dụ: Line 1, S11, ...)
            # Trong OSM, railway lines thường có tag 'route' hoặc 'ref'
            line_name = data.get('ref', data.get('name', UNKNOWN_LINE))
            
            # Tính khoảng cách (độ dài cạnh)
            length = data.get('length', 0)
            
            edges_data.append({
                "source": u,
                "target": v,
                "line": line_name,
                "length": length,
                "oneway": data.get('oneway', False)
            })

        generated_unknown_lines = _generate_unknown_line_codes(nodes_data, edges_data)
            
        network = {
            "nodes": nodes_data,
            "edges": edges_data
        }
        
        # Lưu vào thư mục data
        output_path = os.path.join("data", "cologne_network.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(network, f, ensure_ascii=False, indent=4)

        generated_lines_path = os.path.join("data", "generated_unknown_lines.json")
        with open(generated_lines_path, "w", encoding="utf-8") as f:
            json.dump(generated_unknown_lines, f, ensure_ascii=False, indent=4)
            
        print(f"Success! Data saved at: {output_path}")
        
    except Exception as e:
        print(f"Error fetching data: {e}")

if __name__ == "__main__":
    # Đảm bảo thư mục data tồn tại
    if not os.path.exists("data"):
        os.makedirs("data")
    fetch_cologne_transit()
