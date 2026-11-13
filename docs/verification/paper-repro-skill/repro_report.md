# 论文复现与方法验证 · 可核验报告

生成时间：2026-11-13T05:57:08+00:00　|　由 `paper-repro-verifier` 自动汇总（数值均来自实际文件）

**复现结论：`partially_reproduced`**

> 依据：1/1 metrics agree, 0 exceed tolerance, 0 unverifiable; 0 parameter conflicts; see attribution items；实际运行验证脚本的数值比较 7 PASS / 0 FAIL（优先采信），启发式比较仅作兜底

---

## 1. 材料定位（找得齐）

扫描到 20 个文件。必需材料类别核查：

| 类别 | 状态 | 证据文件 |
|---|---|---|
| paper | found | docs/paper/coal_report/main.pdf, docs/paper/coal_report/main.tex, output/documents/coal_report/main.pdf |
| code_or_script | found | scripts/verify_paper_recompute.py |
| data | found | output/documents/coal_report/metrics_recomputed.json |
| dependency | missing | — |
| license | missing | — |
| parameter_source | missing | — |
| evaluation | found | scripts/verify_paper_recompute.py |

**显式缺失登记**（不得用合成数据替代）：
- `dependency`：no file of this category found in the provided inputs；接管方式：ask the operator for this artifact, or record it as restricted/unpublished; do not substitute synthetic data
- `license`：no file of this category found in the provided inputs；接管方式：ask the operator for this artifact, or record it as restricted/unpublished; do not substitute synthetic data
- `parameter_source`：no file of this category found in the provided inputs；接管方式：ask the operator for this artifact, or record it as restricted/unpublished; do not substitute synthetic data

## 2. 环境检查（跑得对）

- Python `3.13.9` / CPython；Windows 10 / AMD64；CPU 32
- 检出依赖 8 个（完整版本见 `environment_snapshot.json`）
- GPU：ok　|　种子：unset
- 与论文声明比对：0 条声明，版本不一致 0，缺失 0（明细见 `environment_check.json`）

## 3. 参数复原（三源对齐）

共 3 个候选参数，其中 **0 个冲突**。

| 参数 | 论文值 | 代码默认 | 采用值 | 来源类别 | 冲突 | 证据 |
|---|---|---|---|---|---|---|
| `alpha` | 0.05 | — | 0.05 | `paper_explicit` |  | docs/paper/coal_report/main.tex:p.1:l.150 |
| `beta` | 0.5 | — | 0.5 | `paper_explicit` |  | docs/paper/coal_report/main.tex:p.1:l.176 |
| `seed` | 42 | — | 42 | `paper_explicit` |  | docs/paper/coal_report/main.pdf:p.2:l.19 |

裁决规则：paper_explicit > supplement/config > code default > self_set. Conflicts are NEVER auto-resolved. Tolerance must be declared before comparison.

## 4. 代码运行

状态：`ok`　|　命令：`".venv/Scripts/python.exe" scripts/verify_paper_recompute.py --metrics output/documents/coal_report/metrics_recomputed.json --tex docs/paper/coal_report/main.tex --out output/scratch/bohrium_challenge/coal_out/recompute_check.json`　|　退出码：0

Actual subprocess result; nothing here is simulated.

## 5. 结果比较（对得上，容差事前声明）

容差：绝对 `0.01` + 相对 `0.01`（比较前写入 `comparison.json`）。共 1 项：PASS 1 / FAIL 0 / UNVERIFIABLE 0；另有 10 条叙述/逐折声明标 NEEDS_REVIEW（保留证据，需人工确认口径），3 条判为解析噪声已剔除。

### 5.1 实际验证脚本的数值比较（优先采信）

以下数值来自**真实运行**的验证脚本，优先于正则启发式比较：

| 来源 | 条目 | PASS | FAIL |
|---|---:|---:|---:|
| `output/scratch/bohrium_challenge/coal_out/recompute_check.json`（仓库相对路径） | 7 | 7 | 0 |

| 指标 | 论文声明 | 重算值 | 判定 | 定位 |
|---|---|---|---|---|
| `plsr.mean_rmse` | 233.952 | 233.952 | PASS | docs/paper/coal_report/main.tex:l.122:5-fold summary table |
| `hybrid.mean_rmse` | 214.57 | 214.57 | PASS | docs/paper/coal_report/main.tex:l.122:5-fold summary table |
| `delta_rmse` | -19.3822 | -19.3822 | PASS | docs/paper/coal_report/main.tex:l.122:5-fold summary table |
| `plsr.mean_r2` | 0.8803 | 0.880325 | PASS | docs/paper/coal_report/main.tex:l.122:5-fold summary table |
| `hybrid.mean_r2` | 0.8963 | 0.896267 | PASS | docs/paper/coal_report/main.tex:l.122:5-fold summary table |
| `hybrid.mean_rmse_abstract` | 214.57 | 214.57 | PASS | docs/paper/coal_report/main.tex:l.21:abstract |
| `hybrid.std_rmse_pop_abstract` | 25.71 | 25.7094 | PASS | docs/paper/coal_report/main.tex:l.21:abstract |

### 5.2 启发式聚合比较（兜底）


| 指标 | 论文声明 | 复现实测 | 绝对差 | 容差 | 判定 | 论文定位 |
|---|---|---|---|---|---|---|
| `rmse` | 214.57 | 214.57 | 8.85347e-05 | 2.1557 | PASS | docs/paper/coal_report/main.pdf:p.1:l.10 |

复现图与论文原图对比（均为仓库相对路径）：`output/scratch/bohrium_challenge/coal_out/figures/repro_rmse_by_fold.png`、`repro_mae_by_fold.png`、`repro_r2_by_fold.png`、`comparison_paper_vs_repro.png`（同一目录；`output/` 已被 .gitignore 排除，随附快照见本目录 `figures/`）。

出图说明：left = paper original (`output/figures/coal_5fold_rmse_20261028-121844.png`), right = regenerated per-fold RMSE from branch `hybrid` (`.../coal_out/figures/repro_rmse_by_fold.png`); dashed line = recomputed mean, label shows mean ± population std

## 6. 差异归因（讲得清）

按 环境 → 数据 → 实现 → 描述不足 → 随机性 次序排除；每条需填 `resolution` 与证据。


## 7. 结论与不确定性

- 分级：**partially_reproduced**；依据：1/1 metrics agree, 0 exceed tolerance, 0 unverifiable; 0 parameter conflicts; see attribution items；实际运行验证脚本的数值比较 7 PASS / 0 FAIL（优先采信），启发式比较仅作兜底
- 数值波动仅在事前声明容差内成立；方法性差异必须单列，不得靠放宽容差抹平。
- 未报告 / 无法判断 / 材料冲突需分别写入 `result.json` 的 `uncertainty`。

## 8. 输出契约与复核路径

`result.json` 需含字段：answer, evidence, uncertainty, status, reproduction_grade（来源：list:output_contract），并附 `case_id` / `status` / `sources` / `uncertainty` / `change_records`。

复核顺序：`materials_ledger.json` → `environment_snapshot.json` → `parameters.json` → `execution.json` → `comparison.json` → `attribution.json` → `repro/run_log.jsonl` → 本报告。

> 本报告由脚本从实际文件生成；凡标「—」「unverifiable」「missing」处均为真实缺口，不是省略。
