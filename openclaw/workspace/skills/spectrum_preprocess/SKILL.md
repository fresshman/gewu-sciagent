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
model: 书生·InternVL3.5-241B-A28B（谱图读图，sheng/internvl3.5-241b-a28b）+ 书生·Intern-S1（流程规划）
---
# 谱图预处理技能（Spectrum Preprocess）

将原始谱图转为可用于回归/分类的干净特征。

## `sci_data.parse_figure` 的输入输出契约（实测，2026-11-04）

真调 `sheng/internvl3.5-241b-a28b`（`temperature=0`，图以内联 base64 传入），
把一张图读成结构化 JSON：`modality / title / x_axis / y_axis / series / peaks /
key_numbers / text_in_figure / unreadable / confidence`。

- **前置**：Key 必须落在 `mcp.servers.sci-data.env.INTERN_API_KEY` 里。
  只在 shell 里 `export` **到不了** MCP 子进程（openclaw 给 stdio 子进程的是
  15 键环境白名单）。生成方式：
  `python scripts/bootstrap_openclaw_config.py --intern-api-key sk-xxx --write`。
- **失败是显式的**：`missing_key / file_not_found / too_large / timeout /
  http_error / network / bad_json / empty_response / unparsable` 都会返回
  `status` + `hint`，且返回体里**没有** `figure`/`modality`。看到非 `ok` 就当作
  "这张图没读到"，不要拿空结构往下算。
- **读数只算估读**：对 5 峰真值谱图实测，峰位取整到 50/100 的倍数，最大偏差
  **6.6 nm**（RMS 4.36 nm），相对强度最大偏差 0.07；模型会把 `估读` 写进
  `peaks[].label_in_figure`。
- **禁止用常识补峰位**：上面那一步"定位元素特征峰（C 247.8 / H 656.2）"是
  **领域知识**，只能用于对照校验，绝不能反过来填进读数。实测 3 次运行
  **幻觉峰为 0**（没有从元素表里补出图外的峰），这是本工具能进流水线的唯一理由。
- **`confidence` 不可信**：真实论文图上模型把 `L-Risk` 读成 `Z-Risk`、双 y 轴
  合并成一根，`confidence` 仍是 `high`。所以落结论前必须做二次对照——
  与同页文本层/原图核对，或换 `sheng/intern-s2` 读原页再比一次。
- 一次调用墙钟 18–35 s，整页图可达 4900+ tokens；默认超时上限 180 s
  （`GEWU_VL_TIMEOUT_S`，最高 480 s，必须留在 sci-data 600 s 客户端闸门之下）。

完整取证记录：`docs/verification/2026-11-04-parse-figure-vision.md`。
