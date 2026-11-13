# paper-repro-verifier · 使用与方法说明

> 一个可被 Agent 调用的论文复现/方法验证 Skill。它不替你「知道」论文结论，
> 而是把**读实际文件 → 登记材料 → 记录环境 → 复原参数 → 真跑 → 带容差比较 → 归因 → 分级结论**
> 固化成可核验的结构化产物。所有数值来自实际输入，无预制答案。

## 1. 用途与适用条件

**适用**：论文复现、超参核对、指标验算、训练日志与表格对齐、"结果对不上"的归因、
科研阅读问答需要回到原文页码/段落定位、复现报告生成、材料缺失审计。

**不适用**：需要联网拉取论文/数据集、需要原作者私有权重或受限数据、湿实验、
纯开放式文献综述。这些情况 Skill 会登记 `missing`/`restricted` 而非伪造。

**依赖**：Python ≥ 3.9，核心流程仅标准库。可选增强：`pypdf`/`pdfplumber`/`PyMuPDF`
（PDF 文本层）、`matplotlib` + `Pillow`（复现图与并排对比）、外部 `pdftotext`、`tesseract`（扫描件）。
任一缺失都会自动降级并在产物中写明，**不会静默失败**。

## 2. 目录

```
SKILL.md                     入口：工作流、铁律、契约、异常处理
README.md                    本说明
LIMITS.md                    边界、失败模式、自查清单、维护
scripts/
  repro_cli.py               主驱动：run / locate / execute / finalize
  common.py                  原子写、状态机、证据定位、run_log
  pdf_text.py                逐页文本抽取（4 后端降级）+ 证据索引
  materials.py               材料发现、角色分类、sha256、缺失登记
  environment.py             环境快照 + 论文声明版本比对
  params.py                  三源参数对齐 → 可执行参数表
  compare.py                 容差优先的结果比较 + 复现图
  attribution.py             差异归因决策树 + 分级结论
  report.py                  证据链接的复现报告
templates/                   人可读空模板（清单/参数/对比/归因/报告）
examples/                    最小调用示例（明确标注为示例，非真实案例结果）
```

## 3. 完整调用步骤（Agent 侧）

```bash
S=<skill 安装目录>            # 平台上为 /skills/weekly-skill

# ① 自动审计：只读实际文件，产出七环节骨架
python $S/scripts/repro_cli.py run \
  --case /input/case.json --task /input/task.md \
  --work /app/work --out /app/output

# ② 查证据（页码/行号），用于回答 task.md 并写 sources
python $S/scripts/repro_cli.py locate --out /app/output --q "RMSE"
python $S/scripts/repro_cli.py locate --out /app/output --q "learning rate"

# ③ 真跑项目自带的复现/评价命令（留 exit_code / stdout / stderr），
#    并把它的数值结果 JSON 写进 --out，供第 ④ 步采信
python $S/scripts/repro_cli.py execute --out /app/output \
  --cmd "python reproduce.py --config configs/paper.yaml --out /app/output/result_check.json"

# ④ 再跑一次 run（同参数；result.json 不会被覆盖）：读取第 ③ 步的结果，
#    把真实数值比较放进 comparison.json.external_verified 并置于结论主位
python $S/scripts/repro_cli.py run \
  --case /input/case.json --task /input/task.md \
  --work /app/work --out /app/output

# ⑤ 按 task.md 填 /app/output/result.json（契约字段 + case_id + 证据 + 不确定性）
# ⑥ 收尾校验
python $S/scripts/repro_cli.py finalize --case /input/case.json --out /app/output
```

`--inputs` 可显式指定材料目录（可多个）；`--work/--out` 可改。
`run` **不会覆盖**已存在的 `result.json`，可重复运行改进而不丢答案。
`finalize` 写 `validation.json`，列出缺失契约字段与需补充说明的项，返回码 2 表示需处理。

离线/本机自测等价形式：

```bash
python scripts/repro_cli.py run \
  --case examples/minimal_case.json --inputs examples/fixture \
  --work /tmp/repro-work --out /tmp/repro-out
```

## 4. 输入输出

**输入**（全部按实际文件读取，不假设内容）：
- `case.json`：读取 `case_id/id` 与 `output_contract`。契约支持三种形态：字段名数组、
  字段名→说明的字典（含 JSON Schema 的 `properties`）、逗号分隔字符串。字段名**动态生成，不硬编码**。
- `task.md`：任务说明（由 Agent 阅读）。
- 材料目录：PDF/TEX/MD/TXT/CSV/JSON/YAML/PY/LOG/图片，自动分类。

**输出**（均在 `--out`）：

