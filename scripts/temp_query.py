import requests

query = """
[out:json];
area["name"="Köln"]["admin_level"="6"]->.a;
relation["type"="route"]["route"~"train|railway"](area.a);
out tags;
"""

headers = {"User-Agent": "CologneTransitAI/1.0 (Python script)"}
r = requests.post('http://overpass-api.de/api/interpreter', data=query, headers=headers)
data = r.json()
print("Found", len(data['elements']), "relations")
for el in data['elements'][:20]:
    tags = el.get('tags', {})
    ref = tags.get('ref', '')
    name = tags.get('name', '')
    route = tags.get('route', '')
    print(f"ID: {el['id']}, Route: {route}, Ref: {ref}, Name: {name}")
