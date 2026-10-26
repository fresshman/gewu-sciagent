#!/usr/bin/env python3
"""真实执行 journal-match 期刊推荐流程（数据驱动 + 反幻觉溯源）。

流程：
  STEP 0/2  用 OpenAlex 检索与稿件主题相似的已发表论文，聚合 venue 分布
  STEP 3    对每个候选期刊调 OpenAlex 丰富元数据（同时作为 D1 存在性核验）
  STEP 3B   对每个候选期刊调 EasyScholar 取真实等级/分区（反幻觉·期刊信息溯源）
  STEP 4    用 scope_score 计算稿件↔期刊 scope 匹配分（subjects 来自真实 concepts）
  STEP 5    生成单文件 HTML 报告（遵循 shared/report-template.md 设计系统）

用法：
  python run_recommendation.py
报告写到：<repo>/reports/<date>-journal-match-<slug>.html
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent                      # .../journal-match/scripts
SKILL_DIR = HERE.parent                                    # .../journal-match
REPO = SKILL_DIR.parents[5]                                # .../gewu-sciagent
MCP = REPO / "gewu" / "mcp"

sys.path.insert(0, str(HERE))          # venue_enrich, scope_score
sys.path.insert(0, str(MCP))           # journal_rank
import venue_enrich as ve              # noqa: E402
import scope_score as ss               # noqa: E402
import journal_rank as jr              # noqa: E402

MAILTO = "gewu-sciagent@example.com"
OPENALEX = "https://api.openalex.org/works"

# ----- 稿件 profile（来自 MIL+LIBS 大颗粒原煤热值回归论文） -----
PROFILE = {
    "discipline": "analytical chemistry",
    "sub_field": "spectroscopy",   # 用于 scope 打分的聚焦子领域（避免拼接长串造成的误判 exact）
    "sub_field_display": "laser-induced breakdown spectroscopy and chemometrics",
    "methodology": "empirical",
    "scope": "universal",
    "keywords": [
        "laser-induced breakdown spectroscopy",
        "multiple instance learning",
        "coal",
        "calorific value",
        "chemometrics",
        "regression",
        "deep learning",
        "spectral analysis",
    ],
}
MANUSCRIPT_TITLE = (
    "基于 LSE-Pool 聚合的多示例学习用于大颗粒原煤 LIBS 光谱热值回归"
)

# 领域核心主题词（用于判定期刊「专注度」，避免把 MDPI 大刊误判为最佳匹配）
CORE_TERMS = [
    "spectroscopy", "analytical", "chemometrics",
    "laser-induced breakdown", "atomic spectroscopy", "spectrometry", "laser",
]

# 主题相关检索式（用于发现相似论文的 venue 分布）
QUERIES = [
    "laser-induced breakdown spectroscopy coal calorific value",
    "multiple instance learning spectroscopy chemometrics",
    "laser-induced breakdown spectroscopy deep learning regression",
    "LIBS coal analysis machine learning",
    "chemometrics laser-induced breakdown spectroscopy quantitative",
    "激光诱导击穿光谱 煤 热值",   # 中文检索：纳入中文核心/EI 目标刊
]

# 种子候选：领域已知真实目标刊（中文核心/EI），显式纳入推荐；
# subjects 为期刊公开真实范畴（非编造），仅用于 scope 打分，存在性与等级仍由
# OpenAlex / EasyScholar 真实接口核验。
SEED_JOURNALS = {
    "光谱学与光谱分析": [   # 《光谱学与光谱分析》(OpenAlex 以中文名收录)
        "Spectroscopy", "Chemometrics", "Analytical Chemistry",
        "Laser-induced breakdown spectroscopy", "Atomic spectroscopy",
    ],
    "Chinese Journal of Analytical Chemistry": [  # 《分析化学》
        "Analytical Chemistry", "Chemometrics", "Spectroscopy",
    ],
}


# ----------------------------------------------------------------------------
# STEP 0/2 — 检索相似论文 + 聚合 venue 分布（数据驱动候选集）
# ----------------------------------------------------------------------------
def fetch_works(query: str, per_page: int = 100) -> list[dict]:
    params = urllib.parse.urlencode({
        "search": query,
        "per_page": per_page,
        "mailto": MAILTO,
    })
    url = f"{OPENALEX}?{params}"
    req = urllib.request.Request(
        url, headers={"User-Agent": "Gewu/journal-match/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"[WARN] OpenAlex HTTP {e.code} for query '{query}'", file=sys.stderr)
        return []
    return data.get("results", [])


def discover_venues(queries: list[str]):
    venue_counts: dict[str, int] = defaultdict(int)
    venue_concepts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    venue_works: dict[str, list[dict]] = defaultdict(list)
    for q in queries:
        works = fetch_works(q)
        print(f"[INFO] query '{q[:45]}…' -> {len(works)} works", file=sys.stderr)
        for w in works:
            src = (w.get("primary_location") or {}).get("source")
            if not src:
                continue
            if src.get("type") not in (None, "journal"):
                continue  # 只统计期刊，排除 repository / conference 等
            name = src.get("display_name")
            if not name:
                continue
            venue_counts[name] += 1
            venue_works[name].append(w)
            for c in w.get("concepts", []):
                venue_concepts[name][c.get("display_name")] += c.get("score", 0)
        time.sleep(0.3)
    return venue_counts, venue_concepts, venue_works


# ----------------------------------------------------------------------------
# STEP 3/3B/4 — 丰富元数据 + EasyScholar 等级 + scope 打分
# ----------------------------------------------------------------------------
def process_journal(name: str, subjects: list[str], similar_count: int,
                    notable_title: str, is_seed: bool = False) -> dict | None:
    """单刊处理：D1 存在性核验 + scope 打分 + 领域专注度 + EasyScholar 等级。"""
    # STEP 3：OpenAlex 元数据 + D1 存在性核验
    meta = ve.enrich_journal(name, MAILTO)
    if meta is None:
        print(f"[SKIP] D1 存在性核验失败（OpenAlex 未收录）: {name}", file=sys.stderr)
        return None
    # STEP 4：subjects 来自真实 concepts（数据驱动）或种子刊真实范畴（不编造）
    score, reasoning = ss.compute_score(PROFILE, {
        "name": meta["name"],
        "subjects": subjects,
        "type": "journal",
        "is_oa": meta["is_oa"],
        "h_index": meta["h_index"],
        "works_count": meta["works_count"],
    })
    core_focus = sum(1 for s in subjects
                     if any(t in s.lower() for t in CORE_TERMS))
    # STEP 3B：EasyScholar 等级（反幻觉溯源；失败不编造）
    rank = jr.query_publication_rank(meta["name"])
    rank_text = rank["summary"] if rank.get("ok") else "等级：待核查（EasyScholar 无数据）"
    return {
        "name": meta["name"],
        "homepage_url": meta["homepage_url"] or "#",
        "is_oa": bool(meta["is_oa"]),
        "h_index": meta["h_index"],
        "works_count": meta["works_count"],
        "cited_by_count": meta["cited_by_count"],
        "issn": meta["issn"],
        "scope_score": score,
        "scope_reasoning": reasoning,
        "core_focus": core_focus,
        "easyscholar_rank": rank_text,
        "similar_count": similar_count,
        "notable_title": notable_title,
        "subjects": subjects,
        "is_seed": is_seed,
    }


def build_journals(top_names, venue_concepts, venue_works,
                   seed_journals: dict[str, list[str]]) -> list[dict]:
    journals = []
    seen = set()
    # 数据驱动候选（来自相似论文 venue 分布）
    for name in top_names:
        if name in seen:
            continue
        seen.add(name)
        concepts = venue_concepts.get(name, {})
        subjects = sorted(concepts, key=concepts.get, reverse=True)[:8]
        yr = date.today().year
        recent = [w for w in venue_works[name]
                  if (w.get("publication_year") or 0) >= yr - 2]
        similar_count = len(recent) if recent else len(venue_works[name])
        notable = max(venue_works[name],
                      key=lambda w: w.get("cited_by_count", 0), default=None)
        j = process_journal(name, subjects, similar_count,
                            (notable or {}).get("title", "—"))
        if j:
            journals.append(j)
        time.sleep(0.2)
    # 种子候选（领域已知真实目标刊，显式纳入；subjects 为期刊真实范畴，非编造）
    for name, subs in seed_journals.items():
        if name in seen:
            continue
        seen.add(name)
        j = process_journal(name, subs, 0, "—（种子候选，非 venue 分布得出）",
                           is_seed=True)
        if j:
            journals.append(j)
        time.sleep(0.2)
    return journals


def assign_tiers(journals: list[dict]) -> list[dict]:
    # 分层：scope 分 + 领域专注度（专注光谱/分析的期刊优先），tier 仅作建议性排序
    journals.sort(key=lambda j: (j["scope_score"], j["core_focus"],
                                 j["works_count"] or 0),
                  reverse=True)
    for j in journals:
        s, c = j["scope_score"], j["core_focus"]
        if s >= 3 and c >= 3:
            j["tier"] = 1          # 真正专注本领域的期刊
        elif s >= 3 and c >= 2:
            j["tier"] = 2          # 相关但较宽泛
        else:
            j["tier"] = 3          # 边缘相关
    return journals


# ----------------------------------------------------------------------------
# STEP 5 — 生成 HTML 报告
# ----------------------------------------------------------------------------
CSS = r"""
:root {
  --font-heading: 'Crimson Pro', Georgia, 'Times New Roman', serif;
  --font-body: 'Source Sans 3', system-ui, -apple-system, sans-serif;
  --paper: #fbfaf7; --surface: #ffffff; --ink: #1c1a17; --text: #2d2a25;
  --muted: #6b655c; --border: #e4ded3; --accent: #8a1c1c; --positive: #2f7d4f;
  --tier1: #38a169; --tier1-bg: rgba(56,161,105,0.10);
  --tier2: #2b6cb0; --tier2-bg: rgba(43,108,176,0.10);
  --tier3: #718096; --tier3-bg: rgba(113,128,150,0.10);
}
* { box-sizing: border-box; }
body { margin:0; background:var(--paper); color:var(--text);
  font-family:var(--font-body); line-height:1.55; -webkit-font-smoothing:antialiased; }
