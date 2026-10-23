---
name: gewu-lit-review
description: 科研文献阅读与方向探索（最大化书生科学多模态原页理解）。检索→反幻觉校验→下载全文→原页多模态理解→结构化归纳。当 ideation 阶段读论文、找 gap、提炼 idea 时使用。
---

# 格物·文献阅读（原页多模态）

本技能把「读论文」这一步从**纯文本摘要**升级为**书生 intern-s2 多模态原页理解**：
PDF 原页（图+表+公式同帧）直接作为 `image_url` 喂给 `sheng/intern-s2`，让模型在
统一表征空间联合推理，发现「图与正文方法描述矛盾」「公式与表格数据对不上」等
跨模态 gap——这是书生相对纯文本模型的最大差异点。配合 `verify_papers.py`
反幻觉校验，杜绝编造 arXiv ID/DOI。

## 常量
- `MAX_PAPERS = 15` — 检索召回上限
- `REVIEW_TOP_N = 5` — 进入「下载全文+原页理解」的 top 论文数（吃 256K 上下文，克制）
- `RENDER_DPI = 110~150` — 原页渲染分辨率（实测 130 即可读图内小字标注；
  150 时 A4 单页 base64 ≈ 570KB，两页合计 ≈ 5.5K prompt tokens）
- `RENDER_PAGES` — **默认 `"figtab"`**（只渲染含图页）；或先用 `pdf_page_map`
  拿到 `suggested_pages` 再按需精选。**不要按正文图号猜页码**（见下方实测教训）
- 反幻觉脚本：`gewu/mcp/verify_papers.py`（纯标准库，零依赖）

## 实测教训（真实论文验证，务必遵守）

1. **图号 ≠ 页码，禁止猜页。** 实测某中文 LIBS 论文：正文 p9 写着"图6 对比了…"，
   但 p9 内嵌图数为 **0**，图6 实际在 **p10**。盲目渲染会得到"该页无图"的空转结果。
   → 渲染前必须 `pdf_page_map`，或直接用 `pages="figtab"`。
2. **书生会拒绝编造——这是优点，要如实接受。** 测试中它明确回复"该页未包含图6 的
   图像本身…无法对散点分布进行视觉判读"，而不是编造坐标与趋势。
   遇到"无法回答/看不清"时，**换页重渲染**，不要追问施压让它虚构。
3. **图内标注数值是纯文本路线的盲区，正是原页理解的价值。** 实测书生从图中读出了
   `RMSEp=1.097 / MAEp=0.934`、PCA 方差解释率 `PC1 47.9%/43.2%`、`PC2 17.9%/28.3%`
   —— 这些数值写在图里，**PDF 文本层完全没有**，任何 OCR/文本抽取都拿不到。
4. **多页联合推理能发现跨页 gap。** 实测把"结果页+方法页"两页一起给它，它指出：
   结果页把优势归因于"缓解分布差异"，但方法页损失函数并无域适应/分布鲁棒项，
   即**结论归因缺乏方法层显式支撑**。这类跨页矛盾是单页阅读发现不了的。
5. **图中数值的末位/位序会读错，关键数字必须二次确认。**
   实测（Talanta 2025 煤质论文）：Fig.4(b) 的 `R²_P=0.8851` 首次被读成 `0.8551`
   （位序错），Fig.6(c) 的 `0.9616` 读成 `0.9619`（末位错）。
   → **要写进综述/对比表的数字**，必须 (a) 二次复读，或 (b) 与正文表格对照；
   两者冲突时**以文本层/表格为准**，并在表中标注"图中读数"与"表值"的差异。
6. **同一回答内部会前后打架（长回答尤甚）。** 实测读综述 Fig.7 时，表里写 #12 的
   After 为 `/`（无数据），结论段却写 `37.58%→8.73%`。
   → 要求**一次性输出结构化表格**，并加约束："无数据写 `/`，结论段不得与表格冲突"。
7. **要允许并期待它回答"图中没有"。** 实测问 Fig.6 的 RMSE，它答"图中仅标注 R²，
   RMSE 仅见于 Table 3"——没有把正文表格数字冒充成图内读数。
   → 提示词里保留"看不清就写看不清"，这是抗幻觉的正面机制，不要删。
8. **长综合任务（跨文献 gap 分析）intern-s2 会先吐推理草稿。**
   → 提示里写"只输出最终结论，不要输出推理过程"，且 `max_tokens ≥ 3000`，
   否则被截断在草稿里，看起来像答非所问。
9. **图号定位的双重坑：图号≠页码，且一页可能只含部分子图。**
   实测综述 Fig.7 在 p13、Fig.8 在 p14；问 Fig.7 却渲染了 p14，模型直接指出
   "本页只有 Fig.8"（拒答正确，但白花一次调用）。
   → 除 `pdf_page_map` 外，**用图注所在页定位**（在文本层 grep `Fig. 7`），
   或一次渲染 2–3 个相邻含图页。

