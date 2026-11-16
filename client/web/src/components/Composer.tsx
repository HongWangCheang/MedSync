import { useState, type FormEvent, type KeyboardEvent } from "react";
import { Icon } from "./Icon";

const EXAMPLES = ["我吃了布洛芬，有点胃疼，帮我约周三复诊", "吃了华法林", "我吃了布洛芬，告诉女儿我没事", "布洛芬能和阿司匹林一起吃吗？"];

export function Composer({ onSend, offline }: { onSend: (text: string) => void; offline: boolean }) {
  const [text, setText] = useState("");
  const send = (e?: FormEvent) => {
    e?.preventDefault();
    if (!text.trim()) return;
    onSend(text);
    setText("");
  };
  const key = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) send(e);
  };
  return (
    <form className="composer" onSubmit={send}>
      <label className="sr-only" htmlFor="say">说一句话</label>
      <div className="composer-box">
        <textarea id="say" rows={2} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={key}
                  placeholder="说说你今天的情况，例如：我吃了布洛芬，有点胃疼，帮我约周三复诊" />
        <button type="submit" className="primary" disabled={!text.trim()} aria-label="发送">
          <Icon name="send" />
          <span>发送</span>
        </button>
      </div>
      <div className="examples">
        {EXAMPLES.map((e) => <button type="button" key={e} className="chip" onClick={() => setText(e)}>{e}</button>)}
      </div>
      {offline && <p className="hint">离线时也能说：记录会先存在本机，预约和通知排队，联网后自动发出。</p>}
    </form>
  );
}
