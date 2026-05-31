import json

d = json.load(open('data/cologne_network.json', 'r', encoding='utf-8'))

# Count edges per line to understand which are real transit lines vs internal IDs
line_edge_count = {}
for e in d['edges']:
    ln = e['line']
    if isinstance(ln, list):
        for x in ln:
            line_edge_count[str(x)] = line_edge_count.get(str(x), 0) + 1
    else:
        line_edge_count[str(ln)] = line_edge_count.get(str(ln), 0) + 1

# Sort by edge count descending
sorted_lines = sorted(line_edge_count.items(), key=lambda x: -x[1])

print("=== TOP 40 LINES BY EDGE COUNT ===")
for ln, cnt in sorted_lines[:40]:
    try:
        n = int(ln)
        is_numeric = True
    except ValueError:
        is_numeric = False
    print(f"  '{ln}': {cnt} edges {'(numeric)' if is_numeric else '(named)'}")

print(f"\n=== BOTTOM 20 LINES BY EDGE COUNT ===")
for ln, cnt in sorted_lines[-20:]:
    print(f"  '{ln}': {cnt} edges")

# Lines with > 10 edges (likely real transit lines)
real_lines = [(ln, cnt) for ln, cnt in sorted_lines if cnt >= 10]
print(f"\nLines with >= 10 edges: {len(real_lines)}")
for ln, cnt in real_lines:
    print(f"  '{ln}': {cnt} edges")