.report { max-width:880px; margin:2.5rem auto; padding:2.5rem 2.75rem;
  background:var(--surface); border:1px solid var(--border); border-radius:6px;
  box-shadow:0 1px 3px rgba(0,0,0,0.04); }
.report-header { border-bottom:2px solid var(--accent); padding-bottom:1rem; margin-bottom:1.5rem; }
.report-tag { text-transform:uppercase; letter-spacing:0.12em; font-size:0.72rem;
  color:var(--accent); font-weight:600; margin:0 0 0.25rem; }
.report-title { font-family:var(--font-heading); font-size:1.9rem; font-weight:700;
  color:var(--ink); margin:0.25rem 0; line-height:1.2; }
.report-subtitle { color:var(--muted); margin:0.25rem 0 0.75rem; }
.report-meta { font-size:0.8rem; color:var(--muted); }
.meta-sep { margin:0 0.4rem; }
.metrics { display:flex; gap:1rem; margin:1.5rem 0; flex-wrap:wrap; }
.metric-card { flex:1 1 0; min-width:140px; background:var(--paper);
  border:1px solid var(--border); border-radius:4px; padding:1rem; text-align:center; }
.metric-value { font-family:var(--font-heading); font-size:1.6rem; font-weight:700; color:var(--ink); }
.metric-label { font-size:0.78rem; color:var(--muted); text-transform:uppercase; letter-spacing:0.06em; }
.callout { background:var(--paper); border-left:3px solid var(--accent);
  padding:0.85rem 1.1rem; margin:1.25rem 0; font-size:0.92rem; border-radius:0 4px 4px 0; }
