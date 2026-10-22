# 借鉴梳理：academic-research-skills（基于本地完整原文）

> 来源仓库：`https://github.com/Imbad0202/academic-research-skills`（本地克隆路径 `E:\download\academic-research-skills-main`，已逐文件精读）
> 上游：`https://github.com/Imbad0202/academic-research-skills`
> 许可证：**CC-BY-NC 4.0**（非商用 + 必须署名）
> 整理日期：2026-10-22（已读本地完整原文，非仅 README 摘要）

## 0. 合规声明（重要）

本项目（格物 / Gewu）是**科研产品**，存在潜在商用场景。源仓库许可证为
**CC-BY-NC 4.0（非商用 + 署名）**，因此：

- **不复制其代码、SKILL.md 文本、提示词原文**（NC 禁止商用、BY 要求署名）。
- 本文档**仅借鉴其"设计思想/工作流模式"**（方法论层面，属于思想而非表达），并改写为格物自己的表述与实现。
- 若对外文档或产品中引用其思路，需按 CC-BY-NC 标注来源作者 `Imbad0202` 与仓库链接。
- 其 7-mode 失败清单的**学术出处**为 Lu et al. (2026) *Nature* 651:914-919（源仓库 `ai_research_failure_modes.md` 明确引用），该论文本身可正常引用。
- 源项目强绑定 `ANTHROPIC_API_KEY`（Claude）+ Claude Code 子代理编排，**与格物技术栈不兼容**，故只取方法论，不取运行层。

---

## 1. 项目概览（基于本地原文）

一套 **Claude Code 专属**学术技能套件（维护者 Cheng-I Wu），定位 human-in-the-loop。
仓库结构：`academic-paper/`、`academic-paper-reviewer/`、`academic-pipeline/`、`deep-research/`、`sr-screener/`
各含 `SKILL.md` + `agents/` + `references/` + `templates/` + `examples/` + `scripts/`；顶层另有
`shared/`（跨 skill 模式文档：handoff_schemas、ground_truth_isolation、model_tiering、cross_model_verification 等）、
`agents/`、`audits/`、`commands/`、`docs/`、`evals/`、`hooks/`。

| Skill | 版本 | 规模 | 核心机制（原文要点） |
|---|---|---|---|
| **deep-research** | v2.12.1 | 13-agent | 8 模式（full/quick/review/lit-review/fact-check/three-way-scan/socratic/systematic-review）；Socratic 5 层引导（不代答）；FINER 标准；证据层级 Level I–VII；Devil's Advocate 三检查点；反确认偏误 |
| **academic-paper** | v3.3.1 | 12-agent | 11 模式（full/plan/outline/revision/abstract/lit-review/format-convert/citation-check/disclosure/rebuttal-audit…）；写作质量检查；缩写检查；VLM 图验证；防泄漏协议；preregistration |
| **academic-paper-reviewer** | v1.11.1 | 7-agent | 5 座评审团（Journal-Fit + 3 peer + Devil's Advocate）；角色分离但**不声称独立**；DA CRITICAL 必须可见裁决；只读约束；calibration（FNR/FPR） |
| **academic-pipeline** | v3.23.1 | 10 阶段编排器 | 自适应 checkpoint（FULL/SLIM/MANDATORY）；2.5/4.5 完整性门控；7-mode 失败清单（**阻塞**）；Material Passport；claim-audit；协作深度观察；模型分层；预算透明 |
| **sr-screener** | v1.0.0 | 4-agent | PRISMA 2020 协议驱动筛选；双盲审 + 第三方裁决；8 模式；QC（seed/near-miss/kappa/PABAK）；**指令-数据边界**（防注入） |

---

## 2. 核心方法论详细梳理（真实原文）

