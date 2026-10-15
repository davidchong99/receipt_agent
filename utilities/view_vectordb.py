from qdrant_client import QdrantClient

client = QdrantClient(path="../memory/qdrant")  # the same path your app used

print(client.get_collections())
points, _ = client.scroll("knowledge", limit=10, with_payload=True)
for p in points:
    print(p.id, p.payload)
client.close()
