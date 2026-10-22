import { useState, useRef, type KeyboardEvent } from "react";

export function Composer({
  onSend,
  disabled,
}: {
  onSend: (text: string) => void;
  disabled: boolean;
}) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    const t = text.trim();
    if (!t || disabled) return;
    onSend(t);
    setText("");
    if (ref.current) ref.current.style.height = "auto";
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const onInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value);
    const el = ref.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 140) + "px";
    }
  };

  return (
    <div>
      <div className="composer__hint">
        回车发送 · Shift+Enter 换行 · 由 OpenClaw Gateway 经书生大模型驱动
      </div>
      <div className="composer">
        <textarea
          ref={ref}
          className="composer__input"
          placeholder="给格物下达科研指令，例如：帮我复现 MIL 方法…"
          value={text}
          onChange={onInput}
          onKeyDown={onKey}
          rows={1}
        />
        <button className="composer__send" onClick={submit} disabled={disabled || !text.trim()}>
          ↗ 发送
        </button>
      </div>
    </div>
  );
}
