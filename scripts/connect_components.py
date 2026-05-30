import json
import math
import os
from pathlib import Path

import networkx as nx


DATA_PATH = Path("data/cologne_network.json")
UNKNOWN_LINE = "Unknown Line"
GENERATED_REASON = "connect_components"
PLACE_NAME = "Cologne, Germany"
MPLCONFIGDIR = Path(".matplotlib").resolve()
CACHE_DIR = Path("cache").resolve()

os.environ.setdefault("MPLCONFIGDIR", str(MPLCONFIGDIR))


def haversine_distance(lat1, lon1, lat2, lon2):
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return radius * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def node_coord(node):
    return float(node["lat"]), float(node["lon"])


def nearest_pair(source_component, target_component, nodes_by_id):
    best = None
    for source_id in source_component:
        source_node = nodes_by_id[source_id]
        if source_node.get("lat") is None or source_node.get("lon") is None:
            continue
        source_lat, source_lon = node_coord(source_node)

        for target_id in target_component:
            target_node = nodes_by_id[target_id]
            if target_node.get("lat") is None or target_node.get("lon") is None:
                continue
            target_lat, target_lon = node_coord(target_node)
            distance = haversine_distance(source_lat, source_lon, target_lat, target_lon)
            if best is None or distance < best[0]:
                best = (distance, source_id, target_id)

    if best is None:
        raise ValueError("Cannot connect components with missing coordinates")
    return best


def load_walk_graph():
    import osmnx as ox

    MPLCONFIGDIR.mkdir(exist_ok=True)
    CACHE_DIR.mkdir(exist_ok=True)
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(CACHE_DIR)
    print(f"Fetching/loading walk network for {PLACE_NAME}...")
    walk_graph = ox.graph_from_place(PLACE_NAME, network_type="walk", retain_all=True)
    walk_graph = ox.convert.to_undirected(walk_graph)
    walk_graph.graph["_component_id"] = {
        node_id: component_index
        for component_index, component in enumerate(nx.connected_components(walk_graph))
        for node_id in component
    }
    return walk_graph


def build_walk_node_grid(walk_graph):
    cell_size = 0.005
    grid = {}
    for node_id, data in walk_graph.nodes(data=True):
        if data.get("y") is None or data.get("x") is None:
            continue
        row = math.floor(data["y"] / cell_size)
        col = math.floor(data["x"] / cell_size)
        grid.setdefault((row, col), []).append((node_id, data["y"], data["x"]))

    walk_graph.graph["_coord_grid"] = grid
    walk_graph.graph["_coord_cell_size"] = cell_size
    return grid, cell_size


def nearest_walk_node(walk_graph, transit_node):
    return nearest_walk_nodes(walk_graph, transit_node, limit=1)[0][0]


def nearest_walk_nodes(walk_graph, transit_node, limit=8):
    cache = walk_graph.graph.setdefault("_nearest_transit_walk_nodes", {})
    cache_key = (transit_node["id"], limit)
    if cache_key in cache:
        return cache[cache_key]

    lat, lon = node_coord(transit_node)
    grid = walk_graph.graph.get("_coord_grid")
    cell_size = walk_graph.graph.get("_coord_cell_size")
    if grid is None or cell_size is None:
        grid, cell_size = build_walk_node_grid(walk_graph)

    row = math.floor(lat / cell_size)
    col = math.floor(lon / cell_size)
    candidates = []
    search_radius = 0
    seen_cells = set()
    while len(candidates) < limit and search_radius < 20:
        for r in range(row - search_radius, row + search_radius + 1):
            for c in range(col - search_radius, col + search_radius + 1):
                if (r, c) in seen_cells:
                    continue
                seen_cells.add((r, c))
                candidates.extend(grid.get((r, c), []))
        search_radius += 1

    # Include one more ring so points near a cell boundary do not choose worse
    # candidates just because they share the same grid cell.
    for r in range(row - search_radius, row + search_radius + 1):
        for c in range(col - search_radius, col + search_radius + 1):
            if (r, c) in seen_cells:
                continue
            seen_cells.add((r, c))
            candidates.extend(grid.get((r, c), []))

    nearest = sorted(
        (
            (node_id, haversine_distance(lat, lon, node_lat, node_lon))
            for node_id, node_lat, node_lon in candidates
        ),
        key=lambda item: item[1],
    )[:limit]
    cache[cache_key] = nearest
    return nearest


def nearest_routable_pair(source_component, target_component, nodes_by_id, walk_graph):
    component_ids = walk_graph.graph["_component_id"]
    best = None

    for source_id in source_component:
        source_node = nodes_by_id[source_id]
        source_lat, source_lon = node_coord(source_node)
        source_walk_nodes = nearest_walk_nodes(walk_graph, source_node)

        for target_id in target_component:
            target_node = nodes_by_id[target_id]
            target_lat, target_lon = node_coord(target_node)
            straight_distance = haversine_distance(source_lat, source_lon, target_lat, target_lon)
            target_walk_nodes = nearest_walk_nodes(walk_graph, target_node)

            for source_walk_node, source_access in source_walk_nodes:
                source_walk_component = component_ids.get(source_walk_node)
                if source_walk_component is None:
                    continue

                for target_walk_node, target_access in target_walk_nodes:
                    if component_ids.get(target_walk_node) != source_walk_component:
                        continue

                    score = straight_distance + source_access + target_access
                    if best is None or score < best[0]:
                        best = (
                            score,
                            straight_distance,
                            source_id,
                            target_id,
                            source_walk_node,
                            target_walk_node,
                        )

    if best is None:
        raise nx.NetworkXNoPath("No routable walking transfer found between components")
    return best[1:]


