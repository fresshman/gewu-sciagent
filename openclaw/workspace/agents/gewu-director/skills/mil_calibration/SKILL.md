---
name: mil-calibration
description: 用多示例学习(MIL, LSE-Pool 聚合)对 LIBS 大颗粒原煤光谱做端到端热值校准与预测。
type: calibration
steps:
  - 将一次采样视为一个 bag，包内多张谱线为 instance。
  - instance 编码器提取各谱线表征。
  - LSE-Pool 端到端聚合为 bag 表征。
  - 回归头输出 bag 级热值（MJ/kg）。
  - 5 折交叉验证 + 消融（有无 LSE-Pool）评估。
tools: [mil_model.predict_calorific_value, sci_compute.cross_validate]
model: 书生大模型 Intern-S1（实验设计/分析）+ OpenVINO 本地推理（mil_model）
---
# MIL 校准技能（MIL Calibration）

端到端多示例学习热值校准。
