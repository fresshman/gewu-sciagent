---
name: paper-repro-verifier
description: "论文复现与方法验证：把真实论文/附录/代码/日志的材料定位、环境快照、三源参数复原、带容差结果比较、差异归因和分级复现结论固化为可核验的结构化产物。当任务要求复现论文数值、核对超参、解释结果对不上、生成复现报告或为阅读结论保留原文证据时使用。不产出预制答案，只读实际输入文件。"
version: "1.0.0"
license: "Apache-2.0"
---

# 论文复现与方法验证（Reproduction Audit）

## 0. 第一动作：先跑自动审计，再读材料

**任何**论文复现/方法验证/科研阅读任务，第一步固定执行（不要先凭题目文字猜内容）：

```bash
python <SKILL_DIR>/scripts/repro_cli.py run \
  --case /input/case.json --task /input/task.md \
  --work /app/work --out /app/output
```

`<SKILL_DIR>` 是本 SKILL.md 所在目录（平台上是 `/skills/weekly-skill`）。若 `/input/case.json`
不存在，改用 `--inputs <实际材料目录>`；若路径不同，用 `--case/--task/--out` 指向真实位置。
本机或离线自测时等价写法：

```bash
python scripts/repro_cli.py run --inputs <材料目录> --work ./work --out ./output
```

这条命令**只读实际文件**，自动产出七环节的结构化骨架与可执行审计（详见 §3）。
它不会凭标签补造数据、不会写死任何论文答案、不会把"没找到"伪装成"没有"。

跑完后读 `/app/output/repro/index.md`（人读的导航）与 `evidence_index.json`（页码级证据），
再按 `task.md` 完成实际的解析/问答/翻译/提取。**然后真跑项目的复现/评价命令**，
并把它的数值结果 JSON 写进 `--out`：

```bash
python <SKILL_DIR>/scripts/repro_cli.py execute --out /app/output \
  --cmd "python reproduce.py --config configs/paper.yaml --out /app/output/result_check.json"
```

**真跑之后再跑一次 `run`**（同参数即可，`result.json` 不会被覆盖）：Skill 会读取该结果 JSON，
把「实际验证脚本产出的带容差比较」放进 `comparison.json.external_verified` 并置于结论主位。
正则启发式比较只作兜底，且**只自动判定口径明确的聚合声明**；叙述型/逐折声明保留证据但标
`NEEDS_REVIEW`，解析噪声标 `DISCARDED`——不制造假 FAIL。

收尾**必须执行**：

```bash
python <SKILL_DIR>/scripts/repro_cli.py finalize --case /input/case.json --out /app/output
```

`finalize` 校验 `result.json` 是否含全部 `output_contract` 字段与 `case_id`，
补齐诚实状态并输出校验报告；缺字段会明确列出，不会悄悄放过。

## 1. 四条铁律（违反即该次结果不可核验）

1. **只认实际文件**。`case.json`、`task.md`、PDF 正文、代码、日志是事实依据。
   不得依据领域标签、题目名称、文件名或常识推断论文内容；PDF 无预抽取答案层，必须自己解析。
2. **缺失要登记，不跳过**。任何未提供/未报告/读不出/无法判断的项，写入对应产物的
   `missing` 或 `uncertainty` 列表并说明原因与可人工接管位置；**绝不补造软件状态或科学数据**。
3. **结论必须带定位**。每个关键结论附 `evidence`：
   `{source: 文件相对路径, page: 页码, section: 段落/表/图号, quote: 原文片段, line: 行号}` 中
   实际可得的字段。没有定位的结论标为 `unverifiable`，不写成事实。
4. **冲突显式化**。正文、附录、代码默认值、运行日志彼此矛盾时，登记为 `conflict`，
   列出三方取值、各自定位和裁决依据；不得静默选一个。

## 2. 七环节工作流（脚本自动 + Agent 只做需要理解的部分）

| # | 环节 | 脚本产出 | Agent 必须补的 |
|---|---|---|---|
| 1 | 材料定位 | `materials_ledger.json` | 确认哪些是论文正文/附录/仓库代码；标 `role` |
| 2 | 环境配置 | `environment_snapshot.json` | 比对论文声明的依赖/硬件/种子，登记不一致 |
| 3 | 参数复原 | `parameters.json` | 裁决三源冲突，标 `source_class` 依据 |
| 4 | 代码运行 | `execution.json` + `run_log.jsonl` | 真跑复现命令；失败如实记 `exit_code`/`stderr` |
| 5 | 结果比较 | `comparison.json` + `figures/` | 从论文表/图读出声明值；填 `declared` |
| 6 | 差异归因 | `attribution.json` | 判断是数值波动还是方法性差异，选归因类别 |
| 7 | 复现结论 | `repro_report.md` + `result.json` | 给分级结论及依据 |

评分关注「找得齐 / 跑得对 / 对得上 / 讲得清」。**至少把 3、5、6 做实**：
`parameters.json` 的三源对齐表、`comparison.json` 的带容差对比表、
`attribution.json` 的可核验归因条目，是本 Skill 相对基础 Agent 的主要增益。

## 3. 自动审计做什么（无需 Agent 干预）

- 递归发现材料（PDF/TEX/MD/CSV/JSON/YAML/PY/LOG/图片），登记 `path/size/sha256/role/version_hint/missing`，
  生成可勾选清单；**找不到**的必需材料类别（代码、数据、依赖、许可证、评价脚本）显式列出。
