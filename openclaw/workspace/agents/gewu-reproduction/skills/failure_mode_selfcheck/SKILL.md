---
name: failure-mode-selfcheck
description: 科研产出可信性自检（基于 Lu 2026 Nature 7-mode AI 科研失败清单）。在复现结束、改进定稿、写稿定稿、以及沉淀(distillation)固化 Skill/Memory 前，强制逐条运行 7 类失败模式审计；四态裁决（CLEAR/SUSPECTED/INSUFFICIENT EVIDENCE/NOT APPLICABLE），SUSPECTED 或 INSUFFICIENT 必须阻断并索要证据，绝不静默放行。
---
# AI 科研失败模式自检（7-mode Audit）

> 方法论来源：Lu et al. (2026) *Nature* 651:914-919（经 `academic-research-skills` 的 `ai_research_failure_modes.md` 整理；格物仅取其方法论，CC-BY-NC 不复制原文文本）。

本技能是 `research_lifecycle` 规则 ⑦ 的**可执行实体**。它把"失败模式自检"从一句提醒变成可操作的审计流程，主战场在 **distillation（沉淀）**——在把方法固化为 Skill / 写进 MEMORY.md 之前，先确认被沉淀的东西没有科学性问题。

## 何时运行
- 复现（reproduction）结束、基线指标产出后
- 改进（improver）消融 / 对比定稿前
- 写论文（writer）草稿定稿前
- **沉淀（distillation）固化 Skill / 更新 MEMORY.md 前（本技能主场）**
- 任一阶段末若 director 怀疑有科学性风险，随时可触发

## 四态裁决（每条必选其一）
- **CLEAR**：明确无此问题，有证据支撑。
- **SUSPECTED**：发现可疑信号，需进一步核验。
- **INSUFFICIENT EVIDENCE**：无法判断是否存在（证据缺失 / 不可复现）。
- **NOT APPLICABLE**：本阶段 / 本产出不涉及该类（须说明原因）。

## 7 类失败模式与检测信号

| # | Mode | 含义 | 检测问题（对照本阶段产出逐条问） |
|---|---|---|---|
| 1 | Implementation bug passes review | 代码 bug 产出"看似合理但科学错误"的结果 | 有运行日志吗？数值是否异常取整（如正好 0.5）？误差棒在不同条件下竟完全相同？ |
| 2 | Hallucinated citation | 编造 / 错引 / 张冠李戴 | 每条引用能否在 corpus / `paper-search` 结果中找到真实 DOI？claim 与引用源是否对齐（见 research_lifecycle ②）？ |
| 3 | Hallucinated experimental result | 编造未运行的实验 | "X% 提升"有无原始 CSV / 运行日志支撑？声称的 seed 数与运行目录实际 run 数对得上吗？ |
| 4 | Shortcut reliance | 走捷径（虚假特征，如颜色偏置 MNIST 99%） | 有无消融排除最明显 shortcut？消融是否真 ablation 了声称的机制，而非换了个等价 shortcut？ |
| 5 | Bug reframed as insight | bug 被叙事包装成"意外发现" | 是否出现 surprisingly / unexpectedly 等词？首次运行即"惊喜"？是否在新环境 / 新数据复现过？ |
| 6 | Methodology fabrication | 方法部分编造未真正运行的实验 | 方法里每个数字（lr / epoch / 数据量）能否在真实 run config 找到？过去时描述的步骤是否真跑了？ |
| 7 | Frame-lock at early stage | 早期错误承诺（问题 / 方法 / 方向）下游无法回头 | 是否在 hindsight 中改了问题 / 方法？回到 Stage 1 是否会推翻当前结论？ |

## 运行流程
1. **收集待审产出**：本阶段 `handoff_*.json`、新 / 更新 Skill 的 `SKILL.md`、`MEMORY.md` 增量、关键 CSV / 日志路径。
2. **逐条审计**：对 7 类各问检测问题，记录裁决 + 证据 / 疑点。
3. **门控**：若任一非 `NOT APPLICABLE` 项为 `SUSPECTED` 或 `INSUFFICIENT EVIDENCE` → **阻断**，列出具体问题与所需证据，回传 director / 用户确认；**不得静默放行**。
4. **产出日志**：写 `failure_audit_log.json`（见下方 schema）。
5. **放行**：仅当全部 7 项 = `CLEAR` 或 `NOT APPLICABLE`，才允许进入下一阶段 / 固化 Skill。

## 输出 schema · failure_audit_log.json
```
{
  "stage": "distillation | reproduction | improver | writer",
  "run_at": "<ISO8601>",
  "verdicts": [
    {"mode": 1, "name": "Implementation bug passes review",
     "state": "CLEAR | SUSPECTED | INSUFFICIENT EVIDENCE | NOT APPLICABLE",
     "evidence": "...", "action_required": "..."}
    // ... 共 7 条
  ],
  "gate": "PASS | BLOCK",
  "block_reasons": ["..."],
  "next": "..."
}
```

## 与 lifecycle 的衔接
- 复用 `research_lifecycle` ② 引用审计、④ `repro_lock`、⑥ 真值隔离作为本审计的输入证据。
- distillation 阶段必须**把日志随 Skill / Memory 一并沉淀**（复利闭环，避免把 bug 当经验固化）。
- 不要在 `NOT APPLICABLE` 上偷懒：凡涉及实验结论 / 引用 / 方法的产出，Mode 1–6 基本都适用。
