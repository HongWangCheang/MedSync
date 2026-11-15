"""The executor reaches the external systems only through the MCP tool server; exactly-once still holds, including
when the MCP link itself loses a response after the server did the work."""

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from medsync_agent.executor import ExecResult
from medsync_agent.external import Unreachable
from medsync_agent.graph import StepRunner, build_graph
from medsync_agent.mcp_server import build_server
from medsync_agent.tool_ledger import InMemoryToolLedger
from medsync_agent.tools import McpTools

from .fakes import FakeExternal
from .test_graph import booking


class LosesResponses:
    """The MCP link drops the next N answers after the server has handled the call (the agent sees a timeout)."""

    name = "mcp-lossy"

    def __init__(self, inner: McpTools, drops: int = 1) -> None:
        self.inner, self.drops, self.executed = inner, drops, 0

    def execute(self, step_key: str, tool: str, payload: dict[str, Any]) -> ExecResult:
        result = self.inner.execute(step_key, tool, payload)
        self.executed += 1
        if self.drops:
            self.drops -= 1
            raise Unreachable("mcp read timeout")
        return result

    def slot(self, date: str) -> dict[str, Any]:
        return self.inner.slot(date)


def make(tools_wrapper=None) -> tuple[StepRunner, FakeExternal, InMemoryToolLedger]:
    ext, ledger = FakeExternal(), InMemoryToolLedger()
    tools = McpTools(build_server(ledger, ext))  # in-process MCP server, same protocol as over HTTP
    if tools_wrapper:
        tools = tools_wrapper(tools)
    # The agent itself gets no ledger and no external system: only the MCP tools.
    return StepRunner(build_graph(None, None, InMemorySaver(), tools=tools)), ext, ledger


def test_booking_goes_through_mcp_once_and_replays() -> None:
    runner, ext, _ = make()
    first = runner.run(booking())
    assert first.status == "DONE" and first.result["date"] == "2026-11-18"
    assert ext.slot_reads >= 1  # revalidate read the slot through MCP too
    assert runner.run(booking()) == first
    assert ext.count("k1") == 1


def test_external_response_lost_is_reconciled_by_the_tool_server() -> None:
    runner, ext, _ = make()
    ext.fault = "after_commit"
    assert runner.run(booking()).status == "PENDING"
    resumed = runner.run(booking())
    assert (resumed.status, resumed.reason) == ("DONE", "reconciled")
    assert ext.count("k1") == 1


def test_mcp_response_lost_after_the_server_booked_is_not_a_second_booking() -> None:
    lossy: list[LosesResponses] = []
    runner, ext, _ = make(lambda tools: lossy.append(LosesResponses(tools)) or lossy[0])
    assert runner.run(booking()).status == "PENDING"  # the agent cannot tell whether it happened
    assert ext.count("k1") == 1                        # ...but it did
    resumed = runner.run(booking())                     # same step_key → the server's ledger answers
    assert (resumed.status, resumed.reason) == ("DONE", "replayed")
    assert lossy[0].executed == 2 and ext.count("k1") == 1


def test_slot_taken_asks_the_user_with_alternatives_read_through_mcp() -> None:
    runner, ext, _ = make()
    ext.slots["2026-11-18"] = {"available": 0, "version": 4}
    waiting = runner.run(booking())
    assert (waiting.status, waiting.reason) == ("NEEDS_USER", "slot_full")
    assert {"decision": "choose", "date": "2026-11-19"} in waiting.result["options"]
    done = runner.resume("acct", "k1", {"decision": "choose", "date": "2026-11-19"})
    assert done.status == "DONE" and ext.count("k1") == 1


def test_tool_server_down_parks_the_step_without_side_effects() -> None:
    runner = StepRunner(build_graph(None, None, InMemorySaver(),
                                    tools=McpTools("http://127.0.0.1:9/mcp", timeout_s=2)))
    outcome = runner.run(booking())
    assert outcome.status == "PENDING" and "mcp" in (outcome.reason or "")


def test_mcp_tools_are_discoverable_with_step_key_required() -> None:
    import anyio
    from mcp.client.client import Client

    async def listing():
        async with Client(build_server(InMemoryToolLedger(), FakeExternal())) as client:
            return (await client.list_tools()).tools

    tools = {t.name: t for t in anyio.run(listing)}
    assert set(tools) == {"book_appointment", "notify_family", "check_slot"}
    assert "step_key" in tools["notify_family"].input_schema["required"]
