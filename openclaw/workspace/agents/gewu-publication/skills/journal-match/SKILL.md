---
name: journal-match
description: >-
  Recommend target journals for manuscript submission. Analyzes manuscript scope,
  discipline, methodology, and language, then searches for similar papers via
  Semantic Scholar and OpenAlex to identify where comparable work is published.
  Enriches journal metadata (h-index, OA status, citation metrics) and produces
  a tiered HTML report ranking journals by scope alignment and impact. Use when the user provides a manuscript
  file, abstract, or topic and asks "where should I publish this?", "find
  matching journals", "journal recommendation", or "venue selection". Do NOT use
  for citation verification, literature review, paper tracking, reference
  management, impact factor lookup without a manuscript, or general bibliometric
  analysis.
---

Recommend target journals for "$ARGUMENTS".

## INPUT DETECTION

1. Determine input type:
   - **File path** → read with Read tool, proceed to Step 1.
   - **Abstract text** (>50 words, contains academic language) → use directly, proceed to Step 1.
   - **Topic description** (<50 words or non-academic) → ask user for 5-10 keywords and discipline before proceeding.
2. If the input is ambiguous, ask the user to clarify.

## STEP 0 — RETRIEVE SIMILAR PUBLISHED PAPERS (few-shot)

Find 5-10 high-impact published papers similar to the user's submission to guide journal matching. This is the PapervizAgent Retriever→Planner pattern: retrieved examples provide few-shot context for better recommendations.

1. After reading the manuscript (in Step 1), extract: title, 5 keywords, discipline, methodology.
2. Search Semantic Scholar for similar highly-cited papers:
   ```
   GET https://api.semanticscholar.org/graph/v1/paper/search?query={keywords}&limit=30&fields=title,venue,year,citationCount,authors,abstract
   ```
3. Filter results:
   - Prefer papers from the last 5 years
   - Prefer papers with >50 citations
   - Prefer papers with matching methodology type
4. Select top 5-10 by: `discipline_match * log(citationCount + 1)`
5. Extract venue distribution from these similar papers — these venues are strong journal candidates.
6. Pass the similar papers list as few-shot context to Step 2 (similar-papers subagent):
   - The subagent should prioritize journals where these similar papers were published.
   - If no similar papers are found, proceed without few-shot examples.

**Fallback:** If Semantic Scholar returns 0 results, broaden to discipline-level keywords. If still empty, skip this step — Step 2 will search independently.

## STEP 1 — EXTRACT MANUSCRIPT PROFILE

1. Read the manuscript or abstract.
2. Extract the following fields into a structured profile:
   - **Discipline**: e.g., law, computer science, medicine, psychology
   - **Sub-field**: e.g., criminal law theory, NLP, oncology
   - **Methodology**: theoretical | empirical | mixed | review | meta-analysis
   - **Scope**: country-specific | comparative | universal
   - **Length**: estimated word count
   - **Keywords**: 5-10 key terms
   - **Language**: manuscript language (for journal-language matching)
   - **Reference profile**: journals cited in the references (candidate journals)
3. If the manuscript is too short (<200 words) or yields fewer than 3 keywords, ask the user to supply additional keywords and discipline context.

## STEP 2 — FIND SIMILAR PAPERS (SUBAGENT)

1. Launch a subagent with the prompt defined in `references/similar-papers-prompt.md`.
2. Pass the manuscript profile fields (keywords, discipline, methodology, language) into the prompt template.
3. The subagent searches Semantic Scholar and OpenAlex for similar papers and returns a venue distribution table. See `references/api-reference.md` for endpoint details.
4. If the subagent finds **zero** similar papers:
   - Broaden keyword search (use individual keywords instead of combinations).
   - Try discipline-level queries (e.g., "criminal law" instead of "criminal law plea bargaining Germany").
   - If still zero, report the limitation and recommend the user consult a librarian or use Scopus/Web of Science manually.

## STEP 3 — ENRICH JOURNAL DATA

1. Take the top 10-15 journals from Step 2.
2. For each journal, retrieve metadata using the APIs described in `references/api-reference.md`:
   - OpenAlex Sources → h_index, works_count, cited_by_count, is_oa, homepage_url, issn
   - CrossRef Journals (if ISSN available) → publication frequency, subject coverage
