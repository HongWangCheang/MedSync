"""Wire models shared by the API, the graph and the MCP server."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

ToolClass = Literal["READ", "WRITE_IDEMPOTENT", "IRREVERSIBLE"]
OutcomeStatus = Literal["DONE", "NEEDS_USER", "FAILED", "CANCELLED", "PENDING"]

# Bump a tool's version whenever its contract changes. A step planned against an older version is sent back to the
# user instead of being executed against a contract it was never planned for.
TOOL_VERSIONS: dict[str, str] = {
    "record_medication": "v1",
    "record_symptom": "v1",
    "book_appointment": "v1",
    "notify_family": "v1",
    "ask_pharmacist": "v1",
}
EXTERNAL_TOOLS = {"book_appointment", "notify_family"}


class ActionRequest(BaseModel):
    """One planned step, as stored in the gateway's action_ledger (camelCase on the wire, like the device sends it)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    account_id: str = Field(alias="account_id")
    step_key: str
    plan_id: str
    step_index: int
    tool: str
    tool_class: ToolClass = "IRREVERSIBLE"
    identity_args: dict[str, Any] = {}
    payload: dict[str, Any]
    preconditions: dict[str, Any] = {}
    created_at_ms: int = 0
    expires_at_ms: int | None = None


class Outcome(BaseModel):
    status: OutcomeStatus
    result: dict[str, Any] | None = None
    reason: str | None = None