- 抽取 PDF 逐页文本（`pdftotext` → `pypdf` → `pdfplumber` → 纯文本降级），
  生成 `evidence_index.json`，支持按关键词反查页码，供 Agent 写证据定位。
- 记录环境快照：Python/平台/CPU/已装依赖版本/随机数种子/关键环境变量名（不记值）/磁盘，
  输出可在他机重建的 `environment_snapshot.json` + `rebuild.sh` 片段。
- 从论文文本、配置文件、代码 `default=` / `argparse` / 字典常量中抽候选参数，
  按别名归一后生成三源对齐表，预填 `source_class` 候选与 `conflict` 标记。
- 生成带 `tolerance` 的对比表骨架、`decision_tree` 归因模板、报告骨架、
  以及 `result.json` 骨架（**按 `case.json` 的 `output_contract` 动态生成，不硬编码字段**）。
- **按扩展名定大类、名称只在类内细化**地分类材料：`verify_paper_recompute.py` 是代码，
  单页 `xxx_5fold_rmse.pdf` 是插图，都不会被误当成论文正文或结果表。
- 扫描 `--out` 与材料中由**真实运行**产出的数值比较 JSON（`comparison.rows`），
  收进 `external_verified` 并优先采信；没有就明确写"未发现"，不假装跑过。
- 全程写 `run_log.jsonl`：每个步骤的输入、耗时、状态、失败原因，可独立复核。

## 4. `result.json` 契约（写答案时严格遵守）

```json
{
  "case_id": "<照抄 case.json 的 case_id/id>",
  "<output_contract 的每个字段>": "<按 task.md 作答；无法判断写 null 并在 uncertainty 说明>",
  "status": "success | partial | failed | indeterminate",
  "sources": [{"path": "...", "page": 3, "section": "§4.2", "quote": "..."}],
  "uncertainty": [{"item": "...", "reason": "...", "kind": "not_reported|unreadable|conflict|missing_input"}],
  "change_records": [{"step": "...", "before": "...", "after": "...", "why": "..."}],
  "reproduction": {"grade": "reproduced|partially_reproduced|not_reproducible|indeterminate", "basis": "..."}
}
```

规则：
- `output_contract` 可能是字段名数组、字段→说明的字典或 JSON Schema；脚本三种都认。
- **不得删除或改名**契约字段；`finalize` 会逐个核对。
- 状态四态语义：`success` 全部完成且可核验；`partial` 部分完成（必须写 `limits`）；
  `failed` 运行/依赖失败；`indeterminate` 材料不足无法判断。
- 材料冲突、未报告、无法判断**分别**记录，不要合并成一句"数据不足"。
- `figures/` 下若有 Office/图/示意图产物，同时留一份真实渲染的 PNG/PDF 供人工查看。

## 5. 差异归因决策树（结果对不上时按序排除，每条都要留证据）

1. `environment`：依赖/驱动/硬件/BLAS 线程/精度不同 → 查 `environment_snapshot.json` 与论文声明。
2. `data`：数据版本、划分、预处理、单位、泄漏 → 查数据版本与切分脚本；数据需申请则标 `missing`。
3. `implementation`：代码默认值 ≠ 论文超参、聚合口径（总体/样本 std）、指标定义不同 → 查 `parameters.json`。
4. `specification`：论文描述不足、表图未报数值、公式与文字矛盾 → 引原文定位，标 `unverifiable`。
5. `stochastic`：随机种子/折划分/初始化波动 → 多次运行给区间，落容差内记 `numerical_variation`。

区分 **数值波动**（落在事前声明的容差内）与 **方法性差异**（口径/实现不同，不能靠容差抹平）。
容差必须在比较**之前**声明并写进 `comparison.json` 的 `tolerance`，不许事后放宽。

## 6. 异常处理（识别并如实报告，不假装成功）

| 情况 | 处置 |
|---|---|
| 仓库/代码不可访问 | `materials_ledger.json` 标 `missing`，`status=partial`，说明可接管位置 |
| 依赖冲突/缺失 | 记录实际版本与报错，`execution.json` 写 `exit_code`/`stderr`，不伪造运行结果 |
| 算力不足 / 超时 | 保存已完成的部分结果与 `run_log.jsonl`，标 `partial` 并给出最小复现子集 |
| 数据需申请 / 未公开 | 登记 `missing` + `reason=restricted`，禁止用合成数据冒充真实数据 |
| 评价脚本缺失 | 标 `unverifiable`，只报告能自算的指标及算法说明 |
| 结果对不上 | 走 §5 决策树，给可核验归因条目，结论降级为 `partially_reproduced` |
| PDF 无文本层（扫描件） | 尝试 OCR 工具；不可用则标 `unverifiable` 并保留图片路径 |

## 7. 边界与资源

- 只用 Python 标准库完成核心流程；`numpy/matplotlib/Pillow` 为可选增强，缺失时自动降级。
- 不联网、不下载论文、不写入输入目录；所有产物落在 `--out`。
- 不在仓库中保存密钥；环境快照只记变量名与版本，不记 token 值。
- 本 Skill **不提供**预制答案、正式测试案例或白板；`examples/` 仅为接口示例，不冒充正式结果。
- 详细方法与限制见 `README.md`、`LIMITS.md`；模板见 `templates/`；最小调用示例见 `examples/`。
