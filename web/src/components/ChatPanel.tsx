import type { ChatMessage, Stage, Agent } from "../types";
import { StageStrip } from "./StageStrip";
import { MessageBubble } from "./MessageBubble";
import { Composer } from "./Composer";

export function ChatPanel({
  stages,
  messages,
  agents,
  selectedAgent,
  isStreaming,
  onSend,
}: {
  stages: Stage[];
  messages: ChatMessage[];
  agents: Agent[];
  selectedAgent: Agent;
  isStreaming: boolean;
  onSend: (text: string) => void;
}) {
  const agentOf = (id?: string) => agents.find((a) => a.id === id);
  return (
    <section className="chat">
      <StageStrip stages={stages} />
      <div className="chat__scroll">
        {messages.length === 0 ? (
          <div className="chat__empty">
            <div className="big">格物 · 科研工作台</div>
            用一句话开启研究：定方向、读论文、复现、改进、写论文、发表、沉淀——
            7 个阶段、7 个 Agent 已在 Gateway 就位。当前由「{selectedAgent.name}」接收指令。
          </div>
        ) : (
          messages.map((m) => (
            <MessageBubble key={m.id} msg={m} agent={agentOf(m.agentId)} />
          ))
        )}
      </div>
      <Composer onSend={onSend} disabled={isStreaming} />
    </section>
  );
}
