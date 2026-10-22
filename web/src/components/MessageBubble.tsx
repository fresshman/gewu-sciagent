import type { ChatMessage, Agent } from "../types";
import { AgentBadge } from "./AgentBadge";

export function MessageBubble({ msg, agent }: { msg: ChatMessage; agent?: Agent }) {
  const isUser = msg.role === "user";
  return (
    <div className={`msg msg--${isUser ? "user" : "bot"}`}>
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
        ) : (
          msg.text
        )}
        {msg.error && <div className="muted" style={{ fontSize: "var(--fs-micro)", marginTop: 6 }}>（该消息出错，请重试）</div>}
      </div>
    </div>
  );
}
