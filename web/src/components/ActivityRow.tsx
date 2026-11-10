import { useState } from "react";
import type { RunStep, RunStatus } from "../types";

// 一条消息做了什么 —— 挂在气泡下面，而不是全塞进顶部的执行进度面板。
//
// 之所以要按消息归属：runSteps 是全局一份，发第二条消息就整体清空，
// 于是上一轮「调了哪些工具、哪个失败了」当场消失。历史里只剩一段没头没尾的回答，
// 谁也没法回头核对它是怎么得出来的。

function ms(at?: string): number {
  const v = Date.parse(at || "");
  return Number.isFinite(v) ? v : NaN;
}

function duration(steps: RunStep[]): number | null {
  if (!steps.length) return null;
  const first = ms(steps[0].startedTs ?? steps[0].ts);
  const lastStep = steps[steps.length - 1];
  const last = ms(lastStep.endedTs ?? lastStep.ts);
  if (!Number.isFinite(first) || !Number.isFinite(last) || last < first) return null;
  return last - first;
}

function fmtDur(d: number | null): string {
  if (d == null) return "";
  if (d < 1000) return `${d} ms`;
  if (d < 60000) return `${(d / 1000).toFixed(1)} s`;
  return `${Math.floor(d / 60000)} 分 ${Math.round((d % 60000) / 1000)} 秒`;
}

const ICON: Record<string, string> = {
  running: "◐",
  ok: "✓",
  error: "✕",
};

function StepLine({ s }: { s: RunStep }) {
  if (s.kind === "tool") {
    const st = s.status || "ok";
    return (
      <li className={`act__row act__row--${st}`}>
        <span className="act__ic">{ICON[st] || "•"}</span>
        <code className="act__tool">{s.tool}</code>
        {s.status === "running" && s.detail ? (
          <span className="act__arg" title={s.detail}>{s.detail}</span>
        ) : s.result && s.result !== "ok" ? (
          <span className="act__arg" title={s.result}>{s.result}</span>
        ) : null}
      </li>
    );
  }
  if (s.kind === "model") {
    return (
      <li className="act__row act__row--model">
        <span className="act__ic">◇</span>
        <span className="act__note">模型推理{s.detail ? ` · ${s.detail}` : ""}</span>
      </li>
    );
  }
  if (s.kind === "ended") {
    return (
      <li className="act__row act__row--end">
        <span className="act__ic">⏹</span>
        <span className="act__note">结束 · {s.disposition || "—"}</span>
      </li>
    );
  }
  return null;
}

export function ActivityRow({ steps, status }: { steps?: RunStep[]; status?: RunStatus }) {
  // 用户没表过态时跟随运行状态：跑着就摊开（不然只看见一个转圈），
  // 跑完就收起。点过之后一律听用户的，不再被状态改回去。
  const [manual, setManual] = useState<boolean | null>(null);

  const list = (steps || []).filter((s) => s.kind === "tool" || s.kind === "model" || s.kind === "ended");
  if (!list.length) return null;

  const running = status === "running" || list.some((s) => s.status === "running");
  const open = manual ?? running;
  const tools = list.filter((s) => s.kind === "tool").length;
  const failed = list.filter((s) => s.status === "error").length;
  const lastRunning = [...list].reverse().find((s) => s.status === "running");
  const dur = fmtDur(duration(list));

  let summary: string;
  if (running && lastRunning?.tool) summary = `调用 ${lastRunning.tool}…`;
  else if (running) summary = "执行中…";
  else if (failed) summary = `${tools} 次工具调用 · ${failed} 次失败${dur ? ` · ${dur}` : ""}`;
  else summary = `${tools} 次工具调用${dur ? ` · ${dur}` : ""}`;

  return (
    <div className={`act ${open ? "act--open" : ""}`}>
      <button
        type="button"
        className="act__head"
        aria-expanded={open}
        onClick={() => setManual(!open)}
      >
        <span className={`act__dot ${running ? "is-live" : failed ? "is-bad" : "is-ok"}`} />
        <span className="act__sum">{summary}</span>
        <span className="act__caret">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <ol className="act__list">
          {list.map((s, i) => <StepLine key={`${s.ts}-${i}`} s={s} />)}
        </ol>
      )}
    </div>
  );
}
