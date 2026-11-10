import { useEffect, useRef, useState } from "react";
import type { RunStatus, RunStep } from "../types";
import { dispositionText, dispositionTone } from "../lib/disposition";

// 左下角常驻任务圆环：7 阶段的长任务可能跑十几分钟，一旦切到论文库/阅读器，
// 顶部那排「执行进度」就整块消失了，用户只能靠猜。
//
// 交互按需求里那组时间常数来：hover 400ms 才展开（避免划过就弹），
// 移开 100ms 就收（收得要比展得利落）。没有总步数时给不确定弧，绝不假装百分比——
// 我们只知道「已经发生了几步」，不知道「一共几步」。

const R = 15;
const CIRC = 2 * Math.PI * R;

function STATUS_COLOR(s: RunStatus | null): string {
  if (s === "success") return "var(--accent-teal)";
  if (s === "error" || s === "timeout" || s === "aborted") return "var(--danger)";
  return "var(--brand)";
}

const STATUS_TEXT: Record<string, string> = {
  running: "运行中",
  success: "已完成",
  timeout: "已超时",
  error: "出错",
  aborted: "已中止",
};

export function TaskOrb({
  steps,
  status,
  onJump,
}: {
  steps: RunStep[];
  status: RunStatus | null;
  /** 点击圆环回到对话页 —— 进度详情在那儿 */
  onJump?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  // 完成后让满环停留一会儿再消失，否则「跑完了」这件事一闪而过
  const [lingering, setLingering] = useState(false);
  const prev = useRef<RunStatus | null>(null);

  useEffect(() => {
    const was = prev.current;
    prev.current = status;
    if (was === "running" && status && status !== "running") {
      setLingering(true);
      const t = window.setTimeout(() => setLingering(false), 2600);
      return () => window.clearTimeout(t);
    }
  }, [status]);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const tools = steps.filter((s) => s.kind === "tool");
  const running = status === "running" || tools.some((s) => s.status === "running");
  const failed = tools.filter((s) => s.status === "error").length;

  if (!steps.length && !running) return null;

  const show = running || lingering;
  if (!show) return null;

  const enter = () => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(true), 400);
  };
  const leave = () => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(false), 100);
  };

  const color = STATUS_COLOR(status);
  const done = !running;

  return (
    <div
      className="orb"
      onMouseEnter={enter}
      onMouseLeave={leave}
      onFocus={enter}
      onBlur={leave}
    >
      <button
        type="button"
        className={`orb__btn ${running ? "is-live" : ""}`}
        aria-label={`任务${STATUS_TEXT[status || "running"] || ""}，${tools.length} 步`}
        onClick={onJump}
        title={onJump ? "回到对话页看完整进度" : undefined}
      >
        <svg viewBox="0 0 36 36" className="orb__svg" aria-hidden>
          <circle cx="18" cy="18" r={R} fill="none" stroke="var(--border)" strokeWidth="3" />
          <circle
            cx="18" cy="18" r={R} fill="none"
            stroke={color} strokeWidth="3" strokeLinecap="round"
            transform="rotate(-90 18 18)"
            style={{
              // 跑着：一小段弧自己转（不确定进度）；跑完：合成整圈
              strokeDasharray: done ? `${CIRC} ${CIRC}` : `${CIRC * 0.18} ${CIRC}`,
              transition: "stroke-dasharray .45s ease, stroke .3s ease",
            }}
          />
        </svg>
        <span className="orb__n">{tools.length}</span>
        {failed > 0 && <span className="orb__bad">{failed}</span>}
      </button>

      {open && (
        <div className="orb__panel" role="status">
          <div className="orb__head">
            <span className={`orb__dot ${running ? "is-live" : ""}`} style={{ background: color }} />
            <b>{STATUS_TEXT[status || "running"] || "运行中"}</b>
            <span className="orb__meta">
              {tools.length} 次工具调用{failed ? ` · ${failed} 失败` : ""}
            </span>
          </div>
          <ol className="orb__list">
            {steps
              .filter((s) => s.kind === "tool" || s.kind === "ended")
              .slice(-6)
              .map((s, i) => (
                <li
                  key={`${s.ts}-${i}`}
                  className={`orb__row orb__row--${
                    // 结束行没有 status，得按 disposition 定色，否则「出错结束」也显示成绿色对勾
                    s.kind === "ended"
                      ? { ok: "ok", err: "error", warn: "running" }[dispositionTone(s.disposition)]
                      : s.status || "ok"
                  }`}
                >
                  <span className="orb__ic">
                    {s.kind === "ended" ? "⏹" : s.status === "running" ? "◐" : s.status === "error" ? "✕" : "✓"}
                  </span>
                  <code title={s.kind === "ended" ? s.disposition : undefined}>
                    {s.kind === "ended" ? `结束 · ${dispositionText(s.disposition)}` : s.tool}
                  </code>
                </li>
              ))}
          </ol>
          {running && !done && (
            <div className="orb__hint">总步数未知，弧表示「还在动」而不是完成度</div>
          )}
          {!running && (
            <div className="orb__hint">已结束，可从对话页看完整记录或续跑</div>
          )}
        </div>
      )}
    </div>
  );
}