3. If a journal is **not found** in OpenAlex:
   - Try CrossRef lookup by ISSN.
   - Try name variations (with/without abbreviation).
   - If still not found, mark as "metadata unavailable" and note in the report.
4. Optionally run `scripts/venue_enrich.py` for batch enrichment. Export journal names to JSON and invoke:
   ```
   python scripts/venue_enrich.py --journals journals.json
   ```

## STEP 3B — GROUND JOURNAL RANK VIA EASYSCHOLAR (反幻觉)

> 原则：期刊「等级/分区」（SCI/SSCI/Q区、中科院分区、CSCD/北大核心/中国科技核心等）
> 是 LLM 最易**凭记忆编造**的信息，必须锚定到真实接口，禁止模型自行断言等级。

1. 对 STEP 3 得到的每个候选期刊，调用格物反幻觉·文献核验 MCP 服务：
   `mcp__sci-verify__get_journal_rank(publication_name="<期刊名>")`
   - 期刊名中英文均可（如 `"Talanta"` / `"光谱学与光谱分析"`），工具内部已做 URL 编码。
   - 该工具经 EasyScholar `getPublicationRank` 返回官方数据集（officialRank:
     sci/ssci/中科院分区/各校自科目录…）与自定义数据集（customRank）的权威等级。
2. 返回 JSON：
   - 成功：`{"ok":true,"data":{"official_all":{...},"official_select":{...},
     "custom":[{"dataset","rank","raw_rank"}]},"summary":"官方: sci=Q1 · 自定义: 国自然管科=A"}`
   - 失败（秘钥缺失 / 该刊未登记）：`{"ok":false,"error":"..."}` —— **不得**给该刊
     标注任何等级，报告中标「等级：待核查（EasyScholar 无数据）」，交人工确认。
3. 将 `summary` 作为该期刊「等级/分区」字段，写入 STEP 5 报告卡片的
   `{{EASYSCHOLAR_RANK}}` 占位。
4. 反幻觉边界：期刊「是否存在」仍由 D1（OpenAlex，见 `sci-verify.verify_papers`）
   把关；本步只负责「等级/分区」这一层信息溯源。两者叠用 = 推荐期刊的存在性与
   等级都来自真实接口，杜绝编造期刊等级/分区。

## STEP 4 — SCORE AND RANK

1. For each journal, assign a scope match score (1-5):
   - **5**: Journal publishes exactly this type of work (discipline + methodology match)
   - **4**: Close match with minor discipline/scope differences
   - **3**: Related but broader journal
   - **2**: Tangentially related
   - **1**: Poor match
2. Optionally use `scripts/scope_score.py` for structured scoring:
   ```
   python scripts/scope_score.py --profile manuscript_profile.json --journal journal_data.json
   ```
3. Sort journals by: scope score (primary), h-index (secondary).
4. Assign tiers:
   - **Tier 1 — Best Match**: scope score ≥ 4, strong impact metrics
   - **Tier 2 — Good Alternative**: scope score 3-4, solid metrics
   - **Tier 3 — Specialized/Niche**: scope score 2-3, or niche venues with high relevance
5. If all journals are **closed access**, note this limitation and suggest searching for OA alternatives in the same discipline.

## STEP 5 — PRESENT RECOMMENDATIONS

1. Write a single-file HTML report to: `reports/{date}-journal-match-{slug}.html`
2. Follow the design system in `shared/report-template.md` exactly. Do NOT use Tailwind CDN.
3. Use the structural template in `assets/journal-report-template.md` for the journal-specific layout.
4. Read `references/journal-match-style-guide.md` for tier card styling, scope visualization, and few-shot context display.
4. The report must include:

