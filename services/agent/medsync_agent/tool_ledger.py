"""Hop ③ bookkeeping: one row per step_key, written BEFORE the external call (INTENT) and marked COMMITTED after.

The row is what turns "the LLM / gateway / device retried" into "return the cached result" instead of a second
booking. A claim lease stops two concurrent dispatches of the same step from both calling the external system.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class Claim(Enum):
    NEW = "new"              # no row existed: nobody has tried this step yet
    RECLAIMED = "reclaimed"  # an earlier attempt left INTENT and its lease expired: outcome unknown, look it up first
    BUSY = "busy"            # another worker holds a live lease on this step
    COMMITTED = "committed"  # already done: use the stored result


@dataclass
class ClaimResult:
    claim: Claim
    result: dict[str, Any] | None = None


class ToolLedger(Protocol):
    def claim(self, step_key: str, tool: str, request: dict[str, Any], lease_s: float) -> ClaimResult: ...
    def commit(self, step_key: str, result: dict[str, Any]) -> None: ...
    def release(self, step_key: str) -> None: ...
    def expire(self, step_key: str) -> None: ...


class InMemoryToolLedger:
    """For tests and for running the agent without Postgres."""

    def __init__(self, clock=time.monotonic) -> None:
        self._rows: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def claim(self, step_key: str, tool: str, request: dict[str, Any], lease_s: float) -> ClaimResult:
        with self._lock:
            now = self._clock()
            row = self._rows.get(step_key)
            if row is None:
                self._rows[step_key] = {"status": "INTENT", "tool": tool, "request": request, "until": now + lease_s}
                return ClaimResult(Claim.NEW)
            if row["status"] == "COMMITTED":
                return ClaimResult(Claim.COMMITTED, row["result"])
            if row["until"] > now:
                return ClaimResult(Claim.BUSY)
            row["until"] = now + lease_s
            return ClaimResult(Claim.RECLAIMED)

    def commit(self, step_key: str, result: dict[str, Any]) -> None:
        with self._lock:
            self._rows[step_key].update(status="COMMITTED", result=result)

    def release(self, step_key: str) -> None:
        """The external system definitively rejected the call (no side effect), so the step may be retried later."""
        with self._lock:
            self._rows.pop(step_key, None)

    def expire(self, step_key: str) -> None:
        """This worker gave up waiting (outcome unknown). Keep INTENT but drop the lease so the next attempt
        reconciles by step_key right away instead of reporting BUSY until the lease runs out."""
        with self._lock:
            if step_key in self._rows and self._rows[step_key]["status"] == "INTENT":
                self._rows[step_key]["until"] = self._clock()


class PostgresToolLedger:
    DDL = """
    CREATE TABLE IF NOT EXISTS tool_ledger (
        step_key TEXT PRIMARY KEY,
        tool TEXT NOT NULL,
        request JSONB NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('INTENT', 'COMMITTED')),
        result JSONB,
        lease_until TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """

    def __init__(self, pool) -> None:  # psycopg_pool.ConnectionPool
        self._pool = pool
        with self._pool.connection() as conn:
            conn.execute(self.DDL)

    def claim(self, step_key: str, tool: str, request: dict[str, Any], lease_s: float) -> ClaimResult:
        with self._pool.connection() as conn, conn.transaction():
            inserted = conn.execute(
                """INSERT INTO tool_ledger (step_key, tool, request, status, lease_until)
                   VALUES (%s, %s, %s, 'INTENT', now() + make_interval(secs => %s))
                   ON CONFLICT (step_key) DO NOTHING RETURNING step_key""",
                (step_key, tool, json.dumps(request), lease_s),
            ).fetchone()
            if inserted:
                return ClaimResult(Claim.NEW)
            row = conn.execute(
                "SELECT status, result, lease_until > now() AS live FROM tool_ledger WHERE step_key = %s FOR UPDATE",
                (step_key,),
            ).fetchone()
            status, result, live = row["status"], row["result"], row["live"]
            if status == "COMMITTED":
                return ClaimResult(Claim.COMMITTED, result)
            if live:
                return ClaimResult(Claim.BUSY)
            conn.execute(
                "UPDATE tool_ledger SET lease_until = now() + make_interval(secs => %s), updated_at = now() "
                "WHERE step_key = %s",
                (lease_s, step_key),
            )
            return ClaimResult(Claim.RECLAIMED)

    def commit(self, step_key: str, result: dict[str, Any]) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE tool_ledger SET status = 'COMMITTED', result = %s, updated_at = now() WHERE step_key = %s",
                (json.dumps(result), step_key),
            )

    def release(self, step_key: str) -> None:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM tool_ledger WHERE step_key = %s AND status = 'INTENT'", (step_key,))

    def expire(self, step_key: str) -> None:
        with self._pool.connection() as conn:
            conn.execute("UPDATE tool_ledger SET lease_until = now() WHERE step_key = %s AND status = 'INTENT'",
                         (step_key,))
