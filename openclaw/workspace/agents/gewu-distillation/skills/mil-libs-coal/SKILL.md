---
name: mil-libs-coal
description: MIL+LIBS 大颗粒原煤热值预测的完整课题档案与复现路径——含问题定义、hybrid 推理链、真实复现命令、指标口径陷阱、消融结论与常见坑。
type: case-study
domain: coal-libs
inputs:
  - COAL_PROJECT_ROOT（指向外部 coal-calorific-value 项目，含权重与 LIBS 数据）
  - 或 .coal_project_root 文件（仓库根目录，内容为项目绝对路径）
steps:
  - 确认外部项目根可读、5 折权重与 predictions.json 齐全。
  - 用 coal_infer.py cv-summary 跑真实 5 折推理。
  - 用 scripts/recompute_coal_metrics.py 从 predictions.json 独立重算并与注册表交叉校验。
  - 报告指标时必须声明标准差口径（ddof=0 还是 ddof=1）。
commands:
  - python gewu/mcp/coal_infer.py cv-summary
  - python scripts/recompute_coal_metrics.py --json output/documents/coal_report/metrics_recomputed.json
tools: [mil_model.cv_summary, mil_model.predict_calorific_value, mil_model.list_val_bags, sci_exp.query, sci_compute.cross_validate]
model: 书生大模型 Intern-S2（分析）+ 本地真实推理（mil_model → subprocess → coal_infer.py）
---

# MIL + LIBS 大颗粒原煤热值预测（课题档案技能）

本技能不是"怎么做 MIL"的方法教程（那见 `mil_calibration`），而是**这个课题的完整档案**：
踩过哪些坑、指标该怎么报、哪些数字能直接引用、哪些不能。

## 一、问题定义

- **对象**：大颗粒原煤（煤粉压片），一次采样 = 一个 bag，包内多张 LIBS 谱线 = instance
- **目标**：预测热值（kcal/kg；×0.004184 得 MJ/kg）
- **难点**：大颗粒导致颗粒效应/基质效应显著，单张谱线重复性差；样本量小（70 bag / 5 折 × 14）
- **方案要点**：不替换 PLSR，而是让 MIL 只学 PLSR 的残差 → `hybrid = PLSR + ΔMIL`
  好处是保留 PLSR 的可解释性与稳定性，同时吸收非线性偏差

## 二、真实推理链

```
bag 目录（多张 LIBS 谱 CSV）
  → parse + is_valid_spectrum 过滤
  → 预处理 sg → als → mms（bag 内共享）
  → 袋均谱 → PLSR(n_components=7) → plsr_pred
  → 实例矩阵 → MIL(ResNet1D(base=16)+SupCon → TransMIL_attn → FiLM(plsr_dim=7)) → ΔMIL
  → hybrid(kcal/kg) = plsr_pred + ΔMIL
  → MJ/kg = kcal/kg × 0.004184
```

## 三、复现命令

```bash
# 1) 真实 5 折推理（需 torch 环境；mil_model 会用 GEWU_COAL_PYTHON 或自动探测 coal-torch）
python gewu/mcp/coal_infer.py cv-summary

# 2) 从逐 bag 预测值独立重算，并与注册表交叉校验（13 项）
python scripts/recompute_coal_metrics.py \
  --json output/documents/coal_report/metrics_recomputed.json --strict
```

期望：`mean_rmse=214.5699`、`std=25.7094`、与 `summary.json` 差 `1.1e-05`、交叉校验 13/13 PASS。

## 四、关键指标（引用时必须带口径）

| 指标 | Hybrid | PLSR 基线 |
|---|---|---|
| 5 折平均 RMSE (kcal/kg) | **214.5699** | 233.9521 |
| 总体标准差 ddof=0 | **25.7094** | 17.9494 |
| 样本标准差 ddof=1 | 28.7440 | 20.0681 |
| 平均 MAE (kcal/kg) | 177.78 | 198.39 |
| 平均 R²（逐折平均） | 0.8963 | 0.8803 |
| 合并 OOF RMSE (n=70) | 216.1046 | 234.6397 |
| 合并 OOF R² | 0.9204 | 0.9061 |

改进幅度：RMSE −19.3822 kcal/kg（−8.28%），5 折方向全部为负。

统计：配对 t(4)=−2.9735, p=0.0410，95% CI [−37.48, −1.28]；
Wilcoxon p=0.0625（n=5 的下限，**不显著**，不可单独作为显著性证据）。

## 五、消融结论（务必带配置口径）

**陷阱**：以下消融在「MSE 损失、无 SupCon、无 FiLM」阶段完成，与最终 214.57（huber + SupCon + TransMIL + FiLM）**不同配置，不可相减比较**。

| 池化策略 | 参数量 | RMSE |
|---|---|---|
| ABMIL(从零) | 8320 | 957.47 |
| MaxPool | 0 | 883.87 |
| ABMIL(冻结) | 8320 | 559.09 |
| MeanPool | 0 | 512.96 |
| LSE(固定 β=0.5) | 0 | 361.00 |
| LSE(可学习 β→0.516) | 1 | **347.55** |

结论：小样本下注意力池化反而最差；LSE 以近零参数取胜；**SE 模块是负收益**（去掉即降 71.84）。
数据来源：外部项目 `coal-mil/scripts/plot_figures.py`（fig7 第 395 行、fig9 第 486 行），
属脚本硬编码值，复现需跑 `compare_hybrid_pools.py`。

## 六、常见坑

1. **`predict_calorific_value` 必须给 `bag_dir`**：单 bag 预测需要该 bag 的谱线目录，不能只给 fold。
   不知道 bag 在哪先用 `list_val_bags(fold)` 取。
2. **别用 `reproduce_fold` 做长任务**：逐 bag 真推理易超时（>60s）。用 `cv_summary` 聚合接口，
   或直接读缓存的 `predictions.json`。
3. **标准差口径陷阱**：注册表的 25.7094 是**总体标准差**（ddof=0）。若代码用 numpy 默认 ddof=0 就对得上，
   用 pandas `.std()`（ddof=1）会得到 28.7440，看起来"对不上"其实只是口径不同。
4. **不要合并 venv**：`default` 无 torch 是设计而非缺陷。`mil_model` 用 subprocess 隔离推理，
   推理侧由 `GEWU_COAL_PYTHON` 或自动探测的 `coal-torch` 提供 torch。盲合并会多下 1–2GB。
5. **跨配置比较**：消融数字（347.55）与最终指标（214.57）不同组，任何论文/报告里都必须写清。
6. **数据不出本机**：权重与 LIBS 数据留在外部项目，仓库只存聚合指标与复现脚本。

## 七、相关资产

| 资产 | 路径 |
|---|---|
| 实验注册表（单一数字台账） | `gewu/mcp/registry/coal_mil.json` |
| 指标重算脚本 | `scripts/recompute_coal_metrics.py` |
| 重算结果 | `output/documents/coal_report/metrics_recomputed.json` |
| 论文成稿 | `output/documents/coal_report/main.tex` |
| 五阶段 handoff | `openclaw/workspace/agents/gewu-{improver,writer,publication}/handoff_*.json` |
