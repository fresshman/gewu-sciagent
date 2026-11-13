---
name: paper-repro-verifier
description: 论文复现与方法验证：材料定位、环境快照、三源参数复原、带容差结果比较、差异归因与分级复现结论，产出可核验的结构化产物。用于复现数值、核对超参、解释结果对不上、为结论保留原文证据。
type: verification
---

# 论文复现与方法验证（OpenClaw 运行时入口）

**唯一真源在仓库根**：`gewu/skills/paper_repro_verifier/`。
本目录下不放脚本副本；下列命令一律**先切到仓库根**（含 `.git/` 的目录）再执行，
避免各 agent 工作目录不同导致路径失效。完整 `SKILL.md` / `README.md` / `LIMITS.md`
在真源目录，Agent 应读取真源的 `SKILL.md` 获取完整工作流与铁律。

## 何时触发

- 阶段 3 复现：需要把论文表格/曲线与实跑指标对齐并解释差异；
- 阶段 4 改进：需要核对超参来源（正文 / 附录 / 代码默认）与冲突；
- 阶段 5 撰写 / 阶段 7 沉淀：需要为结论保留页码、行号、字段定位；
- 遇到「结果对不上」「数据需申请」「评价脚本缺失」等异常需如实分级时。

## 命令（仓库根执行）

```bash
S=gewu/skills/paper_repro_verifier/scripts/repro_cli.py

python $S run      --case <case.json> --inputs <材料目录...> --work /tmp/work --out /tmp/out
python $S locate   --out /tmp/out --q "RMSE"
python $S execute  --out /tmp/out --cmd "<真实复现命令，结果写 /tmp/out/*check*.json>"
python $S run      --case <case.json> --inputs <材料目录...> --work /tmp/work --out /tmp/out   # 采信 external_verified
python $S finalize --case <case.json> --out /tmp/out
```

`run` 不覆盖已有 `result.json`，可反复运行改进。`finalize` 校验 `output_contract`
全部字段与 `case_id`，输出 `validation.json`。

## 产物（写入 --out）

`materials_ledger.json`（含缺失登记）、`environment_snapshot.json`、
`environment_check.json`、`parameters.json`（三源对齐 + 冲突）、
`execution.json`（真实退出码）、`comparison.json`（事前容差 + `external_verified`）、
`attribution.json`（五类可核验归因 + 分级结论）、`repro_report.md`、
`figures/`（复现图与论文原图并排）、`repro/evidence_index.json`（页码级证据）、
`repro/run_log.jsonl`、`result.json`。

## 铁律（与真源一致）

只认实际文件；缺失分别登记不补造；结论必须带定位；容差比较前声明；
`execution.status=not_run` 时不得写「已复现」；不得用合成数据冒充真实数据。

本项目实跑证据：`docs/verification/paper-repro-skill/`（7/7 数值 PASS，
`partially_reproduced` 因原始数据未公开）。
