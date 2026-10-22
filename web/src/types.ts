export interface Agent {
  id: string;
  name: string;
  role: string;
  color: string;
  desc: string;
}

export type StageStatus = "done" | "active" | "todo";

export interface Stage {
  id: string;
  name: string;
  status: StageStatus;
  agent: string;
  desc: string;
}

export interface ModelOption {
  id: string;
  name: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  agentId?: string;
  text: string;
  ts: number;
  streaming?: boolean;
  error?: boolean;
}
