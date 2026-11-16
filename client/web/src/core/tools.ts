/** How dangerous it is to run a tool twice, and what it does offline (mirrors outbox/Tools.kt). */
export type ToolClass = "READ" | "WRITE_IDEMPOTENT" | "IRREVERSIBLE";
export type Offline = "LOCAL" | "QUEUED" | "REFUSED";

export interface ToolSpec {
  name: string;
  label: string;
  toolClass: ToolClass;
  offline: Offline;
  /** Payload fields that decide "is this the same step?"; free text is left out on purpose. */
  identityFields: string[];
  version: string;
  ttlMs?: number;
}

const HOUR = 3_600_000;

export const TOOLS: Record<string, ToolSpec> = Object.fromEntries(
  ([
    { name: "record_medication", label: "记录服药", toolClass: "WRITE_IDEMPOTENT", offline: "LOCAL",
      identityFields: ["name", "takenAt"], version: "v1" },
    { name: "record_symptom", label: "记录症状", toolClass: "WRITE_IDEMPOTENT", offline: "LOCAL",
      identityFields: ["category", "recordedAt"], version: "v1" },
    { name: "book_appointment", label: "预约复诊", toolClass: "IRREVERSIBLE", offline: "QUEUED",
      identityFields: ["patient_id", "department", "date"], version: "v1" },
    { name: "notify_family", label: "通知家属", toolClass: "IRREVERSIBLE", offline: "QUEUED",
      identityFields: ["to"], version: "v1", ttlMs: 6 * HOUR },
    { name: "ask_pharmacist", label: "用药问答", toolClass: "READ", offline: "REFUSED",
      identityFields: ["question"], version: "v1" },
  ] as ToolSpec[]).map((spec) => [spec.name, spec]),
);

export function tool(name: string): ToolSpec {
  const spec = TOOLS[name];
  if (!spec) throw new Error(`unknown tool: ${name}`);
  return spec;
}
