"""Langfuse tracing: one trace per plan, so every step of "吃了布洛芬，告诉女儿我没事，帮我约明天的号" lands in the same
trace even though the steps reach the agent minutes or hours apart (offline queue, retries, waiting for the user).

    trace  = plan (id derived from account + plan_id, so every process and every retry finds the same one)
      └ step "1:notify_family" (one per dispatch or resume) → LangGraph nodes (revalidate, safety_review, executor)
                                                            → MCP tool calls (mcp:notify_family)

Off unless LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set (LANGFUSE_HOST points at a self-hosted instance).
Tracing never changes behaviour: every helper is a no-op without a client, and a tracing error is not a step error.

Health data: the free text users type (messages to family, notes, questions, answers) is replaced by its length
before anything leaves the process, unless MEDSYNC_TRACE_CONTENT=1. Account ids are hashed. Delegation tokens are
never part of the traced state.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

log = logging.getLogger(__name__)

FREE_TEXT = {"message", "note", "question", "answer", "text", "excerpt", "summary", "detail", "quote"}

_client: Any = None
_public_key: str | None = None  # the LangChain callback handler finds the client by its public key
_configured = False


class _Noop:
    def update(self, **_: Any) -> None:
        pass


NOOP = _Noop()


def _user(account_id: str) -> str:
    return hashlib.sha256(account_id.encode()).hexdigest()[:12]


def _thread(thread_id: str) -> str:
    """LangGraph thread ids are "account:step_key"; keep the step, hash the account."""
    account, _, step_key = thread_id.partition(":")
    return f"{_user(account)}:{step_key}" if step_key else _user(account)


def redact(value: Any) -> Any:
    """Free text out, structure in: what happened stays visible, what the user wrote does not. Accounts are hashed."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "account_id" and isinstance(v, str):
                out[k] = _user(v)
            elif k == "thread_id" and isinstance(v, str):
                out[k] = _thread(v)
            elif k in FREE_TEXT and isinstance(v, str) and os.environ.get("MEDSYNC_TRACE_CONTENT") != "1":
                out[k] = f"<{len(v)} chars>"
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def _mask(*, data: Any, **_: Any) -> Any:
    """Inputs and outputs of every observation (including the LangGraph nodes' state)."""
    return redact(data)


def _mask_spans(*, params: Any) -> Any:
    """Span attributes the input/output mask does not see: LangGraph puts the thread id into metadata."""
    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

    patches = {}
    for ident, span in params.spans.items():
        changes = {}
        for key, value in (span.attributes or {}).items():
            if key.endswith(".thread_id") and isinstance(value, str):
                raw = value.strip('"')
                changes[key] = json.dumps(_thread(raw)) if value.startswith('"') else _thread(raw)
        if changes:
            patches[ident] = OtelSpanPatch(set_attributes=changes)
    return MaskOtelSpansResult(span_patches=patches)


def configure(client: Any = None, public_key: str | None = None) -> None:
    """Use this client (tests pass one with an in-memory exporter); without one, read the environment."""
    global _client, _public_key, _configured
    _client, _public_key, _configured = client, public_key, True


def client() -> Any:
    global _client, _public_key, _configured
    if not _configured:
        _configured = True
        if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"):
            _public_key = os.environ["LANGFUSE_PUBLIC_KEY"]
            try:
                from langfuse import Langfuse

                _client = Langfuse(mask=_mask, mask_otel_spans=_mask_spans, environment=os.environ.get("MEDSYNC_ENV", "development"))
            except Exception:  # tracing must never take the agent down
                log.exception("Langfuse disabled: client could not start")
    return _client


def trace_id(account_id: str, plan_id: str) -> str:
    from langfuse import Langfuse

    return Langfuse.create_trace_id(seed=f"{account_id}:{plan_id}")


@contextmanager
def step(request: Any, action: str) -> Iterator[Any]:
    """One observation per dispatch or resume of a step, inside the plan's trace."""
    lf = client()
    if lf is None:
        yield NOOP
        return
    from langfuse import propagate_attributes

    attributes = dict(user_id=_user(request.account_id), session_id=request.plan_id, trace_name="plan",
                      tags=[request.tool], metadata={"plan_id": request.plan_id})
    with propagate_attributes(**attributes):
        with lf.start_as_current_observation(
                trace_context={"trace_id": trace_id(request.account_id, request.plan_id)},
                name=f"{request.step_index}:{request.tool}", as_type="agent",
                input={"action": action, "tool": request.tool, "payload": request.payload,
                       "preconditions": request.preconditions},
                metadata={"step_key": request.step_key, "tool_class": request.tool_class}) as observation:
            yield observation


@contextmanager
def span(name: str, input: Any = None) -> Iterator[Any]:
    lf = client()
    if lf is None:
        yield NOOP
        return
    with lf.start_as_current_observation(name=name, as_type="tool", input=input) as observation:
        yield observation


def callbacks() -> list[Any]:
    """LangGraph callbacks: each node (revalidate, safety_review, executor…) becomes a child observation."""
    if client() is None:
        return []
    from langfuse.langchain import CallbackHandler

    return [CallbackHandler(public_key=_public_key)]


def flush() -> None:
    if _client is not None:
        _client.flush()
