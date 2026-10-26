# 格物反幻觉架构（Anti-Hallucination Posture）

> 原则：**反幻觉不是某个工具，而是格物贯穿 7 阶段的横向第一公民（cross-cutting
> first-class concern）。** 任何"对外部世界做出断言"的环节——引用一篇文献、报出一个
> 数字、画一条曲线、写一句结论——都必须能在事后被**溯源、核验、复现**；不能溯源的
> 断言要么被显式降级标注，要么被阻断，绝不允许静默流入成稿。

本文档定义四道横向防线，并映射到格物的每个阶段，标注当前实现状态。

---

## 一、四道横向防线

### D1 — 文献存在性核验（sci-verify / OpenAlex） ✅ 已建成
- **位置**：`gewu/mcp/verify_papers.py`（CLI + 通用逻辑）+ `gewu/mcp/verify_server.py`
  （FastMCP 服务，已注册为 `sci-verify`，7 个智能体任一可调用）。
- **核验链**：`arXiv API → CrossRef DOI → Semantic Scholar 标题 → CrossRef 标题 → OpenAlex`
- **OpenAlex 是第 4 层回退**：免费、无需密钥、覆盖最广，尤其收录 ICML/NeurIPS/CVPR 等
  CrossRef 收录不全的**会议论文**。P1-1 的典型失败——Ilse 2018（ICML）在 arXiv/CrossRef/S2
  三层均落 `unverified`，经 OpenAlex 一次命中（`openalex_title_ratio=1.000`，arxiv 1802.04712）。
- **不变量**：`unverified`（所有层干净跑完均未命中）与 `verify_pending`（某层限流/超时）
  严格区分——**临时失败绝不计入幻觉率**，避免把"查不到"误判为"不存在"。
- **输出语义**：`verified | unverified | verify_pending | error` + `hallucination_rate`。

### D1 扩展 — 期刊等级溯源（EasyScholar，反幻觉·期刊信息） ✅ 已建
- **问题**：期刊推荐时，期刊的「等级/分区」（SCI/SSCI/Q区、中科院分区、CSCD/北大核心/
  中国科技核心、各校自科目录…）是 LLM **最易凭记忆编造**的信息——"该刊为中科院 1 区"
  "属于 CSSCI"张口就来、无法核验，且与 D1 的"存在性"完全是两件事。
- **实现**（`gewu/mcp/journal_rank.py` + `sci-verify` MCP 工具 `get_journal_rank`）：
  - 经 **EasyScholar 开放接口** `getPublicationRank`（免费、无需登录、秘钥 `EASYSCHOLAR_SECRET_KEY`
    由 `journal_rank.py` 从本地 **gitignored** 文件 `gewu/mcp/.easyscholar_key` 读取，不外泄、不入库）。
  - 文档要求 ≤2 req/s，模块级 `_throttle()` 限速到 ~1.8 req/s。
  - 返回结构化等级：官方数据集（`officialRank.all/select`：sci/ssci/中科院分区/各校目录…）
    + 自定义数据集（`customRank`：用户自建分级，按 `uuid&&&rank` 解析出 数据集缩写=等级）。
  - 失败（秘钥缺失 / 该刊未登记）：`ok:false`，**不编造等级**，报告标"待核查"交人工确认。
- **与 D1 的关系**：D1 管"期刊是否存在"，本扩展管"期刊等级是否真实"。两者叠用 =
  推荐期刊的**存在性 + 等级**都来自真实接口，是期刊推荐场景下的完整反幻觉闭环。
- **接入点**：发表官 `journal-match` skill 的 STEP 3B；`get_journal_rank` 已在 `sci-verify` 注册。
- 测试：`tests/test_journal_rank.py` 6 passed（mock 网络）；真实 EasyScholar 实测
  Talanta / Spectrochimica Acta B / Analytical Chemistry / 《光谱学与光谱分析》均返回真实等级。

