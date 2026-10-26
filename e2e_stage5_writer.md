# E2E 阶段⑤：写论文（受控·有界）

你是 gewu-writer。基于 `openclaw/workspace/agents/gewu-improver/handoff_4_improve.json`
（含真实 RMSE 与 quality_score）与前面各 handoff，写**有界**论文草稿（E2E 阶段⑤）。

## 执行
1. 写 `openclaw/workspace/agents/gewu-writer/manuscript.md`：结构化草稿，含
   标题 / 摘要 / 引言 / 方法（MIL+LSE-Pool+LIBS 大颗粒原煤）/ 实验（真实 5 折 RMSE≈214.57 kcal/kg，
   引用 handoff_3 的 per_fold 数字）/ 结果 / 结论 / 参考文献（≥3 篇，须来自 handoff_2 已 D1 核验文献）。
2. 用 `mcp__sci-plot__*` 真实出 **1 张图**：预测值 vs 真实值散点图（用 handoff_3 的
   per_fold 或 summary 数字构造少量代表性点；若无可读原始点，则用各折 RMSE 柱状图），
   存到 `openclaw/workspace/agents/gewu-writer/fig_predict_vs_true.png`（同时 PDF 矢量）。
3. D3 引用完整性：用 `mcp__sci-verify__lint_citations` 校验 `\cite` 键均来自已核验文献。
4. 写 `handoff_5_draft.json`：`{stage:5, stage_name:"写论文", status, inputs:[handoff_4路径,...],
   outputs:[manuscript.md, 图路径], d3_status, next:"publication", next_input:"handoff_5_draft.json"}`

## 纪律
- 草稿**有界**：每节 3–6 句，不写冗长；总长度控制在可快速审阅。
- 图中数值必须来自真实 handoff_3 指标，禁止编造；无原始散点则用各折 RMSE 柱状图。
- 工具调用 ~8 次以内；超时前落盘 handoff_5。
