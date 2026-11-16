import type { Snapshot } from "../core/controller";
import { Icon } from "./Icon";

function ago(ms: number): string {
  const s = Math.round((Date.now() - ms) / 1000);
  return s < 10 ? "刚刚" : s < 60 ? `${s} 秒前` : `${Math.round(s / 60)} 分钟前`;
}

export function Header({ s, onOffline, onSync }: { s: Snapshot; onOffline: (v: boolean) => void; onSync: () => void }) {
  const queued = s.rows.filter((r) => !["DONE", "FAILED", "CANCELLED", "NEEDS_USER"].includes(r.state)).length;
  return (
    <header className={`header ${s.offline ? "is-offline" : ""}`}>
      <div className="brand">
        <span className="logo" aria-hidden="true"><Icon name="shield" size={20} /></span>
        <div>
          <h1>MedSync</h1>
          <p className="sub">{s.offline ? "离线中：记录先存在本机" : "在线：动作会同步到服务器"}</p>
        </div>
      </div>
      <div className="header-actions">
        <button className="sync" onClick={onSync} disabled={s.offline || s.syncing} title="立即同步">
          <span className={s.syncing ? "spin" : ""}><Icon name="sync" /></span>
          <span className="sync-text">
            {s.syncing ? "同步中…" : s.lastSync ? `${ago(s.lastSync.atMs)}同步` : "同步"}
            {queued > 0 && <em>{queued} 个排队</em>}
          </span>
        </button>
        <div className="segmented" role="radiogroup" aria-label="网络">
          <button role="radio" aria-checked={!s.offline} className={!s.offline ? "on" : ""} onClick={() => onOffline(false)}>
            <Icon name="wifi" size={16} />在线
          </button>
          <button role="radio" aria-checked={s.offline} className={s.offline ? "on off" : ""} onClick={() => onOffline(true)}>
            <Icon name="wifiOff" size={16} />离线（模拟）
          </button>
        </div>
      </div>
    </header>
  );
}
