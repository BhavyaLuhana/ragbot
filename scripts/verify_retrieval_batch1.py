"""Verify Batch 1: BM25 load, dense search, sparse search, RRF fusion."""

import asyncio

from retrieval.bm25_index import load_index
from retrieval.dense import DenseRetriever, get_chroma_client, get_collection
from retrieval.sparse import SparseRetriever
from retrieval.fusion import rrf_fuse
from shared.providers.factory import get_embedding_provider


async def main() -> None:
    # ── Load ────────────────────────────────────────────────
    print("Loading BM25 index...")
    bm25 = load_index()
    print(f"  chunks: {len(bm25)}")

    print("Opening Chroma...")
    client = get_chroma_client()
    coll = get_collection(client)
    print(f"  collection: {coll.name}  count: {coll.count()}")

    embedder = get_embedding_provider()
    print(f"  embedder: {embedder.model_name} ({embedder.dimension}d)")

    dense = DenseRetriever(coll, embedder)
    sparse = SparseRetriever(bm25)

    query = "What is the deployment policy?"
    print(f"\nQuery: {query!r}\n")

    # ── Dense ───────────────────────────────────────────────
    print("── Dense (top 5) ──")
    d = await dense.search(query, top_k=5)
    for i, s in enumerate(d, 1):
        m = s.chunk.metadata
        print(f"  {i}. score={s.score:.4f}  p{m.page}  {m.section!r}")
        print(f"     {s.chunk.text[:100]}...")

    # ── Sparse ──────────────────────────────────────────────
    print("\n── Sparse (top 5) ──")
    s = sparse.search(query, top_k=5)
    for i, sc in enumerate(s, 1):
        m = sc.chunk.metadata
        print(f"  {i}. score={sc.score:.4f}  p{m.page}  {m.section!r}")
        print(f"     {sc.chunk.text[:100]}...")

    # ── Fusion ──────────────────────────────────────────────
    print("\n── RRF fusion (top 5) ──")
    fused = rrf_fuse([d, s], top_k=5)
    for i, sc in enumerate(fused, 1):
        m = sc.chunk.metadata
        print(f"  {i}. rrf={sc.score:.4f}  p{m.page}  {m.section!r}")
        print(f"     {sc.chunk.text[:100]}...")

    print("\n✅ Batch 1 verified")


if __name__ == "__main__":
    asyncio.run(main())