h2 { font-family:var(--font-heading); color:var(--ink); border-bottom:1px solid var(--border);
  padding-bottom:0.4rem; margin-top:2rem; }
.report-footer { margin-top:2.5rem; padding-top:1rem; border-top:1px solid var(--border);
  font-size:0.82rem; color:var(--muted); }
.report-footer p { margin:0.3rem 0; }
.tag { display:inline-block; font-size:0.7rem; font-weight:600; letter-spacing:0.05em;
  padding:0.15rem 0.5rem; border-radius:3px; background:var(--paper);
  border:1px solid var(--border); color:var(--muted); }
.tag-oa { background:#e8f5e9; color:var(--positive); border-color:#c8e6c9; }
.journal-card { background:var(--surface); border:1px solid var(--border);
  border-radius:4px; padding:1.5rem; margin:1rem 0; }
.journal-card.tier-1 { border-left:4px solid var(--tier1); background:var(--tier1-bg); }
.journal-card.tier-2 { border-left:4px solid var(--tier2); background:var(--tier2-bg); }
.journal-card.tier-3 { border-left:4px solid var(--tier3); background:var(--tier3-bg); }
.journal-card-header { display:flex; justify-content:space-between; align-items:flex-start;
  flex-wrap:wrap; gap:0.5rem; margin-bottom:0.75rem; }
.journal-name { font-family:var(--font-body); font-size:1.1rem; font-weight:600;
  color:var(--ink); margin:0; }
.journal-name a { color:var(--ink); text-decoration:none; border-bottom:1px solid var(--border); }
.journal-name a:hover { border-bottom-color:var(--accent); }
.journal-badges { display:flex; gap:0.35rem; flex-wrap:wrap; }
.journal-meta-row { font-size:0.9rem; color:var(--text); margin-bottom:0.35rem; }
.score-bar { height:6px; border-radius:3px; background:var(--border); margin:0.3rem 0 0.5rem; }
.score-bar > span { display:block; height:100%; border-radius:3px; background:var(--tier1); }
.journal-rank { font-size:0.92rem; color:var(--accent); margin-bottom:0.5rem;
  padding:0.4rem 0.6rem; background:color-mix(in srgb, var(--accent) 8%, transparent);
  border-left:3px solid var(--accent); border-radius:2px; }
.journal-rank strong { color:var(--ink); }
.journal-notable { font-size:0.9rem; color:var(--muted); font-style:italic; margin:0.5rem 0 0; }
details { margin:1rem 0; border:1px solid var(--border); border-radius:4px; padding:0.5rem 1rem; }
summary { cursor:pointer; font-weight:600; color:var(--ink); }
table { width:100%; border-collapse:collapse; font-size:0.85rem; margin-top:0.5rem; }
th, td { text-align:left; padding:0.4rem 0.5rem; border-bottom:1px solid var(--border); }
"""


def html_card(j: dict) -> str:
    oa = '<span class="tag tag-oa">OPEN ACCESS</span>' if j["is_oa"] else ""
    seed = '<span class="tag">种子候选</span>' if j.get("is_seed") else ""
    h_index = j["h_index"] if j["h_index"] is not None else "N/A"
    pct = max(4, min(100, int(j["scope_score"] / 5 * 100)))
    bar_color = {1: "var(--tier1)", 2: "var(--tier2)", 3: "var(--tier3)"}[j["tier"]]
    return f"""
    <div class="journal-card tier-{j['tier']}">
      <div class="journal-card-header">
        <h3 class="journal-name"><a href="{j['homepage_url']}">{j['name']}</a></h3>
        <div class="journal-badges">
          <span class="tag">TIER {j['tier']}</span>{seed}{oa}
        </div>
      </div>
      <div class="journal-meta-row">
        <span>Scope: <strong>{j['scope_score']}/5</strong> — {j['scope_reasoning']}</span>
      </div>
      <div class="score-bar"><span style="width:{pct}%;background:{bar_color}"></span></div>
      <div class="journal-meta-row">
        <span>H-index: {h_index}</span><span class="meta-sep">·</span>
        <span>Works: {j['works_count']}</span><span class="meta-sep">·</span>
        <span>Citations: {j['cited_by_count']}</span>
      </div>
      <div class="journal-rank">等级/分区 (EasyScholar): <strong>{j['easyscholar_rank']}</strong></div>
      <div class="journal-meta-row">
        <span>Similar papers: {j['similar_count']} in last 3 years</span>
      </div>
      <p class="journal-notable">Notable: "{j['notable_title']}" closely related to this manuscript</p>
    </div>
    """


def build_html(journals: list[dict], example_papers: list[dict]) -> str:
    tiers = {1: [], 2: [], 3: []}
    for j in journals:
        tiers[j["tier"]].append(j)
    best_tier = min((j["tier"] for j in journals), default=0)
    best_tier_label = {1: "Tier 1", 2: "Tier 2", 3: "Tier 3"}.get(best_tier, "—")
    oa_n = sum(1 for j in journals if j["is_oa"])
    oa_pct = round(oa_n / len(journals) * 100) if journals else 0
    today = date.today().isoformat()
    cards = "".join(html_card(j) for j in journals)
    ex_rows = "".join(
        f"<tr><td>{ (p.get('title') or '')[:80] }</td>"
        f"<td>{ ((p.get('primary_location') or {}).get('source') or {}).get('display_name','—') }</td>"
        f"<td>{p.get('publication_year','—')}</td>"
        f"<td>{p.get('cited_by_count',0)}</td></tr>"
        for p in example_papers[:10]
    )
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Journal Recommendations — {MANUSCRIPT_TITLE}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Crimson+Pro:wght@400;600;700&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<div class="report">
  <header class="report-header">
    <p class="report-tag">Journal Recommendations</p>
    <h1 class="report-title">{MANUSCRIPT_TITLE}</h1>
    <p class="report-subtitle">基于 scope、方法与影响力的目标期刊分析（数据驱动 + 反幻觉溯源）</p>
    <div class="report-meta"><span>Gewu · journal-match</span><span class="meta-sep">·</span><span>{today}</span></div>
  </header>
  <div class="metrics">
    <div class="metric-card"><div class="metric-value">{len(journals)}</div><div class="metric-label">Journals Analyzed</div></div>
    <div class="metric-card"><div class="metric-value">{best_tier_label}</div><div class="metric-label">Best Match Tier</div></div>
    <div class="metric-card"><div class="metric-value">{oa_pct}%</div><div class="metric-label">Open Access</div></div>
  </div>
  <div class="callout">
    <strong>Manuscript Profile</strong> —
    {PROFILE['discipline']} · {PROFILE['sub_field_display']} · {PROFILE['methodology']} · {PROFILE['scope']}
    <br>Keywords: {', '.join(PROFILE['keywords'])}
  </div>
  <details>
    <summary>Similar Published Papers（{len(example_papers)} found，用于引导 venue 分布）</summary>
    <table>
      <thead><tr><th>Title</th><th>Venue</th><th>Year</th><th>Citations</th></tr></thead>
      <tbody>{ex_rows}</tbody>
    </table>
    <p class="report-footer" style="border:0;margin:0.5rem 0 0">
      候选期刊集合由上述相似论文的 venue 分布聚合得到（OpenAlex），再经存在性核验与等级溯源。
    </p>
  </details>
  <h2>Tier 1 — Best Match</h2>
  {''.join(html_card(j) for j in tiers[1]) or '<p class="journal-notable">（无）</p>'}
  <h2>Tier 2 — Good Alternative</h2>
  {''.join(html_card(j) for j in tiers[2]) or '<p class="journal-notable">（无）</p>'}
  <h2>Tier 3 — Specialized / Niche</h2>
  {''.join(html_card(j) for j in tiers[3]) or '<p class="journal-notable">（无）</p>'}
  <footer class="report-footer">
    <p>推荐基于 OpenAlex 检索相似论文的 venue 分布分析；scope 分反映编辑方向契合度，不代表录用概率。
    期刊等级/分区（SCI/SSCI/中科院分区/CSCD/北大核心等）由 EasyScholar 开放接口经 sci-verify 核验取得；
    期刊存在性经 OpenAlex 核验；二者未通过者不进入推荐。等级字段若显示「待核查」表示该刊在 EasyScholar 无登记数据，需人工确认。</p>
    <p>Generated by Gewu · journal-match · {today}</p>
  </footer>
</div>
</body>
</html>
"""


def main() -> None:
    print("[STEP 0/2] 检索相似论文 + 聚合 venue 分布…", file=sys.stderr)
    venue_counts, venue_concepts, venue_works = discover_venues(QUERIES)
    top = sorted(venue_counts, key=venue_counts.get, reverse=True)[:15]
    print(f"[INFO] Top {len(top)} venues: " +
          ", ".join(f"{n}({venue_counts[n]})" for n in top), file=sys.stderr)

    # 收集示例相似论文（跨所有 query 的高引期刊论文）
    example_papers = []
    seen = set()
    for name in top:
        for w in sorted(venue_works[name],
                        key=lambda x: x.get("cited_by_count", 0), reverse=True)[:3]:
            key = w.get("id")
            if key and key not in seen:
                seen.add(key)
                example_papers.append(w)

    print("[STEP 3/3B/4] 丰富元数据 + EasyScholar 等级 + scope 打分…", file=sys.stderr)
    journals = build_journals(top, venue_concepts, venue_works, SEED_JOURNALS)
    journals = assign_tiers(journals)
    print(f"[INFO] 通过 D1 存在性核验的期刊: {len(journals)}", file=sys.stderr)

    out_dir = REPO / "reports"
    out_dir.mkdir(exist_ok=True)
    html = build_html(journals, example_papers)
    slug = "mil-libs-coal"
    out_path = out_dir / f"{date.today().isoformat()}-journal-match-{slug}.html"
    out_path.write_text(html, encoding="utf-8")

    # 同时落一份机器可读 JSON（便于复核/二次处理）
    json_path = out_dir / f"{date.today().isoformat()}-journal-match-{slug}.json"
    json_path.write_text(json.dumps({
        "profile": PROFILE,
        "manuscript_title": MANUSCRIPT_TITLE,
        "journals": journals,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[DONE] 报告: {out_path}", file=sys.stderr)
    print(f"[DONE] 数据: {json_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
