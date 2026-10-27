---
name: research-lifecycle
description: 科研全生命周期 7 阶段工作流（定方向→读论文找idea→复现→改进→写论文→发表追踪→沉淀），含"不达标回退复现"的迭代循环。当格物接到科研目标时使用。
---
# 科研生命周期工作流

本技能为 Director 提供 7 阶段编排蓝图与迭代循环规则。

## 阶段顺序
1. 定方向（director）：问题 / 假设 / 路线
2. 读论文找 idea（ideation）：gap + 候选改进
3. 复现（reproduction）：基线指标
4. 改进（improver）：消融 / 对比 + 质量分
5. 写论文（writer）：草稿 + Notebook
6. 发表追踪（publication）：选刊 / 投稿 / 引用
7. 沉淀（distillation）：Skill + Memory

## 迭代循环
- improver 产出 `quality_score ∈ [0,1]`。
- 若 `quality_score < 0.8`：director 重新 spawn `reproduction`（调整方法/超参），最多 3 轮。
- 超过上限则取最佳结果进入 writer。

## 状态传递
各阶段产出写入 `workspace/` 文件；子智能体以 A2A announce 向 director 回传摘要。
大对象（数据 / 权重）留在 MCP / Python 侧，只跨边界传路径 / ID。

## 阶段间 handoff schema（强化状态传递）
每阶段产出写为 `handoff_<stage>.json`，下游按 schema 消费，避免上下文丢失：
`{stage, inputs:[paths], outputs:[paths], artifacts:[{type,path}], metrics:{}, next, status}`

## 失败降级落盘铁律（fail-degrade-handoff）★ 最高优先级之一
**任何阶段，无论以何种方式结束（正常完成 / 超时 / 工具报错 / 子智能体无响应 / 进程被 kill），都必须在自身工作区写出一份 `handoff_<stage>.json`，绝不允许"空回复"或"只回一句失败"就结束。**
这是编排层的兜底：下游 agent / director 靠 handoff 续跑，缺失则整条链路断裂。本轮已踩坑——ideation 子会话挂起 28 分钟无 handoff、reproduction 工具失败后空回复，导致后续阶段无法接力。

### 落盘规则
1. **先落盘占位，再进场**：调用任何重工具、进入长循环**之前**，先写一份 `{status:"running"}` 的占位 handoff；阶段推进中持续更新；结束时写最终版。这样即便进程被超时斩杀，磁盘上也有"进度快照"供续跑。
2. **失败也必须写**：超时 / 工具报错时，`status` 取 `"partial"` 或 `"failed"`，并填 `failures` 与 `completed`，不得只留一句失败。
3. **禁止空回复**：若最终只产出"X 失败了"这种话、无配套 handoff，视为**未完成任务**。
4. **不编造**：`completed` / `metrics` 只填**真实已产生**的部分；未得的指标写 `null` + 原因，不得填估算值或占位假数据（反幻觉红线）。
5. **降级也要可续跑**：`next` 写明"建议下一步"（重试 / 换工具 / 人工介入 / 跳过本阶段），让下游或 director 能接手。

### 降级 handoff schema（在基础 schema 上扩展）
```json
{
  "stage": "reproduction",
  "status": "partial | failed",
  "inputs":  ["<上一阶段 handoff 路径>"],
  "outputs": ["<已真实产出的文件，可为空数组>"],
  "artifacts": [{"type": "...", "path": "..."}],
  "metrics": {"rmse_kcal_per_kg": 214.5699, "fold0_rmse": null},
  "completed": ["cv_summary 已真实跑通，5 折 RMSE=214.57 kcal/kg"],
  "failures": [
    {"tool": "mcp__mil-model__reproduce_fold",
     "error": "predict-fold --fold 0 单次推理超出轮次超时预算",
     "impact": "单折逐 bag 复现未产出",
     "mitigation": "改用更长超时专线 / 异步 job；或下游直接用 cv_summary 汇总指标"}
  ],
  "next": "下游可直接消费 cv_summary 汇总指标续跑；如需逐 bag 复现，单独开长超时轮次",
  "degrade_reason": "reproduce_fold 超时，非工具缺陷（直跑可通）"
}
```

