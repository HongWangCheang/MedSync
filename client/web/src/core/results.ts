/** Reading what the server sent back into a step's result (ports of PharmacistAnswer.kt, SafetyReview.kt, App.kt). */
import type { ActionRow } from "./planner";

type Obj = Record<string, unknown>;
const str = (o: Obj | undefined, k: string) => (typeof o?.[k] === "string" ? (o[k] as string) : undefined);
const arr = (o: Obj | undefined, k: string) => (Array.isArray(o?.[k]) ? (o![k] as Obj[]) : []);
const parse = (json: string | null): Obj | undefined => {
  try { return json ? (JSON.parse(json) as Obj) : undefined; } catch { return undefined; }
};

// ----- pharmacist ---------------------------------------------------------------------------------------------

export interface Citation { id: string; label: string; section: string; excerpt: string; url?: string }
export interface Choice { labelId: string; version: string; name: string; manufacturer?: string }
export interface PharmacistAnswer {
  text: string;
  grounded: boolean;
  citations: Citation[];
  sessionId?: string;
  awaitingChoice: boolean;
  choices: Choice[];
}

export function choiceTitle(c: Choice): string {
  return [c.name, c.manufacturer?.trim() || undefined, `版本 ${c.version}`].filter(Boolean).join(" · ");
}

export function pharmacistAnswer(resultJson: string | null): PharmacistAnswer | undefined {
  const root = parse(resultJson);
  const text = str(root, "answer");
  if (!root || text === undefined) return undefined;
  return {
    text,
    grounded: root.grounded === true,
    citations: arr(root, "citations").map((c) => ({
      id: str(c, "id") ?? "?", label: str(c, "label") ?? "", section: str(c, "section") ?? "",
      excerpt: str(c, "excerpt") ?? "", url: str(c, "source_url"),
    })),
    sessionId: str(root, "session_id"),
    awaitingChoice: root.awaiting_choice === true,
    choices: arr(root, "choices").flatMap((c) => {
      const labelId = str(c, "label_id"), version = str(c, "version");
      return labelId && version ? [{ labelId, version, name: str(c, "name") ?? labelId, manufacturer: str(c, "manufacturer") }] : [];
    }),
  };
}

/** Splits an answer into text and "[S1]" markers so the markers can be highlighted. */
export function segments(text: string): { text: string; cite: boolean }[] {
  const out: { text: string; cite: boolean }[] = [];
  const re = /\[\s*S\d{1,4}(?:\s*[,;]\s*S\d{1,4})*\s*]/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index! > last) out.push({ text: text.slice(last, m.index), cite: false });
    out.push({ text: m[0], cite: true });
    last = m.index! + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), cite: false });
  return out;
}

const FOLLOW_UP_WINDOW_MS = 10 * 60_000;

/** The pharmacist conversation a new message should continue: the latest answered question, if recent. */
export function followUp(rows: ActionRow[], nowMs: number): PharmacistAnswer | undefined {
  const latest = rows.filter((r) => r.tool === "ask_pharmacist" && r.state === "DONE" && nowMs - r.createdAtMs <= FOLLOW_UP_WINDOW_MS)
    .sort((a, b) => b.createdAtMs - a.createdAtMs)[0];
  const answer = latest && pharmacistAnswer(latest.resultJson);
  return answer?.sessionId ? answer : undefined;
}

// ----- safety review -----------------------------------------------------------------------------------------

export interface SafetyFinding { summary: string; label: string; section: string; excerpt: string; url?: string }
export interface SafetyAlert { with: string; high: boolean; findings: SafetyFinding[] }
export interface SafetyReview {
  status: string;
  medication: string;
  alerts: SafetyAlert[];
  checked: string[];
  noLabel: string[];
  unresolved: string[];
  notRecent: string[];
  note?: string;
  skippedReason?: string;
}

export function safetyReview(resultJson: string | null): SafetyReview | undefined {
  const safety = parse(resultJson)?.safety as Obj | undefined;
  const status = str(safety, "status");
  if (!safety || !status) return undefined;
  const names = (k: string) => arr(safety, k).map((m) => (typeof m === "string" ? m : str(m, "name"))).filter(Boolean) as string[];
  return {
    status,
    medication: str(safety.medication as Obj, "name") ?? "",
    alerts: arr(safety, "alerts").map((a) => ({
      with: str(a, "with") ?? "",
      high: str(a, "severity") === "high",
      findings: arr(a, "findings").map((f) => {
        const c = (f.citation as Obj) ?? {};
        return { summary: str(f, "summary") ?? "", label: str(c, "label") ?? "", section: str(c, "section_zh") ?? str(c, "section") ?? "",
          excerpt: str(c, "excerpt") ?? "", url: str(c, "source_url") };
      }),
    })),
    checked: names("checked"),
    noLabel: names("no_label"),
    unresolved: names("unresolved"),
    notRecent: names("not_recent"),
    note: str(safety, "note"),
    skippedReason: str(safety, "reason"),
  };
}

