---
name: paper-repro-verifier
description: "格物项目的论文复现与方法验证能力：材料定位、环境快照、三源参数复原、带容差结果比较、差异归因、分级复现结论，产出可核验的结构化报告。当需要复现论文数值、核对超参、解释结果对不上、为科研阅读结论保留原文页码证据时使用。"
---

# 论文复现与方法验证（格物项目入口）

**唯一真源**：仓库内 `gewu/skills/paper_repro_verifier/`（`SKILL.md`、`README.md`、
`LIMITS.md`、`scripts/`、`templates/`、`examples/`）。本文件只是 WorkBuddy 项目级入口，
不复制正文，避免双源漂移。完整工作流与铁律请直接读真源的 `SKILL.md`。

该目录同时是 Bohrium「论文复现与方法验证」挑战（`challenge-da62e8d4`）的提交包，
约束已核验：24 个 UTF-8 文本文件、118 KB、无符号链接。

## 调用（在仓库根执行）

```bash
PY=.venv/Scripts/python.exe
S=gewu/skills/paper_repro_verifier/scripts/repro_cli.py

# ① 自动审计：材料清单 / 环境快照 / 三源参数表 / 比较表 / 归因 / 报告骨架
python $S run --case <case.json> --inputs <材料目录...> --work /tmp/work --out /tmp/out

# ② 页码级证据反查
python $S locate --out /tmp/out --q "RMSE"

# ③ 真跑项目复现脚本，结果 JSON 写到 --out
python $S execute --out /tmp/out --cmd "python scripts/verify_paper_recompute.py ... --out /tmp/out/recompute_check.json"

# ④ 再跑一次 run 采信真实数值（external_verified），⑤ 填 result.json，⑥ 收尾
python $S finalize --case <case.json> --out /tmp/out
```

## 本项目已验证的实跑用例

以 `docs/paper/coal_report/`（MIL+LIBS 5 折论文正文与插图）、
`output/documents/coal_report/metrics_recomputed.json`、
`scripts/verify_paper_recompute.py` 为输入：

- 从逐折值独立重算聚合指标，与论文表格/摘要声明值比较 **7/7 PASS**（事前容差 0.01）；
- 论文聚合块交叉校验 **6/6 PASS**（1e-9）；
- 自动生成 `comparison_paper_vs_repro.png`：左为论文原图、右为按 `hybrid` 分支重画的逐折 RMSE；
- 结论 `partially_reproduced`——数值可复算，但原始光谱/权重未公开，第三方无法独立重跑训练。

证据快照见 `docs/verification/paper-repro-skill/`。

## 四条铁律

1. 只认实际文件，不凭题目名称或领域标签猜论文内容；
2. 缺失/未报告/无法判断/材料冲突分别登记，不补造数据；
3. 关键结论必须附页码/行号/表图定位，无定位标 `unverifiable`；
4. 容差在比较前声明，差异归到具体原因，结论可被他人按记录独立复核。
