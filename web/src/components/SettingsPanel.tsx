import type { Agent, ModelOption } from "../types";
import { useTheme } from "../theme/ThemeProvider";

export function SettingsPanel({
  agents,
  selectedAgent,
  onSelectAgent,
  models,
  selectedModel,
  onSelectModel,
}: {
  agents: Agent[];
  selectedAgent: Agent;
  onSelectAgent: (a: Agent) => void;
  models: ModelOption[];
  selectedModel: string;
  onSelectModel: (id: string) => void;
}) {
  const { theme, toggle } = useTheme();
  return (
    <div className="settings">
      <div className="right__title">设置</div>
      <div className="settings__row">
        <span>主题</span>
        <button className="topbar__btn" onClick={toggle}>
          {theme === "light" ? "🌙 暗色" : "☀ 亮色"}
        </button>
      </div>
      <div className="settings__row">
        <span>接收指令的 Agent</span>
        <select
          className="topbar__model"
          value={selectedAgent.id}
          onChange={(e) => {
            const a = agents.find((x) => x.id === e.target.value);
            if (a) onSelectAgent(a);
          }}
        >
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}（{a.role}）
            </option>
          ))}
        </select>
      </div>
      <div className="settings__row">
        <span>默认模型</span>
        <select
          className="topbar__model"
          value={selectedModel}
          onChange={(e) => onSelectModel(e.target.value)}
        >
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </div>
      <div className="right__placeholder muted" style={{ marginTop: "var(--space-4)" }}>
        格物 Web 为轻量前端，经本地代理接入 OpenClaw Gateway；对话由书生大模型（intern-s2 等）驱动。
      </div>
    </div>
  );
}