### D2 — 数值/事实声明的可追溯性（Claim Provenance） ✅ 已建
- **问题**：写手在成稿里写"MIL 取得 RMSE 214.57 kcal/kg"或"较 PLSR 提升 8.1%"，
  这些数字若来自记忆而非真实输出，无法事后核验。
- **实现**（`gewu/mcp/claim_provenance.py` + `sci-verify` MCP 工具）：
  1. **声明结构**：每条数值声明 `{text, metric, value, source}`，`source` 二选一——
     - `registry:<exp_id>` / `registry:<domain>:<exp_id>` → 比对 `sci-exp` 注册表 `source_of_truth`；
     - `paper:<verified_paper_id>` → 须出现在 D1 已核验文献集合（`verified_papers`）。
  2. **核验工具** `verify_claims(input_json, verified_papers, strict)`：逐条比对，
     状态 `grounded | drift | unknown_experiment | metric_not_in_registry |
     paper_grounded | paper_unverified | bad_value`；`strict=True` 时额外真跑
     `sci-exp rerun` 用实时重算真值再比一次。
  3. **容忍度语义（关键）**：D2 用**紧容忍度**（默认 1% 相对 + 0.01 绝对下限）比对
     "写出来的数字 ↔ 注册表真相"，专治写手凭记忆写错/抄错/漂移；这与 `sci-exp rerun`
     的**松容忍度**（如 rmse 1.0，保证代码↔记录一致）是两回事，互不替代。
  4. **闸门**：发表官成稿前跑 `verify_claims`，任何 `drift` / 不可溯源状态一律拦截。
- **与 P0-1 的关系**：D2 复用 `sci-exp` 注册表作为"论文被引用数字的单一台账"，
  是 P0-1（实验可复现）在成稿侧的闭环——数字从注册表来，回到注册表查。
- 测试：`tests/test_claim_provenance.py` 10 passed（含合成注册表 + 真实 coal_mil 校验）。

### D3 — 引用完整性 lint（Citation Lint） ✅ 已建
- **问题**：成稿里的 `\cite{...}` / 参考文献条目，可能指向 D1 未核验、甚至不存在的文献
  （"幽灵引用"）。
- **实现**（`gewu/mcp/citation_lint.py` + `sci-verify` MCP 工具 `lint_citations`）：
  - 抽取引用键（`extract_cite_keys` 支持 `\cite/\citep/\citet/\autocite/...`），或用
    显式键列表；逐一比对 D1 已核验集合 `verified_papers`。
  - 状态：`verified`（在 D1 集合） / `accepted_unverified`（在人工确认集合，中文等 D1 免入项）
    / `phantom`（幽灵引用，既不在 D1 也不在人工确认集合 → 必须修正）。
  - **P1-2 降级**：中文文献（CNKI/万方 D1 不收录）经 `manually_confirmed` 传参标
    `accepted_unverified`——**不静默通过、也不误判为幻觉**，产出"人工核验清单"交用户。
  - 任何 `phantom` 必须修正/剔除后才可成稿。
- 测试：`tests/test_citation_lint.py` 5 passed（含 LaTeX 抽取、幽灵检测、中文降级、tex+显式合并）。

### D4 — 图/数据 Grounding ⚠️ 部分建成
- **成稿绘图**：`sci-plot` 本地出图、数据不出本机，写手已被铁律约束
  "禁止手写或臆造图中数据，数值必须来自 sci-compute / mil-model 真实输出"。
- **原页理解（③）**：intern-s2 读 PDF/图时**可能误读坐标轴、表格、跨页矛盾**
  （本次走查已发现图中标注与跨页矛盾）。此面目前**无自动核验**，依赖写手人工复核 +
  把关键数值回灌 D2 注册表。→ 后续可加"结构化抽取协议"（要求模型返回原文 span /
  bounding box，而非自由文本结论）。

---

## 二、七阶段 × 防线映射

