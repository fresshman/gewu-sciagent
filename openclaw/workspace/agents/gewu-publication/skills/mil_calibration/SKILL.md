---
name: mil-calibration
description: 用多示例学习(MIL, TransMIL 注意力聚合)对 LIBS 大颗粒原煤光谱做端到端热值校准与预测，真实推理并可复现 5 折交叉验证。
type: calibration
steps:
  - 将一次采样视为一个 bag，包内多张谱线为 instance。
  - 谱线级预处理：sg 平滑 → als 基线校正 → mms 归一化。
  - 实例编码器(ResNet1D)提取各谱线表征。
  - TransMIL 注意力聚合为 bag 表征，FiLM 用 PLSR 得分做特征调制。
  - 回归头输出 MIL 残差，与 PLSR 基线相加得 hybrid 热值(kcal/kg → MJ/kg)。
  - 5 折交叉验证 + 消融评估。
tools: [mil_model.predict_calorific_value, mil_model.list_val_bags, mil_model.reproduce_fold, mil_model.cv_summary, sci_compute.cross_validate]
model: 书生大模型 Intern-S2（实验设计/分析）+ 本地真实推理（mil_model → coal_infer.py）
---
# MIL 校准技能（MIL Calibration）

端到端多示例学习热值校准，**真实推理**（非 demo 输出）。

## 真实推理链路（严格对齐训练脚本，保证可复现）

```
bag 目录(多张 LIBS 谱 CSV)
  → parse + is_valid_spectrum 过滤
  → 预处理 sg → als → mms
  → 袋均谱 → PLSR(n_components=7)  → plsr_pred
  → 实例矩阵 → MIL(ResNet1D + TransMIL_attn + FiLM) → 残差 → mil_res
  → hybrid(kcal/kg) = plsr_pred + mil_res
  → MJ/kg = kcal/kg × 0.004184
```

## 工具用法

| 工具 | 用途 |
|---|---|
| `mil_model.list_val_bags(fold)` | 列出该折验证集 bag，供挑选真实样本 |
| `mil_model.predict_calorific_value(bag_dir, fold)` | **单 bag 真实预测**，返回 PLSR / MIL 残差 / hybrid（kcal/kg 与 MJ/kg） |
| `mil_model.reproduce_fold(fold)` | 复现该折全部验证集预测，返回 RMSE / MAE / R² 与逐 bag 明细 |
| `mil_model.cv_summary()` | 5 折指标汇总，并与原项目官方 summary.json 交叉校验 |

## 铁律

1. **禁止编造预测值**：热值必须来自 `mil_model` 真实前向推理，不得凭印象填数。
2. **模型与数据不出本机**：权重(`.pt`)与 LIBS 数据始终留在 `COAL_PROJECT_ROOT`
   指向的外部未发表项目，格物只按路径读取，不复制、不入库、不上云。
3. **结果可追溯**：报告指标时须注明 fold 编号与是否经 `cv_summary` 交叉校验。
4. **单位显式标注**：kcal/kg 与 MJ/kg 必须写清楚，禁止混用。
