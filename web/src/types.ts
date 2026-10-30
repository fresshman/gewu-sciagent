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
  runKey?: string;
}

// ── A3: 中间结果落盘 / 执行进度 ──
export type RunStatus = "running" | "success" | "timeout" | "error" | "aborted";

export interface RunStep {
  ts: string;
  type: string;
  detail: string;
  raw: string;
  kind: "tool" | "model" | "ended" | "info" | "raw";
  tool?: string;
  callId?: string;
  phase?: "call" | "result";
  status?: "running" | "ok" | "error";
  result?: string;
  disposition?: string;
  startedTs?: string;
  endedTs?: string;
}

export interface RunRecord {
  key: string;
  agent: string;
  message: string;
  startedAt: number;
  endedAt: number | null;
  status: RunStatus;
  steps: RunStep[];
  raw: string[];
}

export interface RunListEntry {
  key: string;
  agent: string;
  message: string;
  startedAt: number;
  endedAt: number | null;
  status: RunStatus;
  stepCount: number;
}

// ── 右栏「真实案例」数据（由 scripts/export_case_bundle.py 生成本机私有文件） ──
// 数据来自本机真实课题；仓库内无副本，取不到时 available=false。

export interface FoldMetric {
  fold: number;
  n: number;
  rmse: number | null;
  mae: number | null;
  r2: number | null;
}

export interface MetricAgg {
  mean: number;
  std: number;
  std_sample: number;
}

export interface MetricArm {
  per_fold: FoldMetric[];
  summary: { rmse: MetricAgg; mae: MetricAgg; r2: MetricAgg };
  pooled: FoldMetric;
}

export interface CaseMetrics {
  convention: string;
  hybrid: MetricArm;
  plsr_baseline: MetricArm;
  improvement_pct: number;
  scatter: { y_true: number[]; hybrid: number[]; plsr: number[]; unit: string };
}

export interface SpectrumPreview {
  bag_id: string;
  shot: string;
  n_shots: number;
  n_raw: number;
  n_points: number;
  wl_range: [number, number];
  wavelength: number[];
  intensity: number[];
  note: string;
}

export interface CasePaper {
  title: string;
  venue: string;
  year: number;
  doi: string;
  status: string;
  method: string;
  note: string;
}

export interface CaseArtifact {
  name: string;
  rel: string;
  kind: string;
  size_kb: number;
}

export interface CaseBundle {
  available: boolean;
  reason?: string;
  hint?: string;
  generated_at?: string;
  topic?: string;
  metrics?: CaseMetrics;
  spectrum?: SpectrumPreview | null;
  papers?: CasePaper[];
  artifacts?: CaseArtifact[];
}
