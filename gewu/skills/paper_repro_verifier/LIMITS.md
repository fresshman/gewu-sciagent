# 边界、失败模式与维护

## 1. 明确的能力边界

| 边界 | 说明 |
|---|---|
| 不做语义推理 | 正则只从**实际文本**抽候选参数/指标；它不"理解"论文，所有行都带 `quote` 与页码行号供人工复核。抽取可能有误报漏报，故每行标 `agent_action` 要求确认。 |
| 不自动裁决冲突 | 正文/附录/代码默认值冲突时 `resolved=null`、`conflict=true`，等 Agent 带证据裁决。静默取一个值正是本 Skill 要消除的失败模式。 |
| 不伪造运行结果 | 未调用 `execute` 时 `execution.status=not_run`、退出码 `null`。报告不会声称已复现。 |
| 不补造数据 | 数据/代码/评价脚本缺失时登记 `missing` 并给接管方式；严禁用合成数据顶替真实数据。 |
| 不联网 | 不下载论文、不访问仓库、不写入输入目录。 |
| 不记密钥 | 环境快照只记环境变量**名**与包版本，token/密码值一律不写。 |

## 2. 与「基础 Agent 直接做」的边界（创新点价值）

基础 Agent 通常能读 PDF 并回答问题，但容易：跳过缺失材料、把代码默认当论文超参、
事后放宽误差、把"对不上"写成一句"环境差异"、结论不带页码。

本 Skill 增加的是**结构性约束与可复核产物**：
1. 三源参数表把"参数从哪来"变成显式字段（`source_class` + 证据定位 + 冲突标记）；
2. 容差在比较**之前**落盘，杜绝事后调参；
3. FAIL 强制展开为五类可证伪假设并留 `resolution`；
4. `run_log.jsonl` + `sha256` + `case_id` 使他人可独立重跑复算。

这些是**流程与证据结构**上的增益，不声称提升模型本身的科学推理能力，
也不替代原作者代码、物理实验或全量数据集复现。

## 3. 已知技术限制

- PDF 表格跨行/跨页、双栏混排时 `pdftotext -layout` 的行序可能错乱；
  此时应结合 `pdf-render-tool` 看版面，并在 `uncertainty` 记 `unreadable`。
- 扫描件无文本层时四个后端都失败 → `needs_ocr`；OCR 未安装则相关结论必须标 `unverifiable`。
- 正则抽取的声明值**不是**最终判定依据。只有 `scope=aggregate` 的声明会自动比较，
  且只配聚合型运行输出；叙述型/逐折声明标 `NEEDS_REVIEW` 并保留原文证据，
  小整数噪声标 `DISCARDED`。真正的数值结论应来自 `external_verified`（项目验证脚本实跑结果）。
  这是刻意保守：宁可标「需人工确认」，也不制造假 FAIL。
- `external_verified` 只识别含 `comparison.rows`（或顶层 `rows`）且每行有
  `declared` + `recomputed`/`observed` + `verdict` 的 JSON；自定义格式需转成该形状，
  或由 Agent 把结果写进 `result.json` 并附证据。
- 自动比较的 `observed_source`/`match_basis` 必须逐行复核后才能引用。
- 参数别名表是通用的，领域特有写法（如 `n_estimators`、`λ`）可能漏抽；
  可在 `params.ALIASES` 扩展，并把改动写进 `change_records`。
- 环境快照只覆盖本机可见状态；容器/集群的调度、隐藏驱动、云端随机性不在其内。
- 图像对比是**辅助**：`comparison_paper_vs_repro.png` 只是并排展示，
  数值判定完全由 `comparison.json` 的容差表决定（不采用 SSIM 计分）。

## 4. 失败模式与处置清单

| 现象 | 原因 | 处置 |
|---|---|---|
| `n_files=0` | `--inputs` 指错或材料在别处 | 显式传 `--inputs`；检查 `materials_ledger.warnings` |
| `evidence_index.documents` 全 `needs_ocr` | PDF 是扫描件且无 PDF 库 | 用 OCR 工具处理；仍失败标 `unverifiable` |
| `comparison.counts.total=0` | 论文/结果里没抽出可配对数值 | 手工从表格读数填 `declared`/`observed` 并保留定位，不删行 |
| 大量 `UNVERIFIABLE` | 未真跑或结果文件不在扫描范围 | 用 `execute` 真跑；确认结果文件后缀被识别 |
| 参数冲突未裁决 | 三源取值不同（预期行为） | 由 Agent 引原文定位裁决，写 `change_records` |
| `finalize` 返回 2 | 契约字段缺失或 case_id 不符 | 按 `validation.json.problems` 逐项补齐 |
| 出图为空 | matplotlib/Pillow 缺失 | 看 `figures/figure_status.json` 的 `note`；不影响数值结论 |

## 5. 自查与质量门

提交或复核前逐条确认（详见 `README.md` §7）：契约完整、`case_id` 一致、
每个缺口都有 `uncertainty`、每个关键结论有 `sources`、`execution` 与结论措辞一致、
图有真实 PNG、`run_log` 无未解释 error。

## 6. 维护

- 新增参数别名 → `scripts/params.py` 的 `ALIASES`，同步本文件 §3。
- 新增指标口径 → `scripts/compare.py` 的 `METRIC_NAMES` 与 `tolerance.overrides`。
- 输出契约形态变化 → `scripts/common.py:contract_fields`。
- 任何改动都要在 `examples/` fixture 上跑一遍 `run` + `finalize`，并把变更写入 `change_records`。
