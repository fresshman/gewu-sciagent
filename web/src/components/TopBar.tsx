import type { Agent, ModelOption } from "../types";
import { useTheme } from "../theme/ThemeProvider";
import { ProjectSelector } from "./ProjectSelector";

export function TopBar({
  topic,
  agents,
  selectedAgent,
  onSelectAgent,
  models,
  selectedModel,
  onSelectModel,
  viewMode,
  onViewModeChange,
}: {
  topic: string;
  agents: Agent[];
  selectedAgent: Agent;
  onSelectAgent: (a: Agent) => void;
  models: ModelOption[];
  selectedModel: string;
  onSelectModel: (id: string) => void;
  viewMode: "chat" | "papers";
  onViewModeChange: (mode: "chat" | "papers") => void;
}) {
  const { theme, toggle } = useTheme();
  return (
    <header className="topbar">
      <div className="topbar__logo">
        <span className="mark" />
        格物
      </div>
      <div className="topbar__topic">· {topic}</div>
      <ProjectSelector />
      <div className="topbar__spacer" />

      <div className="topbar__actions">
        {/* Agent 选择：决定由哪个智能体接收指令 */}
        <select
          className="topbar__model"
          value={selectedAgent.id}
          onChange={(e) => {
            const a = agents.find((x) => x.id === e.target.value);
            if (a) onSelectAgent(a);
          }}
          aria-label="选择 Agent"
          title="选择接收指令的 Agent"
        >
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}（{a.role}）
            </option>
          ))}
        </select>

        {/* 模型（显示用，由 Gateway 配置驱动） */}
        <select
          className="topbar__model"
          value={selectedModel}
          onChange={(e) => onSelectModel(e.target.value)}
          aria-label="默认模型"
          title="默认模型"
        >
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>

        <button
          className={`topbar__btn ${viewMode === "papers" ? "topbar__btn--active" : ""}`}
          onClick={() => onViewModeChange(viewMode === "chat" ? "papers" : "chat")}
          aria-label="切换论文阅读器"
          title={viewMode === "chat" ? "打开论文阅读器" : "返回对话"}
        >
          {viewMode === "chat" ? "📄" : "💬"}
        </button>

        <button className="topbar__btn" onClick={toggle} aria-label="切换主题">
          {theme === "light" ? "🌙" : "☀"}
        </button>
      </div>
    </header>
  );
}