def best_parallel_edge(edge_data):
    return min(edge_data.values(), key=lambda data: data.get("length", float("inf")))


def edge_geometry(walk_graph, u, v):
    edge = best_parallel_edge(walk_graph.get_edge_data(u, v))
    if edge.get("geometry") is not None:
        coords = list(edge["geometry"].coords)
        return [[lat, lon] for lon, lat in coords], edge.get("length", 0)

    start = walk_graph.nodes[u]
    end = walk_graph.nodes[v]
    return [[start["y"], start["x"]], [end["y"], end["x"]]], edge.get("length", 0)


def walking_route_geometry(walk_graph, source_node, target_node, source_walk_node, target_walk_node):
    source_access = haversine_distance(
        source_node["lat"],
        source_node["lon"],
        walk_graph.nodes[source_walk_node]["y"],
        walk_graph.nodes[source_walk_node]["x"],
    )
    target_access = haversine_distance(
        target_node["lat"],
        target_node["lon"],
        walk_graph.nodes[target_walk_node]["y"],
        walk_graph.nodes[target_walk_node]["x"],
    )

    if source_walk_node == target_walk_node:
        shared = walk_graph.nodes[source_walk_node]
        geometry = [
            [source_node["lat"], source_node["lon"]],
            [shared["y"], shared["x"]],
            [target_node["lat"], target_node["lon"]],
        ]
        return geometry, source_access + target_access

    route = nx.shortest_path(
        walk_graph,
        source_walk_node,
        target_walk_node,
        weight="length",
    )
    if not route or len(route) < 2:
        raise nx.NetworkXNoPath("No walking route found")

    geometry = [[source_node["lat"], source_node["lon"]]]
    total_length = source_access + target_access

    for u, v in zip(route, route[1:]):
        segment_geometry, segment_length = edge_geometry(walk_graph, u, v)
        if geometry[-1] == segment_geometry[0]:
            geometry.extend(segment_geometry[1:])
        else:
            geometry.extend(segment_geometry)
        total_length += segment_length

    if geometry[-1] != [target_node["lat"], target_node["lon"]]:
        geometry.append([target_node["lat"], target_node["lon"]])

    return geometry, total_length


def main():
    with DATA_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    old_edge_count = len(data["edges"])
    data["edges"] = [
        edge for edge in data["edges"]
        if edge.get("generated_reason") != GENERATED_REASON
    ]
    removed_edges = old_edge_count - len(data["edges"])

    nodes_by_id = {node["id"]: node for node in data["nodes"]}
    graph = nx.Graph()
    graph.add_nodes_from(nodes_by_id)

    existing_edges = set()
    for edge in data["edges"]:
        source = edge["source"]
        target = edge["target"]
        graph.add_edge(source, target)
        existing_edges.add(tuple(sorted((source, target))))

    components = [set(component) for component in nx.connected_components(graph)]
    components.sort(key=len, reverse=True)
    if len(components) <= 1:
        print(f"Removed {removed_edges} old generated edges.")
        print("Graph is already connected.")
        return

    walk_graph = load_walk_graph()
    main_component = set(components[0])
    added_edges = []

    for component in components[1:]:
        distance, source, target, source_walk_node, target_walk_node = nearest_routable_pair(
            component,
            main_component,
            nodes_by_id,
            walk_graph,
        )
        key = tuple(sorted((source, target)))
        if key in existing_edges:
            main_component.update(component)
            continue

        source_node = nodes_by_id[source]
        target_node = nodes_by_id[target]
        geometry, walking_length = walking_route_geometry(
            walk_graph,
            source_node,
            target_node,
            source_walk_node,
            target_walk_node,
        )
        edge = {
            "source": source,
            "target": target,
            "line": UNKNOWN_LINE,
            "length": walking_length,
            "oneway": False,
            "geometry": geometry,
            "generated": True,
            "generated_reason": GENERATED_REASON,
            "generated_mode": "walk",
            "straight_line_distance": distance,
        }
        data["edges"].append(edge)
        graph.add_edge(source, target)
        existing_edges.add(key)
        added_edges.append(edge)
        main_component.update(component)

    with DATA_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        f.write("\n")

    final_components = nx.number_connected_components(graph)
    print(f"Removed {removed_edges} old generated edges.")
    print(f"Added {len(added_edges)} generated walking {UNKNOWN_LINE} edges.")
    print(f"Components after update: {final_components}")


if __name__ == "__main__":
    main()
