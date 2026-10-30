import { useEffect, useState } from "react";
import { getRuns, getRun } from "../api/client";
import type { RunStep, RunListEntry, RunRecord, RunStatus } from "../types";

const STATUS_TEXT: Record<RunStatus, string> = {
  running: "运行中",
  success: "完成",
  timeout: "超时",
  error: "出错",
  aborted: "已中止",
};
const STATUS_CLASS: Record<RunStatus, string> = {
  running: "st-running",
  success: "st-success",
  timeout: "st-timeout",
  error: "st-error",
  aborted: "st-aborted",
};

function StepRow({ step }: { step: RunStep }) {
  if (step.kind === "tool") {
    if (step.status === "running")
      return (
        <li className="runstep runstep--running">
          🔄 调用 <code>{step.tool}</code>
          {step.detail ? <span className="runstep-args"> · {step.detail}</span> : null}
        </li>
      );
    if (step.status === "error")
      return <li className="runstep runstep--error">❌ <code>{step.tool}</code> · {step.result || "失败"}</li>;
    return (
      <li className="runstep runstep--ok">
        ✅ <code>{step.tool}</code>
        {step.result && step.result !== "ok" ? ` · ${step.result}` : ""}
      </li>
    );
  }
  if (step.kind === "model") return <li className="runstep">🧠 模型推理完成</li>;
  if (step.kind === "ended") return <li className="runstep runstep--end">⏹ 会话结束 · {step.disposition || "—"}</li>;
  if (step.detail) return <li className="runstep runstep--muted">• {step.detail}</li>;
  return null;
}

export function RunPanel({
  runSteps,
  runKey,
  status,
  onResume,
  resumeKey,
}: {
  runSteps: RunStep[];
  runKey: string | null;
  status: RunStatus | null;
  onResume: (key: string) => void;
  resumeKey: string | null;
}) {
  const [showHistory, setShowHistory] = useState(false);
  const [runs, setRuns] = useState<RunListEntry[]>([]);
  const [detail, setDetail] = useState<RunRecord | null>(null);

  useEffect(() => {
    if (showHistory && runs.length === 0) {
      getRuns()
        .then((r) => setRuns(r.runs))
        .catch(() => setRuns([]));
    }
  }, [showHistory, runs.length]);

  const openDetail = (key: string) => {
    getRun(key)
      .then(setDetail)
      .catch(() => setDetail(null));
  };

  const hasLive = runKey && runSteps.length > 0;

  return (
    <section className="runpanel">
      <div className="runpanel__head">
        <span className="runpanel__title">执行进度</span>
        {status && <span className={`runbadge ${STATUS_CLASS[status]}`}>{STATUS_TEXT[status]}</span>}
        <button className="runpanel__toggle" onClick={() => setShowHistory((v) => !v)}>
          {showHistory ? "收起历史" : "历史任务 ▾"}
        </button>
      </div>

      {hasLive && (
        <ul className="runsteps">
          {runSteps.map((s, i) => (
            <StepRow key={i} step={s} />
          ))}
          {status === "running" && <li className="runstep runstep--live">⏳ 智能体工作中…</li>}
        </ul>
      )}
      {resumeKey && (
        <div className="runpanel__hint runpanel__hint--resume">
          ↻ 续跑模式：在下方输入框发送消息，将承接该任务的上下文继续未完成的部分。
        </div>
      )}
      {!hasLive && !showHistory && (
        <div className="runpanel__hint">发送消息后，这里实时显示智能体的工具调用进度；即使超时或关闭页面，已完成步骤也会保留。</div>
      )}

      {showHistory && (
        <div className="runpanel__history">
          {runs.length === 0 && <div className="runpanel__hint">暂无历史任务。</div>}
          {runs.map((r) => (
            <div className="runitem" key={r.key}>
              <span className={`runbadge ${STATUS_CLASS[r.status]}`}>{STATUS_TEXT[r.status]}</span>
              <span className="runitem__msg" title={r.message}>{r.message}</span>
              <span className="runitem__meta">{r.stepCount} 步</span>
              <button className="runitem__btn" onClick={() => openDetail(r.key)}>查看</button>
              {(r.status === "timeout" || r.status === "error" || r.status === "aborted") && (
                <button className="runitem__btn runitem__btn--resume" onClick={() => onResume(r.key)}>续跑</button>
              )}
            </div>
          ))}
        </div>
      )}

      {detail && (
        <div className="runpanel__detail">
          <div className="runpanel__detail-head">
            <span>任务详情</span>
            <button className="runpanel__toggle" onClick={() => setDetail(null)}>关闭 ✕</button>
          </div>
          <div className="runpanel__detail-msg">{detail.message}</div>
          <ul className="runsteps">
            {detail.steps.map((s, i) => (
              <StepRow key={i} step={s} />
            ))}
          </ul>
          {(detail.status === "timeout" || detail.status === "error" || detail.status === "aborted") && (
            <button className="runitem__btn runitem__btn--resume" onClick={() => { onResume(detail.key); setDetail(null); }}>
              从此续跑
            </button>
          )}
        </div>
      )}
    </section>
  );
}