## 流程

### Step 1 — 检索（多源并发，去重）
调 `mcp__paper-search__search_papers`，sources=`arxiv,semantic,crossref,openalex,pubmed`，
按 research_lifecycle 的 SR-Screener 协议做标题/摘要初筛，产出候选清单
`candidates = [{id, title, arxiv_id, doi, abstract, source, relevance}]`。

### Step 2 — 反幻觉校验（强制，不可跳过）
把候选写成 candidate JSON，Bash 调脚本做四层校验
（arXiv API → CrossRef DOI → S2 模糊标题 → **CrossRef 标题检索回退**）：
```bash
cd <项目根>
cat > /tmp/candidates.json <<'JSON'
[{"id":"p1","arxiv_id":"2307.03172","doi":null,"title":"..."},
 {"id":"p2","arxiv_id":null,"doi":"10.1016/...","title":"..."}]
JSON
"/c/Users/SHJ/.workbuddy/binaries/python/envs/default/Scripts/python.exe" \
  gewu/mcp/verify_papers.py --input /tmp/candidates.json --output /tmp/verified.json
```
读 `/tmp/verified.json`：每条带 `verified | unverified | verify_pending` 标记。
- **绝不沉默丢弃** unverified：在后续表格里保留 `[UNVERIFIED]` 标记，供用户审计。
- `verify_pending`（多为 S2 无 key 限流）不要冒充 verified，原样展示并建议下轮重试。
- **第 4 层是实测补的**：只有标题、没有 DOI 的文献原本一律走 S2，无 key 时几乎必然
  429 → 全部 pending，校验形同失效。2026-10-23 实测三篇英文 LIBS 论文时，Talanta
  那篇正是 S2 pending；加 CrossRef `query.title` 回退后稳定命中
  （`10.1016/j.talanta.2025.128106`，标题相似度 1.000），而编造标题正确判为
  `unverified`。方法字段为 `crossref_title_fallback_from_s2`。
- 可选：设 `ARIS_VERIFY_EMAIL=you@institution.edu` 降低 CrossRef 限流。

### Step 3 — 下载全文 PDF（仅 top N）
对 `REVIEW_TOP_N` 内、且 `status∈{verified, verify_pending}` 的论文，用
`mcp__paper-search__download_with_fallback` 拉全文到 `literature/`。已存在则跳过。

### Step 3.5 — 定位含图页（强制，实测踩坑点）
`mcp__sci-data__pdf_page_map(pdf_path)` → 返回每页 `n_images` 与 `figure_pages`、
`suggested_pages`。用它决定 Step 4 渲染哪些页，**不要凭正文图号猜页码**。

### Step 4 — 原页多模态理解（核心：书生 intern-s2）
对每篇全文 PDF：
1. `mcp__sci-data__render_pdf_pages(pdf_path, pages="figtab"|<suggested_pages>,
   dpi=RENDER_DPI)` → `images:[{page, path, width, height}]`。
2. 对每张图 `mcp__sci-data__image_to_data_uri(path)` → `data_uri`。
3. **直接把 `data_uri` 作为 image_url 发给 `sheng/intern-s2`**（不再经 InternVL 转文本）：
   - 文本 content 要求它把该页的图/表/公式与正文方法描述**联合推理**，找出
     跨模态不一致、方法-结果矛盾、图表可疑迹象、未说明的假设。
   - 这是「科学多模态原页理解」的真正落点：模型自己读原页，而非只读 InternVL 抽出的文字。
4. **优先"结果页+方法页"成对喂入**（实测最有效）：一次请求里放 2 页图，要求它
   交叉检验"正文结论 ↔ 图中证据 ↔ 方法/公式设计"三者是否自洽，能挖出跨页 gap。
5. 纯文本页（pdf_page_map 显示 `n_images=0` 且是参考文献/摘要页）跳过渲染省 token。
6. 单篇原页理解完成后，及时把结论写入 `literature_review.md`，不要长期占用上下文。

> ⚠️ 上下文纪律：256K 也有限。每批评 `REVIEW_TOP_N` 篇的原页分次给 intern-s2，
> 不要一次性塞入所有 PDF 全页。base64 单图超 4MB 时 `image_to_data_uri` 会告警，
> 此时降 dpi 或缩小 pages。

### Step 5 — 归纳输出
产出结构化文献表（含 verification 列）：
```
| Paper | Venue | Method | Key Result | 跨模态发现 | Relevance | Verify |
```
+ 叙事性 gap 分析（3–5 段），重点写出**原页理解发现的图文矛盾/未言明假设**——
这是纯文本路线拿不到的增量。输出到 `literature_review.md`，把 top idea 候选
回传 director（A2A announce）。
