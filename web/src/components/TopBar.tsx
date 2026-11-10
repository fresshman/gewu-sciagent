import type { Agent, ModelOption, ViewMode } from "../types";
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
  viewMode: ViewMode;
  onViewModeChange: (mode: ViewMode) => void;
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

        {/* 论文阅读器 / 论文管理是两个入口：前者读单篇 PDF，后者管理整条文献链与自己的稿子 */}
        <button
          className={`topbar__btn ${viewMode === "papers" ? "topbar__btn--active" : ""}`}
          onClick={() => onViewModeChange(viewMode === "papers" ? "chat" : "papers")}
          aria-label="论文阅读器"
          title={viewMode === "papers" ? "返回对话" : "打开论文阅读器"}
        >
          📄
        </button>
        <button
          className={`topbar__btn ${viewMode === "library" ? "topbar__btn--active" : ""}`}
          onClick={() => onViewModeChange(viewMode === "library" ? "chat" : "library")}
          aria-label="论文库与写作台"
          title={viewMode === "library" ? "返回对话" : "论文库 / 写作台"}
        >
          📚
        </button>

        <button className="topbar__btn" onClick={toggle} aria-label="切换主题">
          {theme === "light" ? "🌙" : "☀"}
        </button>
      </div>
    </header>
  );
}
