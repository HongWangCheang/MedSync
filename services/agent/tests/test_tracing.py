"""Langfuse tracing: one trace per plan, nodes and MCP calls as children, no free text leaves the process.

Uses the real Langfuse client with an in-memory OpenTelemetry exporter, so nothing is sent anywhere.
"""

import json
import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from medsync_agent import tracing
from medsync_agent.graph import StepRunner, build_graph
from medsync_agent.mcp_server import build_server
from medsync_agent.models import ActionRequest
from medsync_agent.tool_ledger import InMemoryToolLedger
from medsync_agent.tools import McpTools

from .fakes import FakeExternal
from .test_graph import booking

SECRET = "我今天头晕得厉害"


@pytest.fixture
def spans():
    from langfuse import Langfuse

    exporter = InMemorySpanExporter()
    key = f"pk-lf-test-{uuid.uuid4().hex}"  # Langfuse keeps one client per public key: a fresh one per test
    client = Langfuse(public_key=key, secret_key="sk-lf-test", base_url="http://127.0.0.1:9",
                      span_exporter=exporter, mask=tracing._mask, mask_otel_spans=tracing._mask_spans)
    tracing.configure(client, key)
    yield lambda: (client.flush(), exporter.get_finished_spans())[1]
    tracing.configure(None)
    client.shutdown()


def notify(plan: str = "p1", key: str = "k2") -> ActionRequest:
    return ActionRequest.model_validate({
        "account_id": "acct", "stepKey": key, "planId": plan, "stepIndex": 1, "tool": "notify_family",
        "payload": {"to": "女儿", "message": SECRET}, "preconditions": {"toolVersion": "v1"}})


def runner() -> StepRunner:
    tools = McpTools(build_server(InMemoryToolLedger(), FakeExternal()))
    return StepRunner(build_graph(None, None, InMemorySaver(), tools=tools))


def test_steps_of_one_plan_share_one_trace_with_nodes_and_mcp_calls(spans) -> None:
    steps = runner()
    assert steps.run(booking()).status == "DONE"           # plan p1, step 0
    assert steps.run(notify()).status == "DONE"            # plan p1, step 1, arrives later
    assert steps.run(notify(plan="p2", key="k3")).status == "DONE"
    finished = spans()
    by_trace: dict[int, set[str]] = {}
    for span in finished:
        by_trace.setdefault(span.context.trace_id, set()).add(span.name)
    assert len(by_trace) == 2                                # p1 and p2
    p1 = next(names for names in by_trace.values() if "0:book_appointment" in names)
    assert {"1:notify_family", "revalidate", "executor", "mcp:book_appointment", "mcp:notify_family"} <= p1
    assert hex(next(s for s in finished if s.name == "0:book_appointment").context.trace_id)[2:].zfill(32) == \
        tracing.trace_id("acct", "p1")                       # any process finds the plan's trace from its ids


def test_free_text_and_account_ids_never_leave_the_process(spans) -> None:
    runner().run(notify())
    # Attribute values are JSON strings: decode them so escaped text cannot hide from the check.
    exported = json.dumps([{k: _decoded(v) for k, v in (s.attributes or {}).items()} for s in spans()],
                          ensure_ascii=False)
    assert SECRET not in exported
    assert f"<{len(SECRET)} chars>" in exported               # what happened stays visible
    assert "女儿" in exported                                  # who it was for is not free text
    assert "acct" not in exported                              # account ids are hashed everywhere


def _decoded(value):
    try:
        return json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return value


def test_without_keys_tracing_is_off_and_steps_run_the_same() -> None:
    tracing.configure(None)
    assert tracing.callbacks() == []
    assert runner().run(booking()).status == "DONE"