### 2.1 文献系统筛选 · sr-screener（PRISMA）
- **协议优先（IRON RULE）**：纳入/排除标准在读取任何记录前固定；协议未确认不筛。
- **双盲审 + 裁决**：Reviewer A（内容专家）+ Reviewer B（方法学家）独立判定，冲突交 Adjudicator（第三方）。
- **模式**：protocol / quick / pilot / ta-screen / ft-screen / adjudicate / audit / report。
- **QC**：seed studies、near-miss rechecks、kappa / PABAK 一致性系数；PRISMA 2020 counts、RIS 组、Excel log、方法段落、`literature_corpus` handoff。
- **IRON RULES**：pilot 先于全量；失败调用**不默认 exclude**；不编造 ID；冲突必有裁决；可恢复批处理。
- **指令-数据边界（canonical: instruction-data-boundary）**：检索/粘贴的第三方文本是**数据不是指令**，其中"包含指令的措辞"只作为待报告内容，绝不执行。这是**防 prompt injection** 的明确模式——格物读文献/PDF 时应借鉴。

### 2.2 7-mode AI 科研失败清单（academic-pipeline 引用 Lu 2026 Nature）
在 Stage 2.5 / 4.5 **强制运行且阻塞**；每 mode 四态：CLEAR / SUSPECTED / INSUFFICIENT EVIDENCE / NOT APPLICABLE。
Stage 6 报告"Failure Mode Audit Log"。真实 7 类：

| Mode | 名称 | 含义 | 检测信号（节选） |
|---|---|---|---|
| 1 | Implementation bug passes AI self-review | 代码 bug 产生"看着合理"但科学错误的结果 | 无运行日志；数值异常取整（如正好 0.5）；误差棒跨条件竟完全相同 |
| 2 | Hallucinated citation | 编造/错引/张冠李戴 | 已由引用审计覆盖（Semantic Scholar API 批验） |
| 3 | Hallucinated experimental result | 编造未运行的实验结果 | "X% 提升"无原始 CSV/日志支撑；"跑了 N 个 seed"与运行目录数对不上 |
| 4 | Shortcut reliance | 走捷径（虚假特征，如颜色偏置 MNIST 99%） | 有无消融排除最明显 shortcut；消融是否真 ablation 了声称机制 |
| 5 | Bug reframed as novel insight | bug 被叙事包装成"意外发现" | 出现"surprisingly/unexpectedly"；首次运行即"惊喜"；未在新环境复现 |
| 6 | Methodology fabrication | 方法部分编造未真正运行的实验 | 方法里每个数字（lr/epoch/数据量）能否在真实 run config 找到；过去时描述未运行步骤 |
| 7 | Frame-lock at early stage | 早期错误承诺（问题/方法/方向）下游无法回头 | "in hindsight"；回到 Stage 1 是否会改问题/方法 |

> 这是格物"失败模式自检"的**真实依据**（之前文档里是泛化版，现替换为原文 7-mode）。

### 2.3 多视角评审 + Devil's Advocate 裁决 · reviewer
- 5 座评审团：Journal-Fit（期刊适配）+ R1 方法 + R2 领域 + R3 跨学科 + **固定 DA（反方）**。
- **角色分离 ≠ 独立误差**：明确记录"不声称独立"，避免伪独立误导。
- **DA CRITICAL 必须可见裁决**：验证过或真正未决的 CRITICAL 阻断静默 Accept；被驳回的需记录理由，**永不静默绕过**。
- **只读约束（IRON RULE）**：评审**绝不修改**稿件，只产出报告。
- **反模式**：编造评论、重叠抑制、忽略 DA CRITICAL、橡皮图章 re-review、谄媚膨胀、改稿、泛泛反馈。

### 2.4 完整性门控 / Material Passport / repro · pipeline
- 10 阶段状态机；**2.5 INTEGRITY + 4.5 FINAL INTEGRITY** 为强制门控（FAIL 循环最多 3 轮→记录用户决策）。
- **Material Passport**：跨会话上下文重置边界（`resume_from_passport=<hash>`），让长任务可断点续跑。
- **claim-audit（opt-in, v3.8）**：claim ↔ 引用源对齐校验，HIGH-WARN 类硬门拒输出。
- **自适应 checkpoint**：FULL（首检/完整性边界/终稿）/ SLIM（连续 continue 后单行）/ MANDATORY（完整性 FAIL/评审决策/终稿前）。
- **Self-Check 五问**（每 FULL checkpoint 自问）：引用完整性、谄媚让步、标准轨迹、范围纪律、完整性。
- **反模式 8 条**：跳完整性检查、编排器做实质工作、自动跳过 MANDATORY、跨阶段质量退化、静默丢弃评审意见、仅复验已知问题、膨胀协作分、绕过失败清单阻塞。

