import type { RedFlag } from "../core/redflag";
import { Icon } from "./Icon";

/** Danger signs come first, decided on the device: big, red, one tap to call. */
export function RedFlagBanner({ flag, onDismiss }: { flag: RedFlag; onDismiss: () => void }) {
  const crisis = flag.kind === "CRISIS";
  return (
    <section className={`redflag ${crisis ? "crisis" : ""}`} role="alert">
      <div className="redflag-icon"><Icon name="alert" size={22} /></div>
      <div className="redflag-body">
        <h2>{crisis ? "你现在可能需要帮助" : "检测到危险信号"}</h2>
        <p className="quote">你说的「{flag.matched}」</p>
        <p>{flag.advice}</p>
        <div className="calls">
          {crisis && <a className="call" href="tel:12356"><Icon name="phone" size={16} />12356 心理援助热线</a>}
          <a className="call" href="tel:120"><Icon name="phone" size={16} />拨打 120</a>
          {crisis && <a className="call ghost" href="tel:110"><Icon name="phone" size={16} />110</a>}
        </div>
        <p className="fine">本机规则判断，不需要联网；只提示求助，不做诊断。</p>
      </div>
      <button className="icon-button" onClick={onDismiss} aria-label="关闭提醒"><Icon name="x" /></button>
    </section>
  );
}
