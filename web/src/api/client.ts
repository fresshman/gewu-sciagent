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

export function getPaperNotes(paperId: string): Promise<{ notes: string; path?: string; updated?: string }> {
  return getJSON(`/api/papers/${encodeURIComponent(paperId)}/notes`);
}

export async function savePaperNotes(paperId: string, notes: string): Promise<{ success: boolean; path: string }> {
  const res = await fetch(`/api/papers/${encodeURIComponent(paperId)}/notes`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ notes }),
  });
  if (!res.ok) {
    let msg = `保存失败 (${res.status})`;
    try { msg = (await res.json()).error || msg; } catch { /* 非 JSON 错误体 */ }
    throw new Error(msg);
  }
  return res.json();
}

// 送复现：后端落盘 repro_request handoff，返回给复现员的指令文本（前端拿去走 /api/chat 长任务通道）。
export async function createReproduceHandoff(
  paperId: string,
  summary?: string
): Promise<{ success: boolean; handoffPath: string; instruction: string; stageActivated: boolean }> {
  const res = await fetch(`/api/papers/${encodeURIComponent(paperId)}/reproduce`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ summary: summary || "" }),
  });
  if (!res.ok) {
    let msg = `送复现失败 (${res.status})`;
    try { msg = (await res.json()).error || msg; } catch { /* 非 JSON 错误体 */ }
    throw new Error(msg);
  }
  return res.json();
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

export interface PaperAiCallbacks {
  onDelta?: (text: string) => void;
  onError?: (text: string) => void;
  onDone?: () => void;
}

// 通用一次性 SSE 桥（/api/papers/ai 与 /api/translate 共用事件协议）
async function postSse(path: string, payload: unknown, cb: PaperAiCallbacks): Promise<void> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let msg = `服务异常 (${res.status})`;
    try {
      const err = await res.json();
      msg = err.error || msg;
    } catch { /* 非 JSON 错误体，用默认文案 */ }
    cb.onError?.(msg);
    cb.onDone?.();
    return;
  }
  if (!res.body) { cb.onError?.("无响应流"); cb.onDone?.(); return; }
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
        if (ev.type === "delta") cb.onDelta?.(ev.text || "");
        else if (ev.type === "error") cb.onError?.(ev.text || "error");
        else if (ev.type === "done") cb.onDone?.();
      } catch {
        /* 忽略无法解析的分片 */
      }
    }
  }
}

// 论文 AI 摘要/问答：走代理 /api/papers/ai（服务端提取全文并桥接 Gateway），SSE 流式回传
export function askPaperAi(
  paperId: string,
  mode: "summary" | "qa",
  question: string,
  cb: PaperAiCallbacks,
): Promise<void> {
  return postSse("/api/papers/ai", { paperId, mode, question }, cb);
}

// 划词/段落翻译：选中文本 → /api/translate → SSE 流式回传译文
export function translateText(text: string, cb: PaperAiCallbacks): Promise<void> {
  return postSse("/api/translate", { text }, cb);
}
