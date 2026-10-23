import type { Agent, Stage, ModelOption, ChatMessage, CaseBundle } from "../types";

async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`请求失败 ${r.status}`);
  return r.json() as Promise<T>;
}

export function getAgents(): Promise<{ agents: Agent[] }> {
  return getJSON("/api/agents");
}
export function getStages(): Promise<{ stages: Stage[] }> {
  return getJSON("/api/stages");
}
export function getModels(): Promise<{ models: ModelOption[] }> {
  return getJSON("/api/models");
}
export function getHealth(): Promise<{ ok: boolean; gateway: { reachable: boolean; status: string } }> {
  return getJSON("/api/health");
}

export function getCase(): Promise<CaseBundle> {
  return getJSON("/api/case");
}

export interface ChatCallbacks {
  onStart?: (agentId: string) => void;
  onDelta?: (text: string) => void;
  onError?: (text: string) => void;
  onDone?: () => void;
}

// 通过本地代理 /api/chat 发送消息，解析 SSE 流（代理已桥接 Gateway）
export async function sendChat(agentId: string, message: string, cb: ChatCallbacks): Promise<void> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent: agentId, message }),
  });
  if (!res.ok || !res.body) {
    cb.onError?.(`服务异常 (${res.status})`);
    cb.onDone?.();
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      const json = line.slice(5).trim();
      if (!json) continue;
      try {
        const ev = JSON.parse(json);
        if (ev.type === "start") cb.onStart?.(ev.agent);
        else if (ev.type === "delta") cb.onDelta?.(ev.text || "");
        else if (ev.type === "error") cb.onError?.(ev.text || "error");
        else if (ev.type === "done") cb.onDone?.();
      } catch {
        /* 忽略无法解析的分片 */
      }
    }
  }
  cb.onDone?.();
}
