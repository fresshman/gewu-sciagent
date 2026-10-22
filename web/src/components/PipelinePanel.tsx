import type { Stage, Agent } from "../types";
import { AgentBadge } from "./AgentBadge";

// 左栏：7 阶段竖向时间线（PC 全量呈现，含描述与负责 Agent）
export function PipelinePanel({ stages, agents }: { stages: Stage[]; agents: Agent[] }) {
  const agentOf = (id: string) => agents.find((a) => a.id === id);
  return (
    <nav className="pipeline" aria-label="科研阶段管线">
      <div className="pipeline__title">科研阶段管线</div>
      <div className="pipeline__sub">7 阶段闭环 · 点击底部 Tab 切换</div>
      <ol className="timeline">
        {stages.map((s) => {
          const a = agentOf(s.agent);
          return (
            <li key={s.id} className={`timeline__item timeline__item--${s.status}`}>
              <div className="timeline__rail">
                <span className="timeline__dot" />
              </div>
              <div>
                <div className="timeline__name">
                  {s.name}
                  {s.status === "done" ? " ✓" : s.status === "active" ? " ·进行中" : ""}
                </div>
                <div className="timeline__desc">{s.desc}</div>
                {a && (
                  <div className="timeline__agent">
                    <AgentBadge agent={a} />
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
