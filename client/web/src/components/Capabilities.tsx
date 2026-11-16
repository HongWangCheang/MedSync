import { useState } from "react";

/** What works without a network (the degradation matrix), shown so nothing surprises the user. */
const TIERS = [
  { key: "local", label: "离线可用", items: [["理解你的话", "本机规则（网页版没有端侧模型）"], ["危险信号", "本机规则"],
    ["记录服药和症状", "先存在本机，联网后同步"]] },
  { key: "queued", label: "联网后执行", items: [["预约复诊", "联网后先确认号源还在"], ["通知家属", "过期的消息会先问你"],
    ["相互作用检查", "服药记录同步后补查"]] },
  { key: "online", label: "需要联网", items: [["用药问答", "要检索说明书，离线不回答"]] },
];

export function Capabilities({ offline }: { offline: boolean }) {
  const [open, setOpen] = useState(false);
  const expanded = offline || open;
  return (
    <section className={`panel capabilities ${offline ? "highlight" : ""}`}>
      <button className="panel-title" onClick={() => setOpen(!open)} aria-expanded={expanded} disabled={offline}>
        <span>{offline ? "现在离线，各项功能：" : "断网时各项功能"}</span>
        {!offline && <span className="muted">{expanded ? "收起" : "展开"}</span>}
      </button>
      {expanded && (
        <ul className="tiers">
          {TIERS.map((t) => (
            <li key={t.key} className={`tier ${t.key}`}>
              <span className="tier-label">{t.label}</span>
              <ul>{t.items.map(([name, note]) => <li key={name}><strong>{name}</strong><span>{note}</span></li>)}</ul>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
