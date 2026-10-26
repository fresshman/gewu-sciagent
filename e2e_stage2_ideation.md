# E2E 阶段②：读论文找 idea（受控·有界）

你是 gewu-ideation。基于 director 的 `openclaw/workspace/agents/gewu-director/handoff_1_direction.json`
做**有界**文献调研（本任务是 E2E 七阶段实跑的阶段②，目的是验证编排层与 handoff 传递）。

## 执行（严格有界，避免挂起）
1. 用 `mcp__paper-search__search_papers`（`sources=arxiv,semantic,crossref,openalex,pubmed`）
   检索关键词：multi-instance learning / LIBS / laser-induced breakdown spectroscopy /
    coal calorific value / 大颗粒原煤。取 **top 5** 最相关论文。
2. 对 top 5 做 D1 反幻觉核验：`mcp__sci-verify__verify_papers`。
3. 抽取 gap 与可改进点（基于摘要/标题即可，**不要下载 PDF、不要渲染原页**——如本地已有 PDF 可只读 1 篇）。
4. 写两个文件到你的工作区 `openclaw/workspace/agents/gewu-ideation/`：
   - `handoff_2_litreview.json`：`{stage:2, stage_name:"读论文找idea", status, inputs:["<handoff_1路径>"], outputs:[...], candidates:[{title,doi,relevance,d1_status}], gap, next:"reproduction", next_input:"handoff_2_litreview.json"}`
   - `literature_review.md`：含 Evidence 列（来源/D1核验状态）。

## 纪律（务必遵守）
- 工具调用**控制在 ~12 次以内**；联网受限立即报告，不要无限重试。
- 必须在超时前落盘 `handoff_2_litreview.json`，否则本次编排验证失败。
- 不编造文献；D1 未核验的标 `unverified`。
