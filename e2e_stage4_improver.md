# E2E 阶段④：改进/梳理（受控）

你是 gewu-improver。基于 `openclaw/workspace/agents/gewu-reproduction/handoff_3_repro.json`
（真实 5 折 RMSE≈214.57 kcal/kg）做**有界**改进分析（E2E 阶段④）。

## 执行
1. 对照基线（bag-mean+PLSR）与 hybrid（PLSR+MIL 残差），说明 MIL 残差修正带来的增益
   （用 handoff_3 的 per_fold hybrid_rmse vs plsr_rmse 差值论证）。
2. 给出四维评分卡：方法严谨性 / 创新性 / 表达清晰度 / 反方质疑（Devil's Advocate），
   综合给出 `quality_score ∈ [0,1]`。
3. 跑一次失败模式自检（failure_mode_selfcheck 技能，若可用）：7 类失败模式四态裁决，
   仅 CLEAR/NOT APPLICABLE 才放行；SUSPECTED/INSUFFICIENT EVIDENCE 须标注并索要证据。
4. 写 `openclaw/workspace/agents/gewu-improver/handoff_4_improve.json`：
   `{stage:4, stage_name:"改进", status, inputs:[handoff_3路径], outputs:[...],
   gain_analysis, quality_score, failure_audit:{verdict}, next:"writer", next_input:"handoff_4_improve.json"}`

## 纪律
- 不重跑重推理（baseline 指标已来自 handoff_3 真实值）；工具调用 ~6 次以内。
- 超时前必须落盘 handoff_4。