```
HEADER
  Report tag: "Journal Recommendations"
  Title: manuscript title or topic
  Date: generation date

STATS BAR
  - Journals analyzed: {count}
  - Best match tier: "Tier 1" | "Tier 2" | "Tier 3"
  - Open access: {percentage}%

TIER 1 — BEST MATCH
  For each journal:
  - Journal name (linked to homepage)
  - Scope match: {score}/5 — {one-line reasoning}
  - H-index: {value} · Works: {count} · OA: Yes/No
  - 等级/分区 (EasyScholar): {EASYSCHOLAR_RANK}  ← 来自 sci-verify.get_journal_rank
  - Similar papers found: {count} in last 3 years
  - Notable: "{related paper title}" closely related

TIER 2 — GOOD ALTERNATIVE
  (same card format)

TIER 3 — SPECIALIZED/NICHE
  (same card format)

METHODOLOGY NOTE (footer)
  "Recommendations based on venue analysis of similar papers via
   Semantic Scholar and OpenAlex. Scope scores reflect editorial
   alignment, not acceptance probability. Journal 等级/分区 (SCI/SSCI/
   中科院分区/CSCD/北大核心等) 由 EasyScholar 开放接口经 sci-verify 核验取得，
   期刊存在性经 OpenAlex 核验；二者均未通过者不进入推荐。"
```

5. After writing the file:
   - Return the exact absolute file path to the user.
   - Ask whether they want it opened.
   - Only run `open {file_path}` after the user explicitly confirms.

## AUTOMATED RUNNER（可选·一键重跑）

本技能附带一个**数据驱动 + 反幻觉溯源**的自动化执行脚本，可直接复现上述流程，
无需逐步手调 API：

```
python scripts/run_recommendation.py
```

脚本行为（与上文六步一一对应）：
- 用 OpenAlex 检索相似论文并聚合 **venue 分布**（STEP 0/2，数据驱动候选集）；
- 对每个候选调 OpenAlex 丰富元数据，同时作为 **D1 存在性核验**（STEP 3）；
- 对每个候选调 **EasyScholar**（`sci-verify.get_journal_rank` 同源逻辑）取真实
  等级/分区，失败不编造（STEP 3B）；
- 用 `scope_score` 基于**真实 concepts** 做 scope 打分，并结合「领域专注度」分层（STEP 4）；
- 可选 **种子候选**：在 `SEED_JOURNALS` 中显式纳入领域已知真实目标刊（如中文核心/EI），
  其 subjects 用期刊公开真实范畴，存在性与等级仍由 OpenAlex / EasyScholar 真实核验；
- 生成单文件 HTML 报告到 `<repo>/reports/<date>-journal-match-<slug>.html`
  （遵循 `shared/report-template.md` 设计系统），并落一份机器可读 JSON。

> 注意：脚本中的稿件 profile 与检索式针对「MIL+LIBS 大颗粒原煤热值回归」论文写死；
> 换课题时需改 `PROFILE` / `QUERIES` / `SEED_JOURNALS` 三处。

## STEP 6 — NEXT ACTIONS

Offer follow-up options:
1. "Format manuscript for a specific journal's guidelines?"
2. "Check if your references match what these journals typically cite?"
3. "Draft a cover letter for one of these?"

## ERROR HANDLING

| Condition | Action |
|---|---|
| Manuscript too short (<200 words, <3 keywords) | Ask user for keywords, discipline, and methodology |
| Journal not found in OpenAlex | Try CrossRef by ISSN, then by name variations; mark "metadata unavailable" if all fail |
| Journal metadata unavailable | Try CrossRef by ISSN, then by name variations; mark "metadata unavailable" if all fail |
| All journals are closed access | Note limitation; suggest searching for OA alternatives via DOAJ |
| No similar papers found | Broaden keywords → discipline-level query → report limitation |
| API rate limit or timeout | Retry once after 5 seconds; if still failing, proceed with partial data and note gaps |
| Ambiguous input (not clearly manuscript/abstract/topic) | Ask user to clarify input type |

## TOKEN BUDGET

| Component | Estimate |
|---|---|
| Main session (profile + presentation) | ~5K |
| Similar papers subagent | ~15-20K |
| Journal enrichment | ~5-10K |
| **Total** | **~25-35K** |

## REPORT DESIGN

When writing the HTML report, read and follow the design system in `shared/report-template.md` EXACTLY.
Do NOT use Tailwind CDN. Use the custom CSS variables, font system, and academic book aesthetic defined there.
For the journal-specific report structure, read `assets/journal-report-template.md`.
