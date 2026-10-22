---
name: spectrum-preprocess
description: 对 LIBS / 通用科学谱图做基线校正、归一化与特征峰提取，供下游建模使用。
type: spectral
steps:
  - 载入谱图（波长-强度序列或图像）。
  - 基线校正：去除连续背景（如 ALS 非对称最小二乘）。
  - 归一化：按总强度或峰值归一，消除激光能量波动。
  - 特征峰提取：定位元素特征峰（如 C 247.8nm、H 656.2nm）。
  - 输出结构化特征（peaks / 归一化强度向量），交给 sci_compute 或 mil_model。
tools: [sci_data.parse_figure, sci_compute.pls_regress]
model: 书生大模型 InternVL（谱图解析）+ Intern-S1（流程规划）
---
# 谱图预处理技能（Spectrum Preprocess）

将原始谱图转为可用于回归/分类的干净特征。命中赛题「Agent Skills 技能化封装」加分项。
