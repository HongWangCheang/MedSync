import { useState } from "react";
import { choiceTitle, segments, type Choice, type PharmacistAnswer } from "../core/results";

/** The pharmacist's answer: [S1] markers open the label passage they rest on. */
export function AnswerView({ answer, onChoose }: { answer: PharmacistAnswer; onChoose: (c: Choice) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const toggle = (marker: string) => {
    const id = /S\d+/.exec(marker)?.[0] ?? null;
    setOpen(open === id ? null : id);
  };
  return (
    <div className={`answer ${answer.grounded ? "" : "refused"}`}>
      {!answer.grounded && <p className="tag">没有找到可引用的说明书原文，所以不作回答</p>}
      <p className="answer-text">
        {segments(answer.text).map((s, i) => s.cite
          ? <button key={i} className="cite" onClick={() => toggle(s.text)}>{s.text.replace(/[[\]\s]/g, "")}</button>
          : <span key={i}>{s.text}</span>)}
      </p>
      {answer.citations.length > 0 && (
        <ul className="sources">
          {answer.citations.map((c) => (
            <li key={c.id} className={open === c.id ? "open" : ""}>
              <button className="source" onClick={() => setOpen(open === c.id ? null : c.id)} aria-expanded={open === c.id}>
                <span className="cite static">{c.id}</span>
                <span className="source-name">{c.label}</span>
                <span className="muted">{c.section}</span>
              </button>
              {open === c.id && (
                <blockquote>
                  “{c.excerpt}”
                  {c.url && <a href={c.url} target="_blank" rel="noreferrer">openFDA 原始记录</a>}
                </blockquote>
              )}
            </li>
          ))}
        </ul>
      )}
      {answer.awaitingChoice && answer.choices.length > 0 && (
        <div className="choices">
          <p className="muted">点一下你在用的那一款，会接着回答：</p>
          {answer.choices.map((c) => (
            <button key={`${c.labelId}-${c.version}`} className="choice" onClick={() => onChoose(c)}>{choiceTitle(c)}</button>
          ))}
        </div>
      )}
      {answer.awaitingChoice && answer.choices.length === 0 && (
        <p className="muted">直接回复产品名即可，例如“ADVIL”，会接着这个问题回答。</p>
      )}
      <p className="fine">仅摘录说明书原文，不能代替医生或药师的建议。</p>
    </div>
  );
}
