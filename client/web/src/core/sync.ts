import type { GatewayApi, SubmitResult } from "./gateway";
import type { ActionRow } from "./planner";
import { next, terminal, type ActionEvent, type ActionState } from "./state";
import type { Store } from "./store";
import type { Json } from "./stepKey";

export interface DrainReport { sent: number; done: number; waiting: number; needsUser: number }

/**
 * Drains the outbox over hop ① (a port of sync/SyncEngine.kt). The page decides WHEN (a timer, the browser's
 * "online" event, the user tapping 同步); the logic is the same as on the phones.
 *
 * Rows are visited in plan order, a topological order, so a parent that finishes in this pass unblocks its children
 * in the same pass.
 */
export class SyncEngine {
  private running: Promise<unknown> = Promise.resolve();

  constructor(private store: Store, private api: GatewayApi, private random: () => number = Math.random) {}

  /** One drain at a time, like the Kotlin Mutex. */
  drainOnce(nowMs: number): Promise<DrainReport> {
    const run = this.running.then(() => this.drain(nowMs));
    this.running = run.catch(() => undefined);
    return run;
  }

  resolve(action: ActionRow, decision: { [key: string]: Json }, nowMs: number): Promise<ActionRow> {
    const run = this.running.then(async () => this.apply(action, await this.api.resume(action.stepKey, decision), nowMs));
    this.running = run.catch(() => undefined);
    return run;
  }

  private async drain(nowMs: number): Promise<DrainReport> {
    const rows = await this.store.all();
    const states = new Map<string, ActionState>(rows.map((r) => [r.actionId, r.state]));
    let sent = 0;
    for (const original of rows) {
      let action = original;
      let state = states.get(action.actionId)!;
      if (terminal(state)) continue;

      const parents = action.dependsOn.map((id) => states.get(id) ?? "DONE");
      if (parents.some((p) => p === "FAILED" || p === "CANCELLED")) {
        if (state !== "NEEDS_USER") {
          action = await this.save(action, "ParentFailed", { reason: "parent_not_done" });
          states.set(action.actionId, action.state);
        }
        continue;
      }
      if (state === "BLOCKED") {
        if (parents.some((p) => p !== "DONE")) continue;
        action = await this.save(action, "ParentDone");
        state = "PENDING";
      }
      if (state === "RETRY_WAIT") {
        if (action.nextRetryAtMs > nowMs) continue;
        action = await this.save(action, "RetryDue");
        state = "PENDING";
      }
      let result: SubmitResult;
      if (state === "PENDING") {
        action = await this.save(action, "Send");
        sent++;
        result = await this.api.submit(action);
      } else if (state === "ACKED") {
        result = await this.api.status(action.stepKey);
      } else {
        continue; // NEEDS_USER waits for resolve(); SENDING only exists inside this pass
      }
      action = await this.apply(action, result, nowMs);
      states.set(action.actionId, action.state);
    }
    const final = [...states.values()];
    return {
      sent,
      done: final.filter((s) => s === "DONE").length,
      waiting: final.filter((s) => !terminal(s) && s !== "NEEDS_USER").length,
      needsUser: final.filter((s) => s === "NEEDS_USER").length,
    };
  }

  private async apply(action: ActionRow, result: SubmitResult, nowMs: number): Promise<ActionRow> {
    const json = (value: Json | null) => (value === null ? null : JSON.stringify(value));
    switch (result.kind) {
      case "Done": return this.save(action, "Done", { resultJson: json(result.result), reason: null });
      case "Accepted": return this.save(action, "Accepted");
      case "NeedsUser": return this.save(action, "NeedsUser", { reason: result.reason, resultJson: json(result.result) });
      case "Failed": return this.save(action, "Failed", { reason: result.reason });
      case "Cancelled": return this.save(action, "Cancelled", { reason: result.reason });
      case "Conflict": return this.save(action, "Failed", { reason: "step_key reused for different content" });
      case "Transient": {
        if (action.state === "NEEDS_USER") {
          const row = { ...action, reason: "offline: answer will be sent when online" };
          await this.store.update(row);
          return row;
        }
        const row: ActionRow = {
          ...action,
          state: next(action.state, "TransientError"),
          attempt: action.attempt + 1,
          reason: result.message,
          nextRetryAtMs: nowMs + backoffMs(action.attempt, this.random),
        };
        await this.store.update(row);
        return row;
      }
    }
  }

  private async save(action: ActionRow, event: ActionEvent,
                     change: { reason?: string | null; resultJson?: string | null } = {}): Promise<ActionRow> {
    const row: ActionRow = {
      ...action,
      state: next(action.state, event),
      reason: change.reason === undefined ? action.reason : change.reason,
      resultJson: change.resultJson === undefined ? action.resultJson : change.resultJson,
    };
    await this.store.update(row);
    return row;
  }
}

/** 2 s, 4 s, 8 s … capped at 5 min, ±20 % jitter so many clients coming back online don't stampede. */
export function backoffMs(attempt: number, random: () => number): number {
  const base = Math.min(2_000 * 2 ** Math.min(attempt, 20), 300_000);
  return Math.floor(base * (0.8 + 0.4 * random()));
}