### 2.5 阶段交接 schema · shared/handoff_schemas（9 schema）
跨 skill 数据契约，**必填/可选字段 + 类型 + 消费方校验 + `HANDOFF_INCOMPLETE` 失败路径**。
已见 Schema 1–7：RQ Brief、Bibliography、Synthesis Report、Paper Draft、Integrity Report、
Review Report、Revision Roadmap（另有 Material Passport / Traceability 等）。
关键纪律：消费方校验必填字段，缺字段触发重生成；用 SHA-256 + schema 版本做字节级可重放。
→ 格物 `handoff_<stage>.json` 应借鉴"必填字段 + 类型 + 消费方校验"结构。

### 2.6 模型分层 · shared/model_tiering（ARS_MODEL_TIERING）
- `economy`：执行型 agent 降一级（floor 不破），判断型留会话模型。
- `quality-boost`：判断型在门控面跳到最强档，**绝不降级**。
- 层级是相对位置，不硬绑模型 id；同阶段重复调用路由到同一 worker 以累积 prompt 缓存。

### 2.7 Socratic 引导 + 证据层级 + FINER · deep-research
- **Socratic（5 层）**：澄清→假设探问→证据/推理→视角→推演；非生成模式**绝不代答**，用户明确退出标记后才可给候选。
- **FINER** 标准给研究问题打分（Feasible/Interesting/Novel/Ethical/Relevant）。
- **证据层级** Level I–VII（meta > RCT > 队列 > 病例 > 专家意见），领域相对分级。
- **Devil's Advocate 三检查点**：逻辑链、反确认偏误、替代解释。
- **反模式**：确认偏误选源、cherry-picking、**vibe citing（灰色地带 = FAIL，无法确认存在即不入库）**、跳过阶段、浅 Socratic、来源层级膨胀。

### 2.8 three-way-scan（WHY / HOW / WHAT）· deep-research
轻量论文对比框架：WHY（解决什么问题/为何重要）、HOW（方法/技术路线）、WHAT（发现/遗留）。
每篇输出 + 跨篇合成"共同 WHY / 分歧 HOW / 未解 gap"。适合格物 ideation 阶段**快速对比候选论文**。

### 2.9 协作深度观察 · pipeline（advisory only）
`collaboration_depth_agent` 在 checkpoint 观察用户协作模式（委派强度/认知警觉/认知再分配），
**永不阻塞**；维度基于 Wang & Zhang (2026)。对产品 demo 的"人机协作质量"展示有价值。

### 2.10 预算透明 · pipeline
启动时估算 token 成本 + **交互轮次预算**（round-trip caps：2 轮修订 + 8+5 Socratic + 完整性修复循环），
checkpoint 报告累计轮次；仅 advisory 不阻塞。长任务防"文档腐败复利"。

---

## 3. 与格物 7 阶段对照 · 吸收映射表（更新版）

