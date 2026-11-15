"""Exactly-once execution of one external side effect, keyed by step_key.

The key is the LOGICAL step, not the LLM's output: when a model re-plans after a timeout it may phrase the call
differently (another note, another date format), so deduplicating on the tool arguments would miss it.

    claim → COMMITTED  : return the stored result, never call the external system again
    claim → BUSY       : another worker is mid-call → PENDING (gateway will ask again)
    claim → RECLAIMED  : an earlier attempt's outcome is unknown → look it up by step_key first
    claim → NEW        : call; Unreachable → PENDING (stay INTENT), Rejected → release, success → COMMITTED
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

from .external import External, Rejected, Unreachable
from .tool_ledger import Claim, ToolLedger

# How long an INTENT row blocks other attempts of the same step. After it lapses, the next attempt looks the side
# effect up by step_key instead of waiting. Must exceed the external call's timeout (MEDSYNC_EXTERNAL_TIMEOUT_S), or a
# slow but healthy call could be looked up (and found missing) while it is still in flight.
LEASE_S = float(os.environ.get("MEDSYNC_TOOL_LEASE_S", "30"))


@dataclass
class ExecResult:
    status: Literal["DONE", "PENDING", "REJECTED"]
    result: dict[str, Any] | None = None
    reason: str | None = None


def execute(step_key: str, tool: str, payload: dict[str, Any], ledger: ToolLedger, external: External,
            lease_s: float = LEASE_S) -> ExecResult:
    claim = ledger.claim(step_key, tool, payload, lease_s)
    if claim.claim is Claim.COMMITTED:
        return ExecResult("DONE", claim.result, "replayed")
    if claim.claim is Claim.BUSY:
        return ExecResult("PENDING", reason="another attempt of this step is in flight")
    if claim.claim is Claim.RECLAIMED:
        try:
            found = external.lookup(tool, step_key)
        except Unreachable as error:
            ledger.expire(step_key)
            return ExecResult("PENDING", reason=f"cannot confirm earlier attempt: {error}")
        if found is not None:
            ledger.commit(step_key, found)
            return ExecResult("DONE", found, "reconciled")
    try:
        result = external.call(tool, payload, step_key)
    except Unreachable as error:
        # Outcome unknown (maybe committed, response lost). Keep INTENT; the next attempt looks it up by step_key.
        ledger.expire(step_key)
        return ExecResult("PENDING", reason=f"external outcome unknown: {error}")
    except Rejected as rejected:
        ledger.release(step_key)
        return ExecResult("REJECTED", reason=rejected.reason)
    ledger.commit(step_key, result)
    return ExecResult("DONE", result)
