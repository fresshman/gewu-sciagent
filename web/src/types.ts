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
  /** 这条回复自己的执行记录（按消息归属，而不是全局一份 runSteps） */
  steps?: RunStep[];
  runStatus?: RunStatus;
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

/* ============ 论文库 / 写作台（/api/library、/api/writing） ============ */

/** 一行论文。kind=own 是本人稿子（来自 main.tex），ext 是外部文献。 */
export interface LibraryItem {
  id: string;
  kind: "own" | "ext";
  label: string;
  title: string;
  src: string;
  year: string;
  identifier: string;
  tags: string[];
  /** 本机是否有 PDF；没有就是 null，不假设 */
  pdf: { bytes: number; pages: number } | null;
  check: { t: string; cls: "b-ok" | "b-warn" | "b-mut"; sub: string };
  rel: { note: number; repro: number; cite: number };
  /** 推进度 0–100，五段流水线等分 */
  prog: number;
  /** 五段命中情况，顺序同 LibraryResponse.progressSteps */
  steps: boolean[];
  lines: string[];
  tex?: string;
  claimsCount?: number;
}

export interface LibraryResponse {
  available: boolean;
  project?: string;
  reason?: string;
  hint?: string;
  items: LibraryItem[];
  summary: {
    total: number;
    /** 只统计外部文献 */
    verified: number;
    /** 有 claims.json 的自己稿子数；列表页不判定，只报「有东西待核」 */
    ownWithClaims: number;
    /** 这些稿子加起来多少条声明（核查台才会给结论） */
    ownClaimCount: number;
    withNotes: number;
    withRepro: number;
    missingPdf: number;
  };
  progressSteps: string[];
}

/** 写作台大纲节点。level=0 章节、1 小节；leaves 是该节下的表/图/引用。 */
export interface WritingNode {
  level: 0 | 1;
  num: string;
  title: string;
  /** 源文件行号（1-based） */
  line: number;
  leaves: WritingLeaf[];
}

export interface WritingLeaf {
  kind: "tbl" | "fig" | "cite";
  num: number;
  label: string;
  text: string;
  line: number;
  /** 环境起始行（\begin{figure} 那行）；表/图才有 */
  envLine?: number;
  /** \includegraphics 里的文件名，用来和图纸台账对上 */
  file?: string;
  /** tex 里的 \label{fig:*}；没有就是空串（本稿全部为空） */
  texLabel?: string;
  /** 图纸化：内容寻址 id（fig-<sha 前 8>）。同一张图在任何目录、任何文件名下都是它 */
  fig_id?: string | null;
  /** 这张图散落的副本数 / 目录数（来自台账） */
  fig_copies?: number;
  fig_dirs?: number;
  /** 旁文件出处是否在场（true/false，不猜） */
  fig_provenance?: boolean;
  /** 同一张图被正文多处引用时，列出全部图号（如「图 1、图 3」）；单处引用不写 */
  fig_reused?: string;
}

/** 图纸化注记的统计：正文图谱侧有多少 fig leaf 挂上了内容 id */
export interface FigGraph {
  leaves: number;
  figures: number;
  reusedIds: string[];
}

export interface WritingResponse {
  available: boolean;
  project?: string;
  reason?: string;
  hint?: string;
  tex?: {
    path: string;
    bytes: number;
    sha256: string;
    lines: number;
    title: string;
    date: string;
    mtime: string;
    source: string;
  };
  outline?: WritingNode[];
  /** 图纸化注记统计（annotateFigLeaves 产出）；旧响应没有这个字段 */
  fig_graph?: FigGraph;
  assets?: {
    claims: { n: number; withSource: number; path: string };
    equations: { n: number };
    refs: {
      n: number;
      verified: number;
      verdict: string;
      checkedAt: string;
      hallucinationRate: number | null;
      path: string;
      items: { id: string; title: string; identifier: string; status: string; method: string }[];
    };
    tables: number;
    figures: number;
    bibitems: number;
  };
  pdf?: { path: string; bytes: number } | null;
  /** 项目目录下同一稿子的另一份副本；same=false 表示内容不同 */
  duplicates?: { path: string; bytes: number; sha256: string; same: boolean; lines: number; tables: number }[];
  projectDraft?: { path: string; bytes: number; sha256: string } | null;
}

/** 顶层视图：对话工作台 / 单篇 PDF 阅读器 / 论文库与写作台 */
export type ViewMode = "chat" | "papers" | "library";