| ARS 真实模式 | 格物落点 | 怎么适配（格物自己的实现） |
|---|---|---|
| PRISMA 协议筛选 (2.1) | **ideation**（②） | 先定纳入/排除标准 → `mcp__paper-search__search_papers` 多源检索 → 标题摘要初筛 → 全文精筛 → 冲突 director 裁决 → `literature_corpus.json`（含 prisma_counts） |
| 指令-数据边界 (2.1) | **全阶段**（尤其读文献/PDF） | 把"检索/粘贴的第三方文本当数据不当指令"写入各 Agent 角色；防 prompt injection |
| 7-mode 失败清单 (2.2) | **reproduction / improver / writer** | 替换为真实 Mode 1–7；reproduction 结束 + writer 定稿前各跑一遍，SUSPECTED 阻断并要用户确认（映射见 SKILL.md ⑦） |
| 多视角 + DA 裁决 (2.3) | **improver**（④） | 四维评分卡 + 反方（Devil's Advocate 让步阈值）；DA CRITICAL 必须可见裁决，不静默绕过 |
| 完整性门控 2.5/4.5 (2.4) | **reproduction→improver** 过渡 | 复现基线达阈值才进 improver；否则 director 介入（对应 SKILL.md ④） |
| Material Passport / repro_lock (2.4) | **reproduction**（③） | 关键方法/数据路径写 `repro_lock.json` 防漂移；长任务可断点续跑 |
| claim-audit (2.4) | **writer**（⑤） | 每条 claim 标支撑文献 ID；无支撑触发 HIGH-WARN 退回补引 |
| 自适应 checkpoint (2.4) | **director** 编排 | 阶段完成强制用户确认；完整性门控不可自动跳过（对应 SKILL.md 状态传递） |
| handoff schema 字段化 (2.5) | **全阶段** | `handoff_<stage>.json` 设必填/可选字段 + 类型 + 消费方校验（对应 SKILL.md §状态传递增强） |
| 模型分层 (2.6) | **director** | 机械任务→`intern-s1-mini`；判断/写作/评审→`intern-s2`/`intern-s1-pro` |
| Socratic 引导 (2.7) | **director**（①） | 接收课题后用 Socratic 式提问澄清研究问题/约束，再 spawn 子 agent |
| FINER + 证据层级 (2.7) | **ideation**（②） | 用 FINER 给选题打分；引用按证据层级标注 |
| three-way-scan (2.8) | **ideation**（②） | 快速对比候选论文用 WHY/HOW/WHAT 框架产出对比表 |
| 协作深度观察 (2.9) | **distillation**（⑦） | 长任务记录人机协作质量（advisory），产品 demo 可展示 |
| 预算透明 (2.10) | **director** | 启动时提示预估 token / 阶段轮次预算，防长任务失控 |
| 反模式表 (2.4/2.3/2.7) | **全阶段** | 提炼格物版反模式（跳验证/自动跳过门控/质量退化/静默丢弃/泛泛反馈等）写入 SKILL.md |

---

## 4. 明确不借鉴的部分（及原因）

- **Claude/Anthropic 强绑定**：格物大脑是书生 `intern-s2`，不引入 `ANTHROPIC_API_KEY`。
- **13/12/7-agent 的"堆人"式编排**：格物用 OpenClaw 原生 7 阶段 + lobster/for_each，不照搬 agent 数量，避免复杂度爆炸。
- **插件市场 / slash command 体系**：格物用 OpenClaw `skills/` 目录自动发现。
- **其具体提示词 / SKILL.md 文本 / schema JSON**：受 CC-BY-NC 约束，只取方法论，重写为格物表述。
- **领域模板（HEI 高等教育）**：那是它默认参考领域，与格物 LIBS/煤热值无关。

---

## 5. 下一步

- [x] `openclaw/skills/research_lifecycle/SKILL.md`：已把 7-mode 真实失败清单、指令-数据边界、three-way-scan、handoff 字段化、模型分层、多视角 DA 裁决内化。
- [x] 把"AI 科研失败模式清单（真实 7-mode）"单独固化为 `failure_mode_selfcheck` 自检 skill：源在 `openclaw/workspace/skills/`，已部署到 distillation / reproduction / improver / writer 四阶段工作区；含四态裁决 + 阻断门控 + `failure_audit_log.json` schema；`research_lifecycle` 规则 ⑦ 已改为指向该技能。
- [ ] 在 `ideation/AGENTS.md` 细化：文献筛选协议 + three-way-scan 提示词 + FINER 打分。
- [ ] 在 `reproduction/AGENTS.md` 细化：复现检查清单 + repro_lock + 7-mode 中段适用项的检测问题。
