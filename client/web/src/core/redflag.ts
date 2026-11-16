/**
 * Danger signs, rules only (a port of agents/RedFlagDetector.kt). Runs before anything else, fully offline. It never
 * diagnoses; it tells the user to get help now. Self-harm always gets the crisis hotline as well as 120.
 */
export type RedFlagKind = "EMERGENCY" | "CRISIS";

export interface RedFlag {
  /** The user's own words that triggered it, shown so the alert explains itself. */
  matched: string;
  advice: string;
  kind: RedFlagKind;
}

export const EMERGENCY = "这可能是紧急情况。请立即拨打 120，或尽快前往最近的急诊。";
export const CRISIS = "你现在可能很难受。请立即拨打 12356 心理援助热线；如有生命危险，请拨打 120 或 110。";

const EMERGENCY_WORDS = ["胸痛", "胸口痛", "胸口疼", "胸口压", "呼吸困难", "喘不上气", "喘不过气", "意识不清", "昏迷", "晕倒",
  "抽搐", "吐血", "咯血", "便血", "黑便", "剧烈头痛", "口角歪斜", "说话不清", "半边身体", "一侧肢体", "过量", "吃多了",
  "一整瓶", "吃了一瓶"];
const CRISIS_WORDS = ["不想活", "自杀", "轻生", "结束生命", "想死", "寻死", "活不下去", "一了百了", "遗书", "割腕", "跳楼",
  "自残", "伤害自己", "了结自己", "结束自己"];
const CRISIS_HINTS = /解脱|累赘|拖累|撑不下去|不想醒|别再醒|醒不过来|后事|告别|活着没|没有意义|没意思|攒.{0,8}药|药.{0,6}(全|都)(吞|吃)|(全|都)吞/;
const NEGATIONS = ["没有", "没", "无", "不", "未"];

/** True if [keyword] occurs at least once without a negation right before it ("没有胸痛" is not a hit). */
export function hit(text: string, keyword: string): boolean {
  let from = 0;
  for (;;) {
    const at = text.indexOf(keyword, from);
    if (at < 0) return false;
    const before = text.slice(Math.max(0, at - 2), at);
    if (!NEGATIONS.some((n) => before.endsWith(n))) return true;
    from = at + keyword.length;
  }
}

export function detect(text: string): RedFlag | undefined {
  const crisis = CRISIS_WORDS.find((w) => hit(text, w));
  if (crisis) return { matched: crisis, advice: CRISIS, kind: "CRISIS" };
  const emergency = EMERGENCY_WORDS.find((w) => hit(text, w));
  if (!emergency) return undefined;
  const selfHarm = CRISIS_WORDS.some((w) => hit(text, w)) || CRISIS_HINTS.test(text);
  return selfHarm ? { matched: emergency, advice: CRISIS, kind: "CRISIS" }
    : { matched: emergency, advice: EMERGENCY, kind: "EMERGENCY" };
}
