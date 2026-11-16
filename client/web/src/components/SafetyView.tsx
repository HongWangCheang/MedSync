import { useState } from "react";
import { askAbout, coverage, headline, type SafetyReview } from "../core/results";

/** The safety review of a synced medication record: every alert with the label text it rests on. */
export function SafetyView({ review, onAsk }: { review: SafetyReview; onAsk: (q: string) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const high = review.alerts.some((a) => a.high);
  const tone = high ? "high" : review.alerts.length ? "warn" : review.status === "ok" ? "ok" : "muted";
  return (
    <div className={`safety ${tone}`}>
      <p className="safety-title">{headline(review)}</p>
      {review.alerts.map((alert) => (
        <div key={alert.with} className="alert">
          {alert.findings.map((f, i) => {
            const key = `${alert.with}-${i}`;
            return (
              <div key={key} className="finding">
                <p>{alert.high ? "⚠ " : "• "}{f.summary}</p>
                <button className="link" onClick={() => setOpen(open === key ? null : key)} aria-expanded={open === key}>
                  {f.label} · {f.section}（{open === key ? "收起原文" : "看原文"}）
                </button>
                {open === key && <blockquote>“{f.excerpt}”</blockquote>}
              </div>
            );
          })}
          <button className="secondary small" onClick={() => onAsk(askAbout(review, alert))}>问药师：和{alert.with}能一起吃吗</button>
        </div>
      ))}
      {coverage(review).length > 0 && <p className="fine">{coverage(review).join("；")}</p>}
      {review.note && <p className="fine">{review.note}</p>}
    </div>
  );
}
