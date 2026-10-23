---
name: gewu-review-loop
description: 自主评审循环（用本机书生 intern-s2 当对抗评审）。review→fix→re-review，直到策略通过或达最大轮数。当 improver 改进定稿、或 publication 投稿前自评时使用。
---

# 格物·评审循环（本机书生）

把 ARIS auto-review-loop 的「评分+最小修复+最多 N 轮」工程纪律移植到格物，但
**不依赖 Codex/Gemini 等外部后端**——改用本机 `sheng/intern-s2` 当对抗评审，
符合「本地优先、未发表草稿不出本机」原则。

## 常量
- `MAX_ROUNDS = 4`
- `SCORE_THRESHOLD = 6`（满分 10）
- `POSITIVE_VERDICT = ["ready", "almost"]` — 需 score≥阈值 **且** verdict∈此集才停
- `REVIEWER_MODEL = "sheng/intern-s2"` — 本机书生多模态，可同时看草稿与图
- `REVIEW_DIR = "review-stage/"` — 所有评审产物落这里
- `HUMAN_CHECKPOINT = false` — 默认全自主；改 true 则每轮后暂停等用户

## 循环

### 初始化
- `mkdir -p review-stage`
- 若 `review-stage/REVIEW_STATE.json` 存在且 `status=="in_progress"` 且 24h 内 → 续跑；
  否则新建 `run_id=run_<YYYYMMDD>_<8hex>`，`round=1`。

### Phase A — Review（用 intern-s2 当对抗评审）
把待评审产物（草稿/方法/真实结果路径）交给 `sheng/intern-s2`，对抗式 prompt：
```
你是 NeurIPS/ICML 级别资深 ML 评审。从 artifacts 直接审查（不要轻信作者自述）：
- 草稿/论文：<path>
- 方法/代码：<path(s)>
- 真实结果（原始文件，非摘要）：<path(s)>
- 本轮相对上轮改动：<changed paths>

任务：
1. 给 1–10 分（顶会标准）
2. 列出按严重度排序的关键弱点
3. 每条弱点给出 MINIMUM fix（最小修复动作：实验/分析/重构表述）
4. 明确表态：READY / ALMOST / NOT READY
5.（第 2+ 轮）对照上一轮 REVIEWER_MEMORY，判断担忧是否被真正解决还是被规避
```
intern-s2 若为多模态，可直接把图作为 image_url 一并给入（如预测-真值散点图、
消融柱状图），让它核对「图是否支撑 claim」。

### Phase B — 解析评审
保存 reviewer 原始响应（完整，不摘要）。提取 `score`、`verdict`、`weaknesses:[{fix}]`。

### Phase C — 实现修复（若未停）
按 weaknesses 优先级，用 `sci-compute`/`mil-model` 真实重算、补实验、改表述。
- 优先「重新分析/重构表述」而非新实验；指标须真实算得，禁止凭印象填数。
- 修复后更新 `review-stage/` 下对应产物。

### Phase D — 持久化 + 续跑
向 `review-stage/AUTO_REVIEW.md`（append-only）追加本轮：
```markdown
## Round N (timestamp)
- Score: X/10 — verdict
- Key criticisms: ...
- Actions taken: ...
- Status: continue / stop
```
写 `review-stage/REVIEW_STATE.json`（覆盖写，仅保留最新轮）：run_id/round/score/verdict/status。
`round++` → 回到 Phase A。

### 终止
- score≥阈值 且 verdict∈{ready,almost} → 停，写 `status:"completed"`。
- 达 MAX_ROUNDS 未通过 → 停，列剩余 blocker 与建议。

## 铁律
- 评审原始响应完整留存，绝不静默丢弃弱点以刷分。
- 修复**先于**复评：不空诺「下轮修」，先改再评。
- 指标/结论必须来自 `sci-compute`/`mil-model` 真实计算，禁止编造。
- 诚实包含负面结果；不隐藏弱点。
