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
- `RENDER_DPI = 130` — 原页渲染分辨率（平衡可读性与 base64 体积）
- `RENDER_PAGES = "all"` 或 `"1,3,5"` — 全页/精选；首轮建议全页，省 token 可精选图页
- 反幻觉脚本：`gewu/mcp/verify_papers.py`（纯标准库，零依赖）

## 流程

### Step 1 — 检索（多源并发，去重）
调 `mcp__paper-search__search_papers`，sources=`arxiv,semantic,crossref,openalex,pubmed`，
按 research_lifecycle 的 SR-Screener 协议做标题/摘要初筛，产出候选清单
`candidates = [{id, title, arxiv_id, doi, abstract, source, relevance}]`。

### Step 2 — 反幻觉校验（强制，不可跳过）
把候选写成 candidate JSON，Bash 调脚本做三层校验（arXiv API → CrossRef → S2 模糊匹配）：
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
- 可选：设 `ARIS_VERIFY_EMAIL=you@institution.edu` 降低 CrossRef 限流。

### Step 3 — 下载全文 PDF（仅 top N）
对 `REVIEW_TOP_N` 内、且 `status∈{verified, verify_pending}` 的论文，用
`mcp__paper-search__download_with_fallback` 拉全文到 `literature/`。已存在则跳过。

### Step 4 — 原页多模态理解（核心：书生 intern-s2）
对每篇全文 PDF：
1. `mcp__sci-data__render_pdf_pages(pdf_path, pages=RENDER_PAGES, dpi=RENDER_DPI)`
   → `images:[{page, path, width, height}]`。
2. 对每张图 `mcp__sci-data__image_to_data_uri(path)` → `data_uri`。
3. **直接把 `data_uri` 作为 image_url 发给 `sheng/intern-s2`**（不再经 InternVL 转文本）：
   - 文本 content 要求它把该页的图/表/公式与正文方法描述**联合推理**，找出
     跨模态不一致、方法-结果矛盾、图表可疑迹象、未说明的假设。
   - 这是「科学多模态原页理解」的真正落点：模型自己读原页，而非只读 InternVL 抽出的文字。
4. 若某页纯文本（无图/表/公式）可跳过渲染省 token；优先渲染含图/表/公式的页。

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
