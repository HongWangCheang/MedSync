"""Comparison-experiment baselines. Only reachable when MEDSYNC_EXPERIMENTS=1.

Every mode sees the same faults and the same "LLM re-planning": each time a step is dispatched again, the free-text
arguments are reworded (`rephrase`), the way a model that re-emits a tool call after a timeout rarely produces the
identical string. What differs is only where (if anywhere) duplicates are caught:

    naive       device retries with a NEW key; agent calls the tool on every dispatch           (B0)
    request_id  device keeps its key, so hop ① replays; agent still calls on every dispatch     (B1, MedTrack today)
    args_hash   B1 + agent skips a call whose (tool, arguments) hash it has already executed     (B2, common guard)
    full        step_key through all three hops: LangGraph thread + tool ledger + revalidate     (this project)
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import Counter
from typing import Any

from .external import External, Rejected, Unreachable
from .models import ActionRequest, Outcome

MODES = {"naive", "request_id", "args_hash", "full"}
_PHRASES = ["", "（重试）", "（再次提交）", "（系统重新规划）", "（补发）"]


def enabled() -> bool:
    return os.environ.get("MEDSYNC_EXPERIMENTS") == "1"


class Attempts:
    """Counts dispatches per step so every mode rewords its arguments on the same schedule."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._lock = threading.Lock()

    def next(self, step_key: str) -> int:
        with self._lock:
            n = self._counts[step_key]
            self._counts[step_key] += 1
            return n


def rephrase(tool: str, payload: dict[str, Any], attempt: int) -> dict[str, Any]:
    """Deterministic stand-in for an LLM re-emitting the same call with different free text.

    MEDSYNC_EXPERIMENT_REPHRASE=0 turns it off (ablation: retries resend byte-identical arguments).
    """
    if attempt == 0 or os.environ.get("MEDSYNC_EXPERIMENT_REPHRASE") == "0":
        return payload
    field = {"book_appointment": "note", "notify_family": "message"}.get(tool)
    if field is None:
        return payload
    suffix = _PHRASES[attempt % len(_PHRASES)] or f"（第{attempt + 1}次）"
    return {**payload, field: f"{payload.get(field, '')}{suffix}"}


class BaselineRunner:
    """B0 / B1 / B2: no step thread, no tool ledger, no revalidation; one tool call per dispatch."""

    def __init__(self, external: External, attempts: Attempts) -> None:
        self._external = external
        self._attempts = attempts
        self._args_cache: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def run(self, request: ActionRequest) -> Outcome:
        if request.tool not in {"book_appointment", "notify_family"}:
            return Outcome(status="DONE", result={"tool": request.tool, "accepted": True})
        payload = rephrase(request.tool, request.payload, self._attempts.next(request.step_key))
        digest = hashlib.sha256(
            (request.tool + json.dumps(payload, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()
        if request.experiment_mode == "args_hash":
            with self._lock:
                if digest in self._args_cache:
                    return Outcome(status="DONE", result=self._args_cache[digest], reason="args_cache_hit")
        try:
            result = self._external.call(request.tool, payload, request.step_key)
        except Unreachable as error:
            return Outcome(status="PENDING", reason=f"external outcome unknown: {error}")
        except Rejected as rejected:
            return Outcome(status="FAILED", reason=rejected.reason)
        if request.experiment_mode == "args_hash":
            with self._lock:
                self._args_cache[digest] = result
        return Outcome(status="DONE", result=result)
