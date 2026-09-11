"""Test the retrieval service endpoints (sync + streaming)."""

import json
import sys

import httpx


BASE = "http://localhost:8002"


def test_health() -> None:
    r = httpx.get(f"{BASE}/health", timeout=10)
    r.raise_for_status()
    print("── /health ──")
    print(json.dumps(r.json(), indent=2))
    print()


def test_retrieve_sync(query: str) -> None:
    print(f"── /retrieve/sync :: {query!r} ──")
    r = httpx.post(
        f"{BASE}/retrieve/sync",
        json={"query": query},
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()

    print(f"answer: {data['answer'][:400]}")
    print()
    print(f"trace:  {data['trace']}")
    print()
    print(f"chunks: {len(data['chunks'])}")
    for i, c in enumerate(data["chunks"], 1):
        m = c["chunk"]["metadata"]
        print(f"  {i}. score={c['score']:.4f} retriever={c['retriever']} "
              f"p{m['page']} {m['section']!r}")
        print(f"     {c['chunk']['text'][:100]}...")
    print()
    print(f"citations: {len(data['citations'])}")
    print()


def test_retrieve_stream(query: str) -> None:
    print(f"── /retrieve (SSE) :: {query!r} ──")
    token_count = 0
    saw_citations = False
    saw_done = False
    answer_preview: list[str] = []

    with httpx.stream(
        "POST",
        f"{BASE}/retrieve",
        json={"query": query},
        timeout=120,
    ) as r:
        r.raise_for_status()
        current_event = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                current_event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                payload = line.split(":", 1)[1].strip()
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if current_event == "token":
                    token_count += 1
                    if len(answer_preview) < 40:
                        answer_preview.append(obj["text"])
                elif current_event == "citations":
                    saw_citations = True
                    print(f"  citations: {len(obj['citations'])}")
                elif current_event == "trace":
                    print(f"  trace: {obj['trace']}")
                elif current_event == "done":
                    saw_done = True

    print(f"  tokens received: {token_count}")
    print(f"  answer preview: {''.join(answer_preview)}...")
    print(f"  citations event: {saw_citations}")
    print(f"  done event:      {saw_done}")
    print()


def test_reload() -> None:
    print("── /reload (stub) ──")
    r = httpx.post(f"{BASE}/reload", timeout=10)
    print(f"  {r.status_code}: {r.json()}")
    print()


def main() -> int:
    try:
        test_health()
        test_retrieve_sync("What is the deployment policy?")
        test_retrieve_stream("What is the deployment policy?")
        test_reload()
    except httpx.HTTPError as exc:
        print(f"HTTP error: {exc}", file=sys.stderr)
        return 1
    print("✅ all retrieval endpoints verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())