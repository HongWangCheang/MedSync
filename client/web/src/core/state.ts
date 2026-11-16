/**
 * Lifecycle of one outbox row (mirrors outbox/ActionState.kt).
 *
 *     PENDING ─send─▶ SENDING ─┬─ DONE
 *        ▲                     ├─ ACKED (gateway has it, outcome not final) ─poll─▶ DONE / NEEDS_USER / FAILED
 *        │                     ├─ NEEDS_USER (stale / conflict) ─user─▶ PENDING / CANCELLED
 *        └── RETRY_WAIT ◀──────┴─ transient error (network, timeout, 429, 5xx)
 *     BLOCKED (parent not DONE) ─parent done─▶ PENDING ; parent FAILED/CANCELLED ─▶ NEEDS_USER
 */
export type ActionState =
  | "PENDING" | "BLOCKED" | "SENDING" | "RETRY_WAIT" | "ACKED" | "DONE" | "NEEDS_USER" | "FAILED" | "CANCELLED";

export type ActionEvent =
  | "Send" | "ParentDone" | "ParentFailed" | "Accepted" | "Done" | "NeedsUser" | "Failed" | "Cancelled"
  | "TransientError" | "RetryDue" | "UserConfirmed";

export const terminal = (s: ActionState) => s === "DONE" || s === "FAILED" || s === "CANCELLED";

export class IllegalTransition extends Error {
  constructor(state: ActionState, event: ActionEvent) {
    super(`${event} is not allowed in ${state}`);
  }
}

export function next(state: ActionState, event: ActionEvent): ActionState {
  const fail = () => { throw new IllegalTransition(state, event); };
  switch (state) {
    case "PENDING":
      return event === "Send" ? "SENDING" : event === "ParentFailed" ? "NEEDS_USER" : fail();
    case "BLOCKED":
      return event === "ParentDone" ? "PENDING" : event === "ParentFailed" ? "NEEDS_USER" : fail();
    case "SENDING":
    case "ACKED":
      switch (event) {
        case "Accepted": return "ACKED";
        case "Done": return "DONE";
        case "NeedsUser": return "NEEDS_USER";
        case "Failed": return "FAILED";
        case "Cancelled": return "CANCELLED";
        case "TransientError": return state === "ACKED" ? "ACKED" : "RETRY_WAIT";
        case "Send": return state === "ACKED" ? "SENDING" : fail();
        default: return fail();
      }
    case "RETRY_WAIT":
      return event === "RetryDue" ? "PENDING" : event === "ParentFailed" ? "NEEDS_USER" : fail();
    case "NEEDS_USER":
      switch (event) {
        case "UserConfirmed": return "PENDING";
        case "Done": return "DONE";
        case "Accepted": return "ACKED";
        case "Cancelled": return "CANCELLED";
        case "Failed": return "FAILED";
        case "NeedsUser":
        case "ParentFailed": return "NEEDS_USER";
        default: return fail();
      }
    default:
      return fail();
  }
}
