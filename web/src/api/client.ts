import type { Agent, Stage, ModelOption, ChatMessage, CaseBundle, RunRecord, RunListEntry, RunStep, RunStatus } from "../types";

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

export function getProjects(): Promise<{ active_project: string | null; projects: Record<string, any> }> {
  return getJSON("/api/projects");
}

export async function switchProject(projectName: string): Promise<{ success: boolean; message: string }> {
  const res = await fetch(`/api/projects/${encodeURIComponent(projectName)}/switch`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`切换失败 ${res.status}`);
  return res.json();
}

export function getActiveProject(): Promise<any> {
  return getJSON("/api/projects/active");
}

export function getPapers(): Promise<{ papers: any[] }> {
  return getJSON("/api/papers");
}

export async function uploadPaper(pdfBase64: string, filename: string): Promise<any> {
  const res = await fetch("/api/papers/upload", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pdf: pdfBase64, filename }),
  });
  if (!res.ok) throw new Error(`上传失败 ${res.status}`);
  return res.json();
}

export function getPaperMetadata(paperId: string): Promise<any> {
  return getJSON(`/api/papers/${encodeURIComponent(paperId)}/metadata`);
}

export function getPaperText(paperId: string, maxPages?: number): Promise<{ text: string }> {
  const params = maxPages ? `?max_pages=${maxPages}` : "";
  return getJSON(`/api/papers/${encodeURIComponent(paperId)}/text${params}`);
}

export function getPaperFileUrl(paperId: string): string {
  return `/api/papers/${encodeURIComponent(paperId)}/file`;
}

export function getRuns(): Promise<{ runs: RunListEntry[] }> {
  return getJSON("/api/runs");
}
export function getRun(key: string): Promise<RunRecord> {
  return getJSON("/api/run?key=" + encodeURIComponent(key));
}

export interface ChatCallbacks {
  onStart?: (agentId: string, runKey: string) => void;
  onDelta?: (text: string) => void;
  onStep?: (step: RunStep) => void;
  onError?: (text: string) => void;
  onDone?: (status?: RunStatus) => void;
}

// 通过本地代理 /api/chat 发送消息，解析 SSE 流（代理已桥接 Gateway）
export async function sendChat(
  agentId: string,
  message: string,
  cb: ChatCallbacks,
  sessionKey?: string,
): Promise<void> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent: agentId, message, sessionKey }),
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
        if (ev.type === "start") cb.onStart?.(ev.agent, ev.runKey);
        else if (ev.type === "delta") cb.onDelta?.(ev.text || "");
        else if (ev.type === "step") cb.onStep?.(ev.step);
        else if (ev.type === "error") cb.onError?.(ev.text || "error");
        else if (ev.type === "done") cb.onDone?.(ev.status);
      } catch {
        /* 忽略无法解析的分片 */
      }
    }
  }
  cb.onDone?.();
}