### director 责任
director 派发子阶段后，若到时未收到 `handoff_<stage>.json`：
- 先查子智能体工作区是否已有 `status:"running"` 占位 / 进度文件 → 据此决定续跑或重派；
- 子会话疑似挂起（如某 MCP 子进程存活 > 父轮次预算）时，**主动 kill 并重派"有界任务"**，不要干等超时。

---

## 借鉴增强规则（方法论来自 academic-research-skills，已改写为格物实现）

### ① 文献系统筛选协议 · ideation（借鉴 SR-Screener / PRISMA）
- 检索前先确认「纳入/排除标准」清单（研究问题、年份、源、语言）；用 Socratic 式提问澄清边界。
- 用 `mcp__paper-search__search_papers`（sources=`arxiv,semantic,crossref,openalex,pubmed`）多源并发检索去重。
- 两轮筛选：标题/摘要初筛 → 全文精筛；每条独立判断，冲突项上报 director 裁决（**不默认排除**）。
- 产出 `literature_corpus.json`：`{records:[{id,title,doi,relevance,stage}], prisma_counts:{found,screened,excluded,included}}`。

### ② 引用与声明审计 · writer（借鉴 Pipeline / claim-audit）
- 草稿每条 claim 须标注支撑文献 ID（来自 corpus 或 paper-search）。
- 审计：claim 与引用源对齐校验；无支撑 / 过度引申触发 HIGH-WARN，退回补引后才放行。
- 边界：只查 claim–source 对齐，**不证明实验真做**。

### ③ 多视角评分卡 · improver（借鉴 Reviewer）
- 不再只给单一 `quality_score`，改为四维评分卡：方法严谨性 / 创新性 / 表达清晰度 / 反方质疑
  （Devil's Advocate 让步阈值：达阈值才让步，否则持续质疑）。
- 综合分 `< 0.8` → director 回退 `reproduction`（至多 3 轮）；超上限取最佳进入 writer。

### ④ 复现门控与 repro_lock · reproduction（借鉴 Pipeline）
- 须产出基线指标 + 「复现检查清单」（数据 / 环境 / 超参 / 随机种子 / 指标口径）。
- 完整性门控：基线指标达阈值才可进 improver；否则 director 介入。
- 关键方法 / 数据路径写入 `repro_lock.json` 防方法漂移。

### ⑤ 模型分层调度 · director（借鉴 model_tiering）
- 机械任务（检索 / 格式转换 / 提取）→ `intern-s1-mini`；
- 判断 / 写作 / 评审 / 规划 → `intern-s2` 或 `intern-s1-pro`。

### ⑥ 真值隔离 · reproduction / mil_model / sci_compute（借鉴 ground_truth_isolation）
- 真实标签（如煤热值）仅来自实验测定或公开数据集；模型预测**不得回填当真值**。
- 交叉验证测试折严格隔离，不泄露进训练。

### ⑦ 失败模式自检 · reproduction / improver / writer / distillation（借鉴 ai_research_failure_modes）
- 真实 7-mode 清单（Lu 2026 Nature）已固化为**独立可执行技能 `failure_mode_selfcheck`**，部署于 reproduction / improver / writer / distillation 四阶段工作区。
- 每阶段末（尤其复现结束、改进定稿、写稿定稿）对照 7 类失败模式（实现 bug 过审 / 幻觉引用 / 幻觉实验结果 / 走捷径 / bug 包装成新发现 / 方法编造 / 早期 frame-lock）逐条四态裁决（CLEAR / SUSPECTED / INSUFFICIENT EVIDENCE / NOT APPLICABLE）。
- **门控铁律**：SUSPECTED 或 INSUFFICIENT EVIDENCE 必须阻断并索要证据，**绝不静默放行**；仅当全部 CLEAR / NOT APPLICABLE 才放行。
- **distillation 主场**：固化 Skill / 更新 MEMORY.md 前必须跑一遍，并把 `failure_audit_log.json` 随沉淀一并写入（避免把 bug 当经验复利固化）。
