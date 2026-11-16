import type { Json } from "./stepKey";
import { fmt, isoDay, plusDays, type LocalDate } from "./date";

/** One step as proposed by a router (mirrors outbox/Planner.kt StepDraft). */
export interface StepDraft {
  tool: string;
  payload: { [key: string]: Json };
  /** Indices of earlier steps in the same plan that must be DONE first. */
  dependsOn?: number[];
  preconditions?: { [key: string]: Json };
}

export interface Routed {
  steps: StepDraft[];
  question: boolean;
}

/**
 * The deterministic Chinese rule router, a line-by-line port of agents/RuleRouter.kt. On the phones and the
 * desktop an on-device model plans first and these rules are the fallback; the browser has no model, so it uses the
 * rules alone (the same baseline the routing eval reports).
 */
const STOPS = ["，", ",", "。", "；", ";", "！", "!", "？", "?", " ", "然后", "有点", "帮我", "顺便", "还", "和", "后"];
const TAKE_VERBS = ["吃了", "服用了", "服了", "吃过"];
const SYMPTOMS = ["头晕", "头疼", "头痛", "胃疼", "胃痛", "肚子疼", "恶心", "发烧", "咳嗽", "胸闷", "乏力", "失眠", "腹泻",
  "皮疹", "心慌"];
const RELATIVES = ["女儿", "儿子", "老伴", "妈妈", "爸爸", "家人", "老婆", "老公"];
const WEEKDAYS: Record<string, number> = { 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 日: 7, 天: 7 };
const ASKS = ["能不能", "可不可以", "能一起", "一起吃", "副作用", "怎么吃", "吃多少", "吗", "？", "?"];

const has = (text: string, words: string[]) => words.some((w) => text.includes(w));

export function route(text: string, today: LocalDate, nowMs: number): Routed {
  const steps: StepDraft[] = [];
  let symptomIndex: number | undefined;
  let medicationIndex: number | undefined;

  const name = medication(text);
  if (name !== undefined) {
    medicationIndex = steps.length;
    steps.push({ tool: "record_medication", payload: { name, takenAt: nowMs, note: text } });
  }
  const category = SYMPTOMS.find((s) => text.includes(s));
  if (category) {
    const severity = has(text, ["很", "特别", "严重", "剧烈"]) ? "severe"
      : text.includes("有点") || text.includes("有些") ? "mild" : "moderate";
    symptomIndex = steps.length;
    steps.push({ tool: "record_symptom", payload: { category, severity, recordedAt: nowMs, note: text } });
  }
  const after = symptomIndex === undefined ? [] : [symptomIndex];
  if (has(text, ["约", "挂号", "复诊", "预约"])) {
    steps.push({
      tool: "book_appointment",
      payload: { patient_id: "self", department: department(text), date: date(text, today), note: text },
      dependsOn: after,
    });
  }
  const relative = RELATIVES.find((r) => text.includes(r));
  if (relative && has(text, ["告诉", "通知", "跟", "说一声"])) {
    // The message also waits for the medication record, so the server's safety review of that record is on the
    // findings board before the message is checked against it.
    const dependsOn = [...(medicationIndex === undefined ? [] : [medicationIndex]), ...after].sort((a, b) => a - b);
    steps.push({ tool: "notify_family", payload: { to: relative, message: text }, dependsOn });
  }
  if (steps.length === 0 && has(text, ASKS)) {
    steps.push({ tool: "ask_pharmacist", payload: { question: text }, preconditions: { needsEvidence: true } });
  }
  return { steps, question: steps.length === 1 && steps[0].tool === "ask_pharmacist" };
}

export function medication(text: string): string | undefined {
  const verb = TAKE_VERBS.find((v) => text.includes(v));
  if (!verb) return undefined;
  const rest = text.slice(text.indexOf(verb) + verb.length);
  const cuts = STOPS.map((s) => rest.indexOf(s)).filter((i) => i >= 0);
  const end = cuts.length ? Math.min(...cuts) : rest.length;
  let name = rest.slice(0, end);
  if (name.endsWith("药")) name = name.slice(0, -1);
  return name.trim() || "未注明药物";
}

export function department(text: string): string {
  if (has(text, ["胃", "肚子", "腹泻"])) return "消化内科";
  if (has(text, ["胸", "心"])) return "心血管内科";
  if (has(text, ["头", "失眠"])) return "神经内科";
  if (has(text, ["咳", "发烧"])) return "呼吸内科";
  return "全科";
}

/** 今天/明天/后天/大后天、(下)周X/星期X/礼拜X、M月D日; defaults to tomorrow. */
export function date(text: string, today: LocalDate): LocalDate {
  const md = /(\d{1,2})月(\d{1,2})[日号]/.exec(text);
  if (md) {
    const year = Number(today.slice(0, 4));
    const candidate = fmt(year, Number(md[1]), Number(md[2]));
    return candidate < today ? fmt(year + 1, Number(md[1]), Number(md[2])) : candidate;
  }
  if (text.includes("大后天")) return plusDays(today, 3);
  if (text.includes("后天")) return plusDays(today, 2);
  if (text.includes("明天")) return plusDays(today, 1);
  if (text.includes("今天")) return today;
  // (?<!一): "约一下周二" is this coming Tuesday, not next week's.
  const wk = /(?<!一)(下)?(?:周|星期|礼拜)([一二三四五六日天])/.exec(text);
  if (wk) {
    const target = WEEKDAYS[wk[2]];
    const dow = isoDay(today);
    let days = (target - dow + 7) % 7;
    if (days === 0) days = 7;
    if (wk[1] && days <= 7 - dow) days += 7;
    return plusDays(today, days);
  }
  return plusDays(today, 1);
}
