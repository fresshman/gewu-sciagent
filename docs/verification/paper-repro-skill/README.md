# 论文复现 Skill · 本地实跑证据（2026-11-13）

这份快照是用 `gewu/skills/paper_repro_verifier/`（比赛提交包兼格物能力真源）
在**格物自己的真实论文材料**上跑出来的结果，用于他人复核。所有本机绝对路径已脱敏。

## 输入（真实材料）

| 材料 | 路径 |
|---|---|
| 论文正文 PDF + LaTeX 源 | `docs/paper/coal_report/main.pdf` / `main.tex` |
| 论文插图（5 折 RMSE 柱状） | `output/figures/coal_5fold_rmse_20261028-121844.png` |
| 逐折与聚合指标 | `output/documents/coal_report/metrics_recomputed.json`（gitignore，脱敏快照在本目录） |
| 独立重算脚本 | `scripts/verify_paper_recompute.py` |

## 复现命令（仓库根）

```bash
PY=.venv/Scripts/python.exe
S=gewu/skills/paper_repro_verifier/scripts/repro_cli.py
CASE=output/scratch/bohrium_challenge/coal_case/case.json   # 本地演练用，非平台案例
OUT=/tmp/repro-out

python $S run --case $CASE \
  --inputs docs/paper/coal_report output/documents/coal_report output/figures scripts/verify_paper_recompute.py \
  --work /tmp/repro-work --out $OUT
python $S execute --out $OUT \
  --cmd "python scripts/verify_paper_recompute.py --metrics output/documents/coal_report/metrics_recomputed.json --tex docs/paper/coal_report/main.tex --out $OUT/recompute_check.json"
python $S run --case $CASE --inputs ... --work /tmp/repro-work --out $OUT   # 采信 external_verified
python $S finalize --case $CASE --out $OUT
```

不依赖 `output/` 的最小复核（用本目录脱敏快照）：

```bash
python scripts/verify_paper_recompute.py \
  --metrics docs/verification/paper-repro-skill/metrics_snapshot.json \
  --tex docs/paper/coal_report/main.tex --out /tmp/recompute_check.json
```

## 结果

| 项 | 结果 |
|---|---|
| 独立重算 vs 论文表格/摘要声明 | **7/7 PASS**（事前容差：绝对 0.01） |
| 论文聚合块 vs 重算值 | **6/6 PASS**（1e-9） |
| 启发式自动比较 | 1 条聚合声明 PASS；10 条叙述/逐折声明 `NEEDS_REVIEW`；3 条解析噪声 `DISCARDED`；**0 假 FAIL** |
| 材料清单 | paper / code / data / evaluation 找到；dependency / license / parameter_source 显式登记缺失 |
| 并排图 | 左论文原图、右按 `hybrid` 分支重画的逐折 RMSE，数值一致（约 219/245/222/220/167） |
| 分级结论 | **`partially_reproduced`** |
| `finalize` | `verdict=PASS`，0 problems |

## 诚信边界（必须随这份证据一起读）

1. **数值可复算 ≠ 训练可复现**。原始 LIBS 光谱与模型权重留在本人本机的外部项目、
   不入库不上云（`docs/paper/README.md` 已声明）。第三方只能从落盘逐折指标重算聚合值，
   不能独立重跑训练。因此结论是「部分复现」，不是「已复现」。
2. 本演练用的是**格物自己的论文**，不是平台 3 个固定案例；`result.json` 是本地
   演练产物快照，不是任何比赛的正式答案或预制答案。
3. 逐折表格行与叙述型声明保留原文证据但标 `NEEDS_REVIEW`，口径需人工确认，
   未被自动判成 PASS/FAIL。解析噪声（如 `RMSE / MAE / R2` 里的 `2`）显式剔除。
4. 平台当前提供的书生模型别名与 README 的模型分工描述有偏差，本演练不依赖模型分工。

## 文件清单

| 文件 | 内容 |
|---|---|
| `metrics_snapshot.json` | 脱敏后的逐折/聚合指标（去掉 `source_root` 绝对路径） |
| `recompute_check.json` | 独立重算 + 带容差比较的原始输出 |
| `result.json` | 按 `output_contract` 填写的演练答案（含证据定位、不确定性、变更记录） |
| `repro_report.md` | 七环节证据链接报告 |
| `figures/comparison_paper_vs_repro.png` | 论文原图 vs 复现图并排对比 |

回归测试：`tests/test_paper_repro_verifier.py`（纳入 `verify_all` 的 pytest 项）。
