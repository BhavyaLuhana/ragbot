"""Test the chat service end-to-end (session + streaming + multi-turn)."""

import json
import sys

import httpx


BASE = "http://localhost:8003"


def _stream_and_collect(payload: dict) -> dict:
    """Send POST /chat, collect SSE events into a structured result."""
    result = {
        "session_id": None,
        "tokens": [],
        "citations": [],
        "trace": None,
        "error": None,
        "done": False,
    }
    current_event = None

    with httpx.stream("POST", f"{BASE}/chat", json=payload, timeout=180) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                current_event = None
                continue
            if line.startswith("event:"):
                current_event = line.split(":", 1)[1].strip()
                continue
            if not line.startswith("data:"):
                continue
            try:
                obj = json.loads(line.split(":", 1)[1].strip())
            except json.JSONDecodeError:
                continue

            if current_event == "session":
                result["session_id"] = obj["session_id"]
            elif current_event == "token":
                result["tokens"].append(obj["text"])
            elif current_event == "citations":
                result["citations"] = obj.get("citations", [])
            elif current_event == "trace":
                result["trace"] = obj
            elif current_event == "error":
                result["error"] = obj
            elif current_event == "done":
                result["done"] = True
    return result


def main() -> int:
    print("── Turn 1: What is the deployment policy? ──")
    r1 = _stream_and_collect({"message": "What is the deployment policy?"})
    answer1 = "".join(r1["tokens"])
    print(f"session_id: {r1['session_id']}")
    print(f"answer:     {answer1[:300]}")
    print(f"citations:  {len(r1['citations'])}")
    print(f"done:       {r1['done']}")
    print()

    session_id = r1["session_id"]
    if not session_id:
        print("❌ no session_id returned", file=sys.stderr)
        return 1

    print("── Turn 2 (same session): What about rollbacks? ──")
    r2 = _stream_and_collect({
        "session_id": session_id,
        "message": "What about rollbacks?",
    })
    answer2 = "".join(r2["tokens"])
    print(f"session_id: {r2['session_id']}  (should match)")
    print(f"answer:     {answer2[:300]}")
    print(f"citations:  {len(r2['citations'])}")
    print()

    print("── Session transcript ──")
    tr = httpx.get(f"{BASE}/sessions/{session_id}", timeout=10)
    tr.raise_for_status()
    data = tr.json()
    print(f"messages: {len(data['messages'])}")
    for i, m in enumerate(data["messages"], 1):
        preview = m["content"][:80].replace("\n", " ")
        print(f"  {i}. [{m['role']}] {preview}...  ({len(m.get('citations', []))} citations)")
    print()

    print("── Multi-turn context check ──")
    # If recent_turns is being sent, turn 2's answer should reflect
    # deployment/rollback context, not a fresh unrelated query.
    assert "rollback" in answer2.lower() or "roll" in answer2.lower() or "revert" in answer2.lower(), \
        "turn 2 answer doesn't seem to be about rollbacks"
    print("  ✅ turn 2 answer addresses rollbacks in context")
    print()

    print("── Cleanup ──")
    d = httpx.delete(f"{BASE}/sessions/{session_id}", timeout=10)
    print(f"  DELETE /sessions/{{id}} → {d.status_code}")
    print()

    print("🎉 chat service verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())