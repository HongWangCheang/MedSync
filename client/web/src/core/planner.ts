import { canonical, stepKey, type Json } from "./stepKey";
import type { StepDraft } from "./router";
import { tool } from "./tools";
import type { ActionState } from "./state";

/** One outbox row (mirrors data/Database.kt ActionEntity). JSON columns are kept as canonical text, as on the phones. */
export interface ActionRow {
  actionId: string;
  planId: string;
  stepIndex: number;
  stepKey: string;
  tool: string;
  toolClass: string;
  identityArgsJson: string;
  payloadJson: string;
  preconditionsJson: string;
  /** actionIds this step waits for (a DAG within its plan). */
  dependsOn: string[];
  createdAtMs: number;
  expiresAtMs: number | null;
  state: ActionState;
  attempt: number;
  nextRetryAtMs: number;
  reason: string | null;
  resultJson: string | null;
  /** The sentence the plan came from, for the timeline (web only; not sent). */
  utterance: string;
}

/**
 * Turns drafts into outbox rows with step keys. Pure: the caller stores the whole list in one transaction.
 * Dependencies may only point backwards, which makes plan order a valid topological order.
 */
export async function plan(drafts: StepDraft[], deviceId: string, nowMs: number, utterance: string,
                           planId: string = crypto.randomUUID()): Promise<ActionRow[]> {
  const ids = drafts.map(() => crypto.randomUUID());
  return Promise.all(drafts.map(async (draft, index) => {
    const deps = draft.dependsOn ?? [];
    if (!deps.every((d) => d >= 0 && d < index)) throw new Error(`step ${index} depends on a later or unknown step`);
    const spec = tool(draft.tool);
    const identity: { [key: string]: Json } = {};
    for (const [k, v] of Object.entries(draft.payload)) if (spec.identityFields.includes(k)) identity[k] = v;
    const preconditions = { ...(draft.preconditions ?? {}), toolVersion: spec.version };
    return {
      actionId: ids[index],
      planId,
      stepIndex: index,
      stepKey: await stepKey(deviceId, planId, index, spec.name, identity),
      tool: spec.name,
      toolClass: spec.toolClass,
      identityArgsJson: canonical(identity),
      payloadJson: canonical(draft.payload),
      preconditionsJson: canonical(preconditions),
      dependsOn: deps.map((d) => ids[d]),
      createdAtMs: nowMs,
      expiresAtMs: spec.ttlMs ? nowMs + spec.ttlMs : null,
      state: deps.length === 0 ? "PENDING" : "BLOCKED",
      attempt: 0,
      nextRetryAtMs: 0,
      reason: null,
      resultJson: null,
      utterance,
    } satisfies ActionRow;
  }));
}
