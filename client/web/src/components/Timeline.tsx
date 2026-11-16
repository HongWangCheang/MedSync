import type { ActionRow } from "../core/planner";
import {
  conflicts, optionLabel, options, pharmacistAnswer, reasonLabel, safetyReview, STATE_LABEL, summary,
  type Choice, type Decision, type PharmacistAnswer,
} from "../core/results";
import { TOOLS } from "../core/tools";
import { AnswerView } from "./AnswerView";
import { Icon, TOOL_ICON } from "./Icon";
import { SafetyView } from "./SafetyView";

export interface Handlers {
  onDecision: (row: ActionRow, decision: Decision | null) => void;
  onChoose: (answer: PharmacistAnswer, choice: Choice) => void;
  onAsk: (question: string) => void;
}

const TONE: Record<string, string> = {
  DONE: "ok", NEEDS_USER: "attention", FAILED: "bad", CANCELLED: "muted", BLOCKED: "muted",
  PENDING: "queued", RETRY_WAIT: "queued", SENDING: "busy", ACKED: "busy",
};

function time(ms: number): string {
  return new Date(ms).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

/** One user sentence and the steps it became, newest first. */
export function Timeline({ rows, ...handlers }: { rows: ActionRow[] } & Handlers) {
  const plans = new Map<string, ActionRow[]>();
  for (const row of rows) plans.set(row.planId, [...(plans.get(row.planId) ?? []), row]);
  const ordered = [...plans.values()].sort((a, b) => b[0].createdAtMs - a[0].createdAtMs);
  if (!ordered.length) {
    return (
      <div className="empty">
        <p>还没有记录。</p>
        <p className="muted">在上面说一句话，比如“我吃了布洛芬，有点胃疼，帮我约周三复诊”，会拆成几个动作，先存在本机，再按顺序同步。</p>
      </div>
    );
  }
  return (
    <ol className="timeline">
      {ordered.map((steps) => (
        <li key={steps[0].planId} className="plan">
          <div className="utterance">
            <p>{steps[0].utterance || "（来自其他设备）"}</p>
            <time>{time(steps[0].createdAtMs)} · {steps.length} 个动作</time>
          </div>
          <ol className="steps">
            {steps.map((row) => <StepCard key={row.actionId} row={row} plan={steps} {...handlers} />)}
          </ol>
        </li>
      ))}
    </ol>
  );
}

function StepCard({ row, plan, onDecision, onChoose, onAsk }: { row: ActionRow; plan: ActionRow[] } & Handlers) {
  const spec = TOOLS[row.tool];
  const parents = row.dependsOn.map((id) => plan.find((p) => p.actionId === id)).filter(Boolean) as ActionRow[];
  const answer = row.tool === "ask_pharmacist" && row.state === "DONE" ? pharmacistAnswer(row.resultJson) : undefined;
  const review = row.tool === "record_medication" && row.state === "DONE" ? safetyReview(row.resultJson) : undefined;
  const found = row.state === "NEEDS_USER" ? conflicts(row) : [];
  const choices = row.state === "NEEDS_USER" ? options(row) : [];
  const reason = row.reason && !(row.state === "DONE" && row.reason.startsWith("safety_alert")) ? reasonLabel(row.reason) : null;
  return (
    <li className={`step tone-${TONE[row.state]}`}>
      <div className="step-rail" aria-hidden="true"><span className="dot"><Icon name={TOOL_ICON[row.tool] ?? "pill"} size={15} /></span></div>
      <article className="card">
        <header className="card-head">
          <span className="tool">{spec?.label ?? row.tool}</span>
          <span className={`badge tone-${TONE[row.state]}`}>{STATE_LABEL[row.state]}</span>
        </header>
        <p className="card-main">{summary(row)}</p>
        {parents.length > 0 && row.state === "BLOCKED" && (
          <p className="waits"><Icon name="link" size={14} />等「{parents.map((p) => TOOLS[p.tool]?.label).join("、")}」处理完再发</p>
        )}
        {answer && <AnswerView answer={answer} onChoose={(c) => onChoose(answer, c)} />}
        {review && <SafetyView review={review} onAsk={onAsk} />}
        {found.length > 0 && (
          <div className="conflict">
            <p className="conflict-title">已暂停：联网后的审核结论和这一步冲突，什么都还没发出</p>
            {found.map((c, i) => (
              <div key={i}>
                <p>{c.severity === "high" ? "⚠ " : "• "}{c.summary}</p>
                {c.why && <p className="fine">{c.why}</p>}
              </div>
            ))}
          </div>
        )}
        {row.state === "NEEDS_USER" && (
          <div className="decisions">
            {choices.length === 0 && <button className="secondary" onClick={() => onDecision(row, null)}>取消这一步</button>}
            {choices.map((o, i) => (
              <button key={i} className={o.decision === "cancel" ? "secondary" : i === 0 ? "primary" : "secondary"}
                      onClick={() => onDecision(row, o)}>{optionLabel(o, row.tool)}</button>
            ))}
          </div>
        )}
        <footer className="card-meta">
          {reason && <span>{reason}</span>}
          {row.attempt > 0 && <span>重试 {row.attempt} 次</span>}
          <span className="mono" title={row.stepKey}>step_key {row.stepKey.slice(0, 10)}…</span>
        </footer>
      </article>
    </li>
  );
}