export function headline(r: SafetyReview): string {
  if (r.status === "skipped") return `安全审核未执行（${r.skippedReason ?? "未知原因"}）`;
  if (r.status === "unresolved_medication") return `安全审核：没认出「${r.medication}」，没有检查`;
  if (r.alerts.some((a) => a.high)) return "安全审核：有需要马上留意的提醒";
  if (r.alerts.length) return "安全审核：有用药提醒";
  if (!r.checked.length && !r.noLabel.length && !r.unresolved.length) return "安全审核：最近一周没有其他服药记录，无需对照";
  if (!r.checked.length && r.noLabel.length) return "安全审核：没有可查的说明书，只核对了是否含相同成分";
  return "安全审核：说明书里没有找到相关提醒";
}

export function coverage(r: SafetyReview): string[] {
  return [
    r.checked.length ? `已对照：${r.checked.join("、")}` : "",
    r.noLabel.length ? `没有说明书可查（只核对了是否含相同成分）：${r.noLabel.join("、")}` : "",
    r.unresolved.length ? `没认出、未检查：${r.unresolved.join("、")}` : "",
    r.notRecent.length ? `一周前的记录未对照：${r.notRecent.join("、")}` : "",
  ].filter(Boolean);
}

export const askAbout = (r: SafetyReview, a: SafetyAlert) => `我在用${a.with}，现在加上${r.medication}，这两个能一起用吗？`;

// ----- waiting for the user ----------------------------------------------------------------------------------

export interface Conflict { summary: string; severity: string; why?: string }
export interface Decision { decision: string; date?: string; [key: string]: unknown }

export const conflicts = (row: ActionRow): Conflict[] => arr(parse(row.resultJson), "conflicts").map((c) => ({
  summary: str(c, "summary") ?? "", severity: str(c, "severity") ?? "", why: str(c, "why"),
}));
export const options = (row: ActionRow): Decision[] => arr(parse(row.resultJson), "options") as Decision[];

export function optionLabel(o: Decision, tool: string): string {
  switch (o.decision) {
    case "choose": return `改约 ${o.date}`;
    case "confirm": return tool === "notify_family" ? "照原样发送" : "仍然执行";
    case "send_with_note": return "附上提醒再发";
    case "cancel": return "取消";
    default: return JSON.stringify(o);
  }
}

// ----- how a step reads --------------------------------------------------------------------------------------

const OUTCOME_FIELDS: Record<string, string[]> = { book_appointment: ["department", "date"], notify_family: ["to", "message"] };

/** A finished booking or message shows what actually happened (rescheduled date, warning appended). */
export function shownPayload(row: ActionRow): Obj {
  const payload = parse(row.payloadJson) ?? {};
  const fields = OUTCOME_FIELDS[row.tool];
  const result = row.state === "DONE" ? parse(row.resultJson) : undefined;
  if (!fields || !result) return payload;
  return { ...payload, ...Object.fromEntries(fields.filter((k) => typeof result[k] === "string").map((k) => [k, result[k]])) };
}

const SEVERITY: Record<string, string> = { mild: "轻微", moderate: "中等", severe: "严重" };

export function summary(row: ActionRow): string {
  const p = shownPayload(row);
  switch (row.tool) {
    case "record_medication": return String(p.name ?? "");
    case "record_symptom": return `${p.category}${p.severity ? ` · ${SEVERITY[p.severity as string] ?? p.severity}` : ""}`;
    case "book_appointment": return `${p.department} · ${p.date}`;
    case "notify_family": return `发给${p.to}：${p.message}`;
    case "ask_pharmacist": return String(p.question ?? "");
    default: return row.payloadJson;
  }
}

export const STATE_LABEL: Record<string, string> = {
  PENDING: "待发送", BLOCKED: "等待前一步", SENDING: "发送中", RETRY_WAIT: "等待重试", ACKED: "服务器处理中",
  DONE: "已完成", NEEDS_USER: "需要你确认", FAILED: "失败", CANCELLED: "已取消",
};

export function reasonLabel(reason: string): string {
  const known: Record<string, string> = {
    slot_full: "原定日期号源已满",
    refused_without_evidence: "没有找到依据，已拒答",
    pharmacist_not_configured: "药学服务未配置",
    "pharmacist_not_configured: missing_key": "药学服务未配置（服务器缺少 Gemini 密钥）",
    expired: "排队时间过长，请确认是否仍要执行",
    tool_changed: "功能已更新，请重新确认",
    parent_not_done: "前一步没有完成",
    replayed: "已去重（replayed）",
    reconciled: "已去重（reconciled）",
    safety_alert_high: "安全审核：高风险提醒",
    safety_alert_moderate: "安全审核：有提醒",
    conflict_with_later_finding: "联网后发现用药提醒，已暂停等你确认",
    cancelled_by_user: "你取消了这一步",
    "offline: answer will be sent when online": "离线：你的选择会在联网后发送",
  };
  return known[reason] ?? reason;
}