| 文件 | 内容 |
|---|---|
| `result.json` | 按契约生成的答案骨架，`finalize` 校验 |
| `materials_ledger.json` | 文件级清单 + **必需材料类别缺失登记** |
| `environment_snapshot.json` / `environment_check.json` | 可重建环境 + 与论文声明的版本差异 |
| `parameters.json` | 三源对齐的可执行参数表（含冲突与证据定位） |
| `execution.json` | 真实命令、退出码、stdout/stderr |
| `comparison.json` | 事前容差的对比表（PASS/FAIL/UNVERIFIABLE/NEEDS_REVIEW），含 `external_verified` 真实脚本数值结果 |
| `attribution.json` | 可核验归因条目 + 分级结论 |
| `repro_report.md` | 带证据链接的人读报告 |
| `figures/` | 复现图、与论文原图并排对比、`figure_status.json` |
| `repro/evidence_index.json` | 逐页逐行文本，供 `locate` 反查 |
| `repro/run_log.jsonl` | 每步输入/耗时/状态/错误的追加式轨迹 |
| `repro/index.md` | 产物导航 |
| `validation.json` | `finalize` 的校验结论 |

## 5. 关键方法（三个增益点）

1. **三源参数表**：分别抽取论文正文/附录（`paper_values`）、配置文件（`config_values`）、
   代码默认（`code_defaults`），按别名归一；每项给 `source_class`
   （`paper_explicit` / `code_inferred` / `self_set` / `unresolved`）、页码/行号证据、
   `conflict` 标记与裁决策略。**冲突绝不自动消解**，必须由 Agent 带证据裁决并写进 `change_records`。
2. **容差前置比较**：`comparison.json` 先写 `tolerance`（默认绝对 0.01 + 相对 0.01，可按指标覆盖），
   再比较。落在容差内记 `numerical_variation`，超出记 `methodological_difference_candidate`
   并进入归因；不允许事后放宽容差。数值指标优先于图像相似度。
3. **可核验归因**：每个 FAIL 展开为 环境→数据→实现→描述不足→随机性 五类假设，
   每类写明所需证据与证伪/证实动作，结论必须由 Agent 填 `resolution` 和证据定位。
4. **优先采信真实运行**：`external_verified` 收录项目验证脚本实际产出的带容差比较。
   正则启发式只自动判定口径明确的**聚合声明**；叙述型/逐折声明保留原文证据但标
   `NEEDS_REVIEW`，明显噪声标 `DISCARDED`。这样"结果对不上"不会被正则误判伪造，
   也不会把无法判断的项写成事实。

材料分类按**扩展名定大类、文件名只在类内细化**：`verify_paper_recompute.py` 永远是代码、
`xxx_5fold_rmse.pdf` 永远是插图，不会被误当成论文声明来源。

## 6. 状态与异常处理

四态：`success`（全部完成可核验）/ `partial`（部分完成，必须写 `limits`）/
`failed`（运行或依赖失败）/ `indeterminate`（材料不足无法判断）。
`uncertainty` 的 `kind` 区分 `not_reported` / `unreadable` / `conflict` / `missing_input`，
**分别**登记，不合并成"数据不足"。

| 情况 | 产物中的表现 |
|---|---|
| 代码/仓库不可访问 | `materials_ledger.checklist` 标 `missing` + 接管方式 |
| 依赖缺失/冲突 | `environment_check.json` 记录实际版本；`execution.json` 留 stderr |
| PDF 无文本层 | `evidence_index.json` 标 `needs_ocr`，保留图片路径，建议 OCR 命令 |
| 数据需申请 | 标 `restricted`，禁止用合成数据冒充 |
| 评价脚本缺失 | 相关指标 `UNVERIFIABLE`，只报能自算的口径 |
| 结果对不上 | 进 `attribution.json`，结论降级 `partially_reproduced` |

## 7. 自查方法（提交/复核前）

```bash
python -m py_compile scripts/*.py
python scripts/repro_cli.py run --case examples/minimal_case.json \
  --inputs examples/fixture --work /tmp/w --out /tmp/o
python scripts/repro_cli.py finalize --case examples/minimal_case.json --out /tmp/o
```

自查要点：① `validation.json` 为 PASS；② `result.json` 含全部契约字段与 `case_id`；
③ 每个 `missing`/`UNVERIFIABLE` 都在 `uncertainty` 有对应项；④ 每个关键结论有 `sources` 定位；
⑤ `execution.json` 若 `status=not_run`，报告中不得出现"已复现"字样；
⑥ 图产物有真实 PNG；⑦ `run_log.jsonl` 无未解释的 `error` 步骤。

## 8. 版本与维护

v1.0.0，Apache-2.0。改动脚本请同步更新 `LIMITS.md` 的已知边界与 `templates/` 结构。
`examples/` 中的数值为**接口示例**，明确标注，不是任何论文的真实结果，也不作为正式测试案例。
