import type { ChatMessage, Agent } from "../types";
import { renderMarkdown } from "../lib/markdown";
import { ActivityRow } from "./ActivityRow";
import { AgentBadge } from "./AgentBadge";

export function MessageBubble({ msg, agent }: { msg: ChatMessage; agent?: Agent }) {
  const isUser = msg.role === "user";
  return (
    <div className={`msg msg--${isUser ? "user" : "bot"}`}>
      {!isUser && <ActivityRow steps={msg.steps} status={msg.runStatus} />}
      <div className="msg__bubble">
        {!isUser && agent && (
          <div className="msg__head">
            <AgentBadge agent={agent} />
          </div>
        )}
        {msg.streaming && !msg.text ? (
          <span className="typing" aria-label="正在思考">
            <span />
            <span />
            <span />
          </span>
        ) : isUser ? (
          // 用户输入保持原样：换行是他自己敲的，合并成段落反而失真
          msg.text
        ) : (
          // agent 输出是 Markdown。以前直接输出原文，于是 **粗体**、### 标题、
          // 表格竖线全裸露，看着像没渲染的源码。
          <div className="md">{renderMarkdown(msg.text)}</div>
        )}
        {msg.error && <div className="muted" style={{ fontSize: "var(--fs-micro)", marginTop: 6 }}>（该消息出错，请重试）</div>}
      </div>
    </div>
  );
}
