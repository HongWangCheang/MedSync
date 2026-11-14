"""Findings board: where online agents post conclusions that queued steps may not have known about.

The device plans offline. "吃了布洛芬，告诉女儿我没事" becomes a medication record and a queued notification, both
decided before any server-side agent has looked at them. Once online, the safety review (and the pharmacist, when its
answer shows a label warning about a combination) posts what it concluded here. Before an irreversible step runs,
the step graph asks the board for findings its planner could not have seen; conflicts.py decides whether they
contradict the step.

A finding is "unseen by the planner" when it belongs to the same plan, or when it was posted after the step was
planned and concerns something that happened no more than LOOKBACK_MS before that. Posting is idempotent per
(account, step, kind), because a node that resumes after a crash runs again.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

LOOKBACK_MS = 24 * 3_600_000

Severity = Literal["high", "moderate"]


@dataclass(frozen=True)
class Finding:
    account_id: str
    step_key: str         # the step whose processing produced it
    plan_id: str
    source: str           # "safety_review" | "pharmacist"
    kind: str             # "safety_alert" | "label_interaction"
    severity: Severity
    summary: str          # one sentence the user can read
    event_at_ms: int      # when the thing it is about happened (the dose was taken, the question was asked)
    detail: dict[str, Any] = field(default_factory=dict)  # alerts / citations; never tokens
    posted_at_ms: int = 0


def now_ms() -> int:
    return int(time.time() * 1000)


class FindingsBoard(Protocol):
    def post(self, finding: Finding) -> None: ...
    def unseen_by(self, account_id: str, plan_id: str, step_key: str, planned_at_ms: int) -> list[Finding]: ...


def _unseen(f: Finding, account_id: str, plan_id: str, step_key: str, planned_at_ms: int) -> bool:
    if f.account_id != account_id or f.step_key == step_key:
        return False
    if f.plan_id == plan_id:
        return True  # same utterance: the planner could not have known, whatever the device clock says
    return f.posted_at_ms > planned_at_ms and f.event_at_ms >= planned_at_ms - LOOKBACK_MS


class InMemoryFindingsBoard:
    def __init__(self, clock=now_ms) -> None:
        self._rows: dict[tuple[str, str, str], Finding] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def post(self, finding: Finding) -> None:
        with self._lock:
            key = (finding.account_id, finding.step_key, finding.kind)
            if key not in self._rows:
                self._rows[key] = Finding(**{**asdict(finding), "posted_at_ms": self._clock()})

    def unseen_by(self, account_id: str, plan_id: str, step_key: str, planned_at_ms: int) -> list[Finding]:
        with self._lock:
            rows = list(self._rows.values())
        return sorted((f for f in rows if _unseen(f, account_id, plan_id, step_key, planned_at_ms)),
                      key=lambda f: (f.severity != "high", -f.posted_at_ms))


class PostgresFindingsBoard:
    DDL = """
    CREATE TABLE IF NOT EXISTS agent_finding (
        account_id TEXT NOT NULL,
        step_key TEXT NOT NULL,
        kind TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        source TEXT NOT NULL,
        severity TEXT NOT NULL CHECK (severity IN ('high', 'moderate')),
        summary TEXT NOT NULL,
        detail JSONB NOT NULL,
        event_at_ms BIGINT NOT NULL,
        posted_at_ms BIGINT NOT NULL,
        PRIMARY KEY (account_id, step_key, kind)
    )
    """
    INDEX = "CREATE INDEX IF NOT EXISTS agent_finding_recent ON agent_finding (account_id, posted_at_ms)"

    def __init__(self, pool) -> None:  # psycopg_pool.ConnectionPool with dict rows
        self._pool = pool
        with self._pool.connection() as conn:
            conn.execute(self.DDL)  # one statement per execute: the pool's connections use prepared statements
            conn.execute(self.INDEX)

    def post(self, finding: Finding) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """INSERT INTO agent_finding (account_id, step_key, kind, plan_id, source, severity, summary, detail,
                                             event_at_ms, posted_at_ms)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (account_id, step_key, kind) DO NOTHING""",
                (finding.account_id, finding.step_key, finding.kind, finding.plan_id, finding.source,
                 finding.severity, finding.summary, json.dumps(finding.detail, ensure_ascii=False),
                 finding.event_at_ms, now_ms()),
            )

    def unseen_by(self, account_id: str, plan_id: str, step_key: str, planned_at_ms: int) -> list[Finding]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM agent_finding
                   WHERE account_id = %s AND step_key <> %s
                     AND (plan_id = %s OR (posted_at_ms > %s AND event_at_ms >= %s))
                   ORDER BY severity <> 'high', posted_at_ms DESC LIMIT 20""",
                (account_id, step_key, plan_id, planned_at_ms, planned_at_ms - LOOKBACK_MS),
            ).fetchall()
        return [Finding(**row) for row in rows]