| 阶段 | 对外断言 | 幻觉面 | D1 文献 | D2 数值溯源 | D3 引用 | D4 图/数据 |
|------|----------|--------|---------|-------------|---------|-----------|
| ① 检索 | "找到 N 篇相关文献" | 编造/错配引用 | ✅ | — | — | — |
| ② 反幻觉核验 | "这些文献真实存在" | 漏检真实文献（假阴性） | ✅(含OpenAlex) | — | — | — |
| ③ 原页理解 | "该图显示 X 趋势" | 误读图/表/跨页 | — | ⬜(待D2) | — | ⚠️(人工) |
| ④ 领域建模 | "RMSE=214.57" | 数字漂移/记忆错误 | — | ⬜(待D2,复用sci-exp) | — | — |
| ⑤ 绘图 | "图5 展示…" | 轴标签/数据绑定错 | — | ✅(sci-plot约束) | — | ✅ |
| ⑥ 成稿·LaTeX | "据此我们得到…" | 无源声明/幽灵引用 | ✅(D1前置) | ⬜(待D2) | ⬜(待D3) | ✅ |
| ⑦ 成稿·Word | 同上 | 同上 | ✅ | ⬜ | ⬜ | ✅ |

**结论**：反幻觉当前只在 D1（文献存在性）与 D4 的"绘图约束"两处有硬保障；
**D2（数值溯源）、D3（引用 lint）是让"整个格物都反幻觉"真正闭环的两个必建项**，
且二者都廉价复用既有 `sci-exp` 注册表与 `sci-verify` 服务，无需新基础设施。

---

## 三、降级策略（诚实优于静默）

- 中文文献（P1-2）：CNKI/万方未接入时，标注 `UNVERIFIED` **而非静默通过**；
  产出"人工核验清单"交用户。
- 某层 API 限流/超时：状态 `verify_pending`，**不计入幻觉率**，可重试。
- 领域脚本无权重/日志、无法重算（如草稿 197.99）：在 `sci-exp` 注册表诚实标注
  `requires_original_script`，**不编造数字**；待权重入版本化后一键复现。
- "凭记忆写下的引用"：D1/D3 跑全量校验，尤其重点排查（P1-3 曾抓出一条高度疑似
  不准确引用）。

---

## 四、实施状态

| 项 | 状态 | 说明 |
|----|------|------|
| P1-1 OpenAlex 第 4 层 | ✅ 已修 | `verify_papers.py` 加 OpenAlex；`sci-verify` MCP 服务已注册；8 测试通过 |
| D1 文献核验服务化 | ✅ 已修 | `verify_server.py` 注册为 `sci-verify`，7 agent 可调用 |
| P1-2 中文文献 | ⚠️ 降级策略已定 | 标 UNVERIFIED + 人工清单；接入 CNKI/万方为后续 |
| D2 数值声明溯源 | ✅ 已建 | `claim_provenance.py` + `sci-verify.verify_claims`，复用 sci-exp 注册表 |
| D3 引用完整性 lint | ✅ 已建 | `citation_lint.py` + `sci-verify.lint_citations`，含 P1-2 中文降级 |
| D1 扩展·期刊等级溯源 | ✅ 已建 | `journal_rank.py` + `sci-verify.get_journal_rank`，EasyScholar 接口 + gitignored 秘钥 |
| D4 原页理解 grounding | ⚠️ 人工复核 | 待结构化抽取协议 |

---

## 五、下一步提议（按杠杆排序）

1. **D2 声明注册 + verify_claim**：让写手每条数字声明带溯源标签，发表官终检。
   复用 `sci-exp` 注册表，零新基础设施。
2. **D3 引用 lint**：成稿末尾比对 D1 核验集合，拦截幽灵引用。
3. **D4 原页理解结构化抽取**：要求 intern-s2 返回原文 span/坐标，降低误读。
4. （可选）**中文文献**：评估 CNKI/万方或人工核验清单自动化。
