"""
In-memory session store (ADR-023).

Single-process, in-memory dict of conversation histories. TTL eviction
is lazy — checked on `get()` and `append()`, never on a background
thread. For a demo-scale app with one service replica, this is
sufficient and honest.

Production swap: Redis (or Postgres) with the same interface. Only
`SessionStore` implementation changes; the rest of the service stays put.

Threading note:
- FastAPI handlers run in the event loop, so a plain dict is safe as
  long as we never await between mutation operations. We don't.
- If we ever add background tasks, add an asyncio.Lock per session.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from shared.config.settings import settings
from shared.logging.setup import get_logger
from shared.schemas.chat import ChatMessage

log = get_logger(__name__)


@dataclass
class Session:
    """One conversation."""

    session_id: str
    created_at: float
    updated_at: float
    messages: list[ChatMessage] = field(default_factory=list)

    def is_expired(self, ttl: int, now: float | None = None) -> bool:
        t = now if now is not None else time.monotonic()
        return (t - self.updated_at) > ttl

    def touch(self) -> None:
        self.updated_at = time.monotonic()


class SessionStore:
    """
    In-memory session storage with lazy TTL eviction.

    All methods are synchronous (no I/O). `evict_expired()` runs inside
    `get()` and `append()` on the accessed session only, plus a bounded
    sweep on `create()` to keep the dict from growing unboundedly.
    """

    def __init__(self, ttl_seconds: int | None = None) -> None:
        self._ttl = ttl_seconds if ttl_seconds is not None else settings.session_ttl_seconds
        self._sessions: dict[str, Session] = {}

    # ── public API ──────────────────────────────────────────
    def create(self) -> Session:
        """Create a new session with a fresh UUID."""
        now = time.monotonic()
        sid = str(uuid.uuid4())
        session = Session(session_id=sid, created_at=now, updated_at=now)
        self._sessions[sid] = session
        self._sweep()
        log.info("session_created", session_id=sid, total=len(self._sessions))
        return session

    def get(self, session_id: str) -> Session | None:
        """Return the session or None if missing/expired. Lazy eviction."""
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.is_expired(self._ttl):
            del self._sessions[session_id]
            log.info("session_expired_on_get", session_id=session_id)
            return None
        return session

    def get_or_create(self, session_id: str | None) -> tuple[Session, bool]:
        """
        Return (session, created).

        If `session_id` is None, creates a new session.
        If provided but missing/expired, creates a new one (does NOT
        silently reuse an expired id — clients should treat the returned
        id as authoritative).
        """
        if session_id is not None:
            existing = self.get(session_id)
            if existing is not None:
                return existing, False
        return self.create(), True

    def append(self, session_id: str, message: ChatMessage) -> Session | None:
        """Append a message to a session. Returns the updated session."""
        session = self.get(session_id)
        if session is None:
            return None
        session.messages.append(message)
        session.touch()
        # Trim to the last N turns so long sessions don't grow forever.
        max_messages = settings.session_max_turns * 2  # user + assistant per turn
        if len(session.messages) > max_messages:
            session.messages = session.messages[-max_messages:]
        return session

    def delete(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def stats(self) -> dict[str, Any]:
        return {
            "sessions": len(self._sessions),
            "ttl_seconds": self._ttl,
        }

    # ── private ─────────────────────────────────────────────
    def _sweep(self) -> None:
        """
        Cheap full sweep — runs on `create()`. Fine for a demo: we don't
        create sessions in a hot loop. If this ever becomes a bottleneck,
        switch to a heap keyed by `updated_at`.
        """
        now = time.monotonic()
        expired = [
            sid for sid, s in self._sessions.items()
            if s.is_expired(self._ttl, now)
        ]
        for sid in expired:
            del self._sessions[sid]
        if expired:
            log.info("session_sweep", evicted=len(expired), remaining=len(self._sessions))


__all__ = ["Session", "SessionStore"]