/* ============ 图纸台账（/api/writing/figures） ============ */

/** 一张图 = 一条。副本按内容 sha256 合并，id 是内容寻址的 fig-<sha8>。 */
export interface FigureItem {
  fig_id: string;
  /** 文件名去掉扩展名，正文 \includegraphics 按它对齐 */
  base: string;
  sha256: string;
  masterFormat: "pdf" | "png";
  bytes: number;
  formats: Partial<Record<"pdf" | "png", { rel: string; bytes: number; sha256: string }>>;
  /** 逐个文件的副本（同一目录可能 pdf + png 各一份） */
  copies: { rel: string; format: string; bytes: number; dir: string }[];
  /** 按目录归并后的位置 */
  locations: { dir: string; formats: string[]; bytes: number }[];
  copyCount: number;
  dirCount: number;
  /** 出图时写的 .meta.json；没有就是 null，不编造 */
  provenance: FigureProvenance | null;
  provenancePath: string;
  refs: {
    num: number;
    caption: string;
    line: number;
    sectionNum: string;
    sectionTitle: string;
    texLabel: string;
  }[];
  referenced: boolean;
  concerns: { level: "warn" | "info"; code: string; text: string }[];
}

export interface FigureProvenance {
  schema: number;
  created_at: string;
  stem: string;
  /** 画它的工具函数名，如 plot_bar */
  tool: string;
  fig_id: string;
  args: Record<string, { kind: string; value?: unknown; shape?: number[]; n?: number; sha256?: string; min?: unknown; max?: unknown; values?: string[] }>;
  draw: {
    axes: number | null;
    series: { kind: string; n?: number; sha256?: string; min?: unknown; max?: unknown; axis?: number; shape?: number[] }[];
    labels?: { titles?: string[]; x?: string[]; y?: string[] };
    digest: string | null;
  };
  files: Record<string, { name: string; bytes: number; sha256: string }>;
  dpi: number;
  gewu: { version: string | null; git: string | null };
  errors?: string[];
}

export interface FigureIndexResponse {
  available: boolean;
  project?: string;
  reason?: string;
  hint?: string;
  texPath?: string;
  dirs?: { dir: string; label: string; exists: boolean; files: number }[];
  figures: FigureItem[];
  summary: {
    total: number;
    files: number;
    referenced: number;
    unreferenced: number;
    withProvenance: number;
    multiCopy: number;
    rowsBeforeMerge: number;
  } | null;
}

/* ============ 声明核查（/api/writing/claims，D2 引擎投影） ============ */

/**
 * 引擎给的状态。不要在前端「合并」成两三种：
 * 「数字漂移」和「指针写错」是两种完全不同的毛病，改法也不一样。
 */
export type ClaimStatus =
  | "grounded"
  | "drift"
  | "paper_grounded"
  | "paper_unverified"
  | "unknown_experiment"
  | "metric_required"
  | "metric_not_in_registry"
  | "metric_not_scalar"
  | "metric_not_list"
  | "metric_index_out_of_range"
  | "metric_not_numeric"
  | "bad_value"
  | "bad_source";

export interface ClaimRow {
  status: ClaimStatus;
  text: string;
  source: string;
  metric?: string;
  /** claim.metric 没命中、改用 source 锚点时的原值 */
  claim_metric?: string;
  experiment_id?: string;
  domain?: string;
  value?: number | string;
  truth?: number;
  abs_diff?: number;
  tolerance?: number;
  reproducibility?: string;
  /** legacy-anchor = 用了 `#` 锚点写法（能解析但不是规范写法） */
  source_style?: "canonical" | "legacy-anchor";
  reason?: string;
  note?: string;
  /** 列表型 metric 的长度 / 越界时的实际长度 */
  length?: number;
  available_metrics?: string[];
  failed_experiments?: string[];
  tried?: string[];
}

export interface ClaimReport {
  available: boolean;
  project?: string;
  reason?: string;
  hint?: string;
  path?: string;
  n_claims?: number;
  n_grounded?: number;
  n_drift?: number;
  n_unverifiable?: number;
  /** source 用了 `#` 锚点写法的条数 */
  n_legacy_source?: number;
  n_with_source?: number;
  all_grounded?: boolean;
  counts?: Record<string, number>;
  verified_papers?: string[];
  claims?: ClaimRow[];
}
