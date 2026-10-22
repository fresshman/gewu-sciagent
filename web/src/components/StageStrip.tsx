import type { Stage } from "../types";

// 阶段胶囊条：移动端概览 / 桌面端中栏顶部，均横排展示，不展开细节
export function StageStrip({ stages }: { stages: Stage[] }) {
  return (
    <div className="stage-strip" role="list" aria-label="科研阶段进度">
      {stages.map((s) => (
        <span
          key={s.id}
          role="listitem"
          className={`stage-chip stage-chip--${s.status}`}
          title={s.desc}
        >
          <span className="dot" />
          {s.name}
          {s.status === "done" ? " ✓" : s.status === "active" ? " …" : ""}
        </span>
      ))}
    </div>
  );
}
