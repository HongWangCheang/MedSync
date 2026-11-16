import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import type { Controller } from "./core/controller";
import { Capabilities } from "./components/Capabilities";
import { Composer } from "./components/Composer";
import { Header } from "./components/Header";
import { RedFlagBanner } from "./components/RedFlagBanner";
import { Timeline } from "./components/Timeline";

type Filter = "all" | "attention" | "queued";

export function App({ controller }: { controller: Controller }) {
  const s = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  const [filter, setFilter] = useState<Filter>("all");
  useEffect(() => controller.start(), [controller]);

  const counts = useMemo(() => ({
    attention: s.rows.filter((r) => r.state === "NEEDS_USER").length,
    queued: s.rows.filter((r) => !["DONE", "FAILED", "CANCELLED", "NEEDS_USER"].includes(r.state)).length,
  }), [s.rows]);
  const rows = useMemo(() => {
    if (filter === "all") return s.rows;
    const keep = new Set(s.rows.filter((r) => filter === "attention" ? r.state === "NEEDS_USER"
      : !["DONE", "FAILED", "CANCELLED", "NEEDS_USER"].includes(r.state)).map((r) => r.planId));
    return s.rows.filter((r) => keep.has(r.planId));
  }, [s.rows, filter]);

  return (
    <div className="app">
      <Header s={s} onOffline={(v) => void controller.setOffline(v)} onSync={() => void controller.sync()} />
      <div className="layout">
        <main>
          {s.redFlag && <RedFlagBanner flag={s.redFlag} onDismiss={() => controller.dismissRedFlag()} />}
          <Composer onSend={(t) => void controller.submit(t)} offline={s.offline} />
          {s.notice && <p className="notice" role="status">{s.notice}</p>}
          <nav className="filters" aria-label="筛选">
            {([["all", "全部", s.rows.length], ["attention", "需要确认", counts.attention], ["queued", "排队中", counts.queued]] as const)
              .map(([key, label, n]) => (
                <button key={key} className={filter === key ? "on" : ""} onClick={() => setFilter(key)}>
                  {label}{n > 0 && <span className={`count ${key === "attention" && n ? "hot" : ""}`}>{n}</span>}
                </button>
              ))}
          </nav>
          <Timeline rows={rows}
                    onDecision={(row, d) => void controller.resolve(row, d)}
                    onChoose={(a, c) => void controller.choose(a, c)}
                    onAsk={(q) => void controller.submit(q)} />
        </main>
        <aside>
          <Capabilities offline={s.offline} />
          <section className="panel how">
            <h3>它是怎么做到只执行一次的</h3>
            <ol>
              <li>说的话先在本机拆成几个动作，每个动作在发送前就生成 <code>step_key</code> 并存进本机。</li>
              <li>断网、超时、重试、刷新页面，都用同一个 <code>step_key</code>，网关、Agent、工具三处按它去重。</li>
              <li>排队期间情况变了（号源被抢、审核发现冲突），会停下来问你。</li>
            </ol>
          </section>
        </aside>
      </div>
    </div>
  );
}
