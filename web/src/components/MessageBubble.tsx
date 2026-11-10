import type { ChatMessage, Agent } from "../types";
import { renderMarkdown } from "../lib/markdown";
import { parseAsk, stripAsk } from "../lib/ask";
import { ActivityRow } from "./ActivityRow";
import { AgentBadge } from "./AgentBadge";
import { AskUserCard } from "./AskUserCard";

export function MessageBubble({
  msg,
  agent,
  onAnswer,
  answered,
}: {
  msg: ChatMessage;
  agent?: Agent;
  /** 只有「当前待回答」的那条消息才给回调；历史消息里的问卷只回显 */
  onAnswer?: (text: string) => void;
  /** 已回答：填入用户实际发回的那句话 */
  answered?: string;
}) {
  const isUser = msg.role === "user";
  // 结构化提问：从正文里摘掉围栏，正文照旧按 Markdown 渲染，问卷单独成块
  const ask = isUser || msg.streaming ? null : parseAsk(msg.text);
  const body = ask ? stripAsk(msg.text, ask) : msg.text;

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
          body.trim() && <div className="md">{renderMarkdown(body)}</div>
        )}
        {ask && (
          <AskUserCard
            block={ask}
            answered={answered}
            // 历史里没被回答的问卷只回显：给个空回调会造出「能点但没反应」的死按钮
            locked={!answered && !onAnswer}
            onAnswer={onAnswer || (() => {})}
          />
        )}
        {msg.error && <div className="muted" style={{ fontSize: "var(--fs-micro)", marginTop: 6 }}>（该消息出错，请重试）</div>}
      </div>
    </div>
  );
}
