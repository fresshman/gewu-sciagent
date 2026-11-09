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

// 合并 OOF 口径：把 5 折预测并起来统一算，无逐折结构
export interface PooledMetric {
  n: number | null;
  rmse: number | null;
  r2: number | null;
}

export interface MetricArm {
  per_fold: FoldMetric[];
  summary: { rmse: MetricAgg; mae: MetricAgg; r2: MetricAgg };
  pooled: PooledMetric;
}

// 逐折配对检验：t 检验与 Wilcoxon 结论可能不一致，必须同时展示
export interface PairedTest {
  available: boolean;
  test?: string;
  t: number | null;
  df: number | null;
  p: number | null;
  mean_diff: number | null;
  ci95?: [number, number] | null;
  wilcoxon_p?: number | null;
  note?: string;
}

export interface AblationItem {
  id: string;
  label: string;
  rmse: number;
}

// 消融结果：与最终配置不同组，caveat 必填，防止跨配置直接相减
export interface CaseAblation {
  status: string;
  caveat: string;
  pooling: AblationItem[];
  path: AblationItem[];
  /** 组件级消融（第三组，基准为最终配置本机重训）；与上面两组不可相减 */
  component?: AblationItem[];
  component_caveat?: string;
  source?: string;
}

export interface RefsSummary {
  verdict: string | null;
  hallucination_rate: number | null;
  n_papers: number;
  checked_at?: string;
  tool?: string;
}

export interface CaseMetrics {
  convention: string;
  primary_convention?: string;
  hybrid: MetricArm;
  plsr_baseline: MetricArm;
  /** 逐折均值口径（论文正文口径） */
  improvement_pct: number;
  /** 合并 OOF 口径，与上一项不同，必须分开标注 */
  improvement_pct_pooled?: number | null;
  improvement_basis?: string;
  paired_test?: PairedTest;
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
  key?: string;
  title: string;
  venue: string;
  year: number | null;
  doi: string;
  arxiv?: string;
  status: string;
  method: string;
  note?: string;
}

export interface CaseArtifact {
  name: string;
  rel: string;
  kind: string;
  size_kb: number;
  scope?: "repo" | "external";
}

export interface CaseBundle {
  available: boolean;
  mode?: "local_recompute" | "repo_snapshot";
  mode_label?: string;
  reason?: string;
  hint?: string;
  generated_at?: string;
  topic?: string;
  provenance?: Record<string, string | null>;
  metrics?: CaseMetrics;
  ablation?: CaseAblation | null;
  references_summary?: RefsSummary | null;
  spectrum?: SpectrumPreview | null;
  papers?: CasePaper[];
  artifacts?: CaseArtifact[];
}
