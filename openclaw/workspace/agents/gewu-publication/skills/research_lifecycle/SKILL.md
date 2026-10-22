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
