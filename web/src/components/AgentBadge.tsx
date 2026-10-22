import type { Agent } from "../types";

export function AgentBadge({ agent }: { agent: Agent }) {
  return (
    <span className="agent-badge" style={{ background: agent.color }}>
      <span className="sq" />
      {agent.name} · {agent.role}
    </span>
  );
}
