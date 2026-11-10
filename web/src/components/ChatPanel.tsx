import { useEffect, useState } from "react";
import type { ChatMessage, Stage, Agent } from "../types";
import { parseAsk } from "../lib/ask";
import { StageStrip } from "./StageStrip";
import { MessageBubble } from "./MessageBubble";
import { Composer } from "./Composer";

// 「已回答」不另存状态：用户点选项后那条回答就是下一条 user 消息，
// 后面有没有 user 消息本身就是答案。多存一份状态只会两处对不上。

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

  // 最后一条 agent 消息里挂着一个没答的问卷 → 输入框让位。
  // 不让位的话，用户会以为还能自由聊天，偏偏 agent 正在等一个具体答案。
  const last = messages[messages.length - 1];
  const pending =
    last && last.role === "assistant" && !last.streaming ? parseAsk(last.text) : null;

  // 逃生口：问卷写坏了（或用户就是想自己说），不能把人锁在门外
  const [bypass, setBypass] = useState(false);
  useEffect(() => {
    setBypass(false); // 换了一轮对话，重新按问卷走
  }, [last?.id]);

  const askVisible = Boolean(pending) && !bypass && !isStreaming;

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
          messages.map((m, i) => {
            // 这条消息里的问卷答了没有：看它之后有没有 user 消息
            const nextUser = messages.slice(i + 1).find((x) => x.role === "user");
            const isLastAsk = i === messages.length - 1 && Boolean(pending);
            return (
              <MessageBubble
                key={m.id}
                msg={m}
                agent={agentOf(m.agentId)}
                answered={nextUser ? nextUser.text.trim() : undefined}
                onAnswer={isLastAsk ? onSend : undefined}
              />
            );
          })
        )}
      </div>
      {askVisible ? (
        <div className="chat__gate">
          <span className="chat__gate-txt">请先回答上方的问题</span>
          <button type="button" className="chat__gate-btn" onClick={() => setBypass(true)}>
            改为自由输入
          </button>
        </div>
      ) : (
        <Composer onSend={onSend} disabled={isStreaming} />
      )}
    </section>
  );
}
