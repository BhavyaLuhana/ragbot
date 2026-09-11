"""One-off diagnostic: what does Chroma's list_collections() actually return?"""

from ingestion.ingest import get_chroma_client

c = get_chroma_client()
colls = c.list_collections()
print(f"list_collections() returned: {type(colls).__name__}, len={len(colls)}")
print()

for i, coll in enumerate(colls):
    print(f"--- item {i} ---")
    print(f"  type:      {type(coll).__name__}")
    print(f"  has .name: {hasattr(coll, 'name')}")
    if hasattr(coll, 'name'):
        print(f"  .name:     {coll.name!r}")
    print(f"  has .count:{hasattr(coll, 'count')}")
    if hasattr(coll, 'count'):
        try:
            print(f"  .count():  {coll.count()}")
        except Exception as e:
            print(f"  .count() raised: {type(e).__name__}: {e}")
    print()

# Also: what does get_collection(name) return, and can we read the sentinel?
print("--- sentinel probe ---")
name = "techcorp_handbook"
coll_obj = c.get_collection(name)
print(f"get_collection({name!r}) -> {type(coll_obj).__name__}")
try:
    got = coll_obj.get(ids=["__ingest_sentinel__"], include=["metadatas"])
    print(f"  sentinel .get() returned keys: {list(got.keys())}")
    print(f"  ids:       {got.get('ids')}")
    print(f"  metadatas: {got.get('metadatas')}")
except Exception as e:
    print(f"  sentinel .get() raised: {type(e).__name__}: {e}")