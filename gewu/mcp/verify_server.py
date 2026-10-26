#!/usr/bin/env python3
"""sci-verify — 格物反幻觉·文献核验 MCP Server。

把 verify_papers 的"多层核验"能力暴露成 MCP 工具，使 7 个智能体中的任意一个
（检索/写手/发表官/复现员…）都能直接调用，而不再依赖一条会被遗忘的 CLI 约定。

核验链（领域无关，覆盖绝大多数自然/工程/医学文献）：
    arXiv API → CrossRef DOI → Semantic Scholar 标题 → CrossRef 标题 → OpenAlex
OpenAlex 是第 4 层回退，覆盖 ICML/NeurIPS/CVPR 等 CrossRef 收录不全的会议论文，
杜绝"真实论文被误判 unverified"的假阳性幻觉信号（见 P1-1）。

权威来源：本服务只判断"论文是否真实存在"，不评价内容优劣。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# verify_papers 与本文件同目录
sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_papers as vp  # noqa: E402
import claim_provenance as cp  # noqa: E402  # D2 数值声明溯源引擎
import citation_lint as cl  # noqa: E402  # D3 引用完整性 lint
import journal_rank as jr  # noqa: E402  # EasyScholar 期刊等级溯源（反幻觉·期刊信息）
import source_ground as sg  # noqa: E402  # D4 原页理解 grounding（核对原页文本层读数）

mcp = FastMCP("sci-verify")


@mcp.tool()
def verify_papers(input_json: str, user_email: str = "", no_cache: bool = False) -> str:
    """核验一批候选文献是否真实存在，返回 JSON 校验结论。

    参数:
      input_json: 文献数组的 JSON 字符串，元素形如
        {"id":"p1","arxiv_id":"1802.04712","doi":null,"title":"..."}
        —— 任一层（arxiv_id / doi / title）提供其一即可触发对应核验链。
      user_email: 可选，用于 CrossRef/OpenAlex 礼貌池（降低限流），建议填机构邮箱。
      no_cache: 为 true 时禁用本地缓存（默认命中缓存以加速并降频）。

    返回 JSON 结构:
      {"verdict":"PASS|WARN|BLOCKED|ERROR",
       "hallucination_rate":0.0, "pending_rate":0.0,
       "warnings":[...],
       "papers":[{"id","status":"verified|unverified|verify_pending|error",
                  "method","confidence","reason","identifiers"}]}

    status 含义:
      verified       — 至少一层确认存在
      unverified     — 所有可用层干净跑完且未命中（高度疑似幻觉/编造引用）
      verify_pending — 某层临时失败（限流/超时），请勿计入幻觉率
    """
    try:
        papers = [vp.PaperInput(**d) for d in json.loads(input_json)]
    except Exception as e:
        return json.dumps(
            {"verdict": "BLOCKED", "papers": [], "warnings": ["input_unreadable"],
             "error": str(e)}, ensure_ascii=False
        )

    cache = None
    if not no_cache and papers:
        cp = vp.resolve_cache_path("project", None)
        if cp:
            cache = vp.load_cache(cp, vp.DEFAULT_CACHE_TTL_DAYS)

    results = vp.verify_papers(
        papers,
        arxiv_batch_size=vp.DEFAULT_BATCH_SIZE,
        fuzzy_threshold=vp.DEFAULT_FUZZY_THRESHOLD,
        user_email=user_email or "gewu-verify@local",
        cache=cache,
    )
    if cache is not None and papers:
        vp.save_cache(vp.resolve_cache_path("project", None), cache)

    verdict, metrics = vp.compute_verdict(results, vp.DEFAULT_HALLUCINATION_WARN_THRESHOLD)
    return json.dumps(
        {"verdict": verdict, **metrics, "papers": [vp.asdict(r) for r in results]},
        ensure_ascii=False, indent=2,
    )


@mcp.tool()
def verify_papers_file(input_path: str, output_path: str | None = None, user_email: str = "") -> str:
    """从文件读取文献数组（JSON）并写入校验结论。

    参数:
      input_path: 含文献数组的 JSON 文件路径。
      output_path: 可选，结论写出路径；省略则只返回字符串。
      user_email: 可选，礼貌池邮箱。
    返回: 校验结论 JSON 字符串（与 verify_papers 一致）。
    """
    try:
        papers = [vp.PaperInput(**d) for d in json.loads(Path(input_path).read_text(encoding="utf-8"))]
    except Exception as e:
        return json.dumps(
            {"verdict": "BLOCKED", "papers": [], "warnings": ["input_unreadable"],
             "error": str(e)}, ensure_ascii=False
        )

    cache = None
    cp = vp.resolve_cache_path("project", None)
    if cp:
        cache = vp.load_cache(cp, vp.DEFAULT_CACHE_TTL_DAYS)

    results = vp.verify_papers(
        papers,
        arxiv_batch_size=vp.DEFAULT_BATCH_SIZE,
        fuzzy_threshold=vp.DEFAULT_FUZZY_THRESHOLD,
        user_email=user_email or "gewu-verify@local",
        cache=cache,
    )
    if cache is not None:
        vp.save_cache(cp, cache)

    verdict, metrics = vp.compute_verdict(results, vp.DEFAULT_HALLUCINATION_WARN_THRESHOLD)
    payload = json.dumps(
        {"verdict": verdict, **metrics, "papers": [vp.asdict(r) for r in results]},
        ensure_ascii=False, indent=2,
    )
    if output_path:
        Path(output_path).write_text(payload, encoding="utf-8")
    return payload


@mcp.tool()
def verify_claims(input_json: str, verified_papers: str | None = None, strict: bool = False) -> str:
    """D2 数值声明溯源：校验成稿里每条"对外断言的数字"是否可溯源、与真相一致。

    参数:
      input_json: 声明数组的 JSON 字符串，元素形如
        {"text":"MIL 取得 RMSE","metric":"rmse_kcal_mean","value":214.57,
         "source":"registry:our_hybrid"}
        source 支持：
          registry:<exp_id>            → 比对 sci-exp 注册表 source_of_truth
          registry:<domain>:<exp_id>   → 同上（domain 可选，id 全局唯一）
          paper:<paper_id>             → 要求该文献在 D1 已核验集合内
        value 可为数字或带单位的字符串（如 "214.57 kcal/kg"）。
      verified_papers: 可选，D1 已核验文献 id 的 JSON 数组字符串
        （paper:<id> 溯源时，id 须在此集合中，否则判 paper_unverified）。
      strict: 为 true 时额外真跑 rerun_experiment 用实时重算真值比对（最强但耗时）。

    返回 JSON 汇总：
      {"all_grounded":bool,"n_claims":N,"n_grounded":G,"n_drift":D,"n_unverifiable":U,
       "counts":{...},"claims":[{status,text,value,truth,abs_diff,tolerance,...}]}
      status ∈ grounded|drift|unknown_experiment|metric_not_in_registry|
               paper_grounded|paper_unverified|bad_value|bad_source|metric_required
    发表官应在成稿前以此做"声明溯源闸门"：任何 drift / unverifiable 不得落稿。
    """
    try:
        claims = json.loads(input_json)
        vps = json.loads(verified_papers) if verified_papers else None
    except Exception as e:
        return json.dumps(
            {"all_grounded": False, "claims": [], "warnings": ["input_unreadable"],
             "error": str(e)}, ensure_ascii=False
        )
    report = cp.verify_claims(claims, verified_papers=vps, strict=strict)
    return json.dumps(report, ensure_ascii=False, indent=2)


@mcp.tool()
def save_claims(input_json: str, path: str) -> str:
    """把成稿的数值声明清单持久化到文件（写手产出、发表官后续 verify_claims 复核用）。

    参数:
      input_json: 声明数组 JSON 字符串（同 verify_claims）。
      path: 写出路径（相对路径锚定 output/documents/，防 ../ 越界；绝对路径可写到项目外）。
    返回: 写出的绝对路径或错误 JSON。
    """
    try:
        claims = json.loads(input_json)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"input_unreadable: {e}"}, ensure_ascii=False)
    p = Path(path)
    if not p.is_absolute():
        p = Path("output/documents") / p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(claims, ensure_ascii=False, indent=2), encoding="utf-8")
    return json.dumps({"ok": True, "path": str(p), "n_claims": len(claims)}, ensure_ascii=False)


@mcp.tool()
def lint_citations(input_json: str, verified_papers: str | None = None,
                   manually_confirmed: str | None = None, tex: str | None = None) -> str:
    """D3 引用完整性 lint：成稿引用键逐一比对 D1 已核验集合，拦截幽灵引用。

    参数:
      input_json: 引用键数组 JSON 字符串，如 ["ilse2018","resnet2016","cn_li2020"]；
        也可省略，直接传 tex 从 LaTeX 抽取。
      verified_papers: D1 自动核验通过的文献 id 数组 JSON 字符串
        （来自 mcp__sci-verify__verify_papers 的 verified 项）。
      manually_confirmed: 人工已确认/待复核的文献 id 数组 JSON（中文期刊等 D1 免入项），
        这些会被标 accepted_unverified（非幻觉、待人工复核），而非 phantom。
      tex: 可选，LaTeX 源码字符串；若提供则从 \\cite/\\citep/\\citet 中抽取引用键并合并。

    返回 JSON：
      {"all_verified":bool,"n_citations":N,"n_verified":V,"n_accepted_unverified":A,
       "n_phantom":P,"citations":[{"key","status":"verified|accepted_unverified|phantom"}]}
      任何 phantom（幽灵引用）必须修正/剔除后才可成稿。
    """
    try:
        explicit = json.loads(input_json) if input_json else []
        vps = json.loads(verified_papers) if verified_papers else []
        mcs = json.loads(manually_confirmed) if manually_confirmed else []
    except Exception as e:
        return json.dumps({"all_verified": False, "citations": [], "error": f"input_unreadable: {e}"},
                         ensure_ascii=False)
    keys = list(explicit)
    if tex:
        keys.extend(cl.extract_cite_keys(tex))
    report = cl.lint_citations(keys, verified_papers=vps, manually_confirmed=mcs)
    return json.dumps(report, ensure_ascii=False, indent=2)


@mcp.tool()
def get_journal_rank(publication_name: str) -> str:
    """查询推荐期刊在 EasyScholar 的等级/分区，用于期刊推荐时"标注推荐期刊的具体信息"，
    让期刊等级/分区可溯源、不靠模型记忆编造（反幻觉·期刊信息层）。

    参数:
      publication_name: 期刊名称（中英文均可，如 "Talanta" 或 "光谱学与光谱分析"）。
        内部已做 URL 编码，调用方无需自行 encode。

    返回 JSON：
      {"ok":true,
       "data":{"official_all":{字段:等级,...},"official_select":{...},
               "custom":[{"dataset","rank","raw_rank"}]},
       "summary":"官方: sci=Q1 · ssci=... | 自定义: 国自然管科=A"}
      失败：{"ok":false,"error":"...","code"?}

    重要边界：期刊"是否存在"仍由 D1（sci-verify.verify_papers / OpenAlex）把关；
    本工具只负责"等级/分区"这一层信息的真实性与溯源。两者叠用 =
    推荐期刊存在性 + 期刊等级 都来自真实接口。
    """
    res = jr.query_publication_rank(publication_name)
    return json.dumps(res, ensure_ascii=False, indent=2)


@mcp.tool()
def verify_source_span(pdf_path: str, page: int, value: str | None = None,
                       claim_text: str | None = None,
                       evidence_type: str = "auto") -> str:
    """D4 原页理解 grounding：核对模型从 PDF 某页读出的数值/声明是否真实落在文本层，
    拦截书生读图/读表的末位/位序误读与长回答前后矛盾（见 lit-review 实测教训 #5/#6）。

    参数:
      pdf_path: PDF 文件路径（绝对或相对）。
      page: 页码（从 1 开始）。
      value: 可选，模型声明的数值（数字或含单位字符串如 "218.61 kcal/kg"）；
        提取其中数字与该页文本层数字做容忍度比对（默认 1% 相对 + 0.01 绝对，与 D2 一致）。
      claim_text: 可选，模型声明的文本片段（如 "缓解分布差异"）；在文本层做子串比对。
      evidence_type: "auto"(默认) | "text" | "table" | "figure"。
        auto 时由是否命中文本层推断：命中→文本/表格支持(grounded_text)；
        未命中且声明 figure→figure_derived_requires_human（图中数值文本层查不到，交人工复核）；
        未命中且未声明 figure→figure_suspected（疑似来自图，需人工复核）。

    返回 JSON：
      {"ok":true,
       "status":"grounded_text|value_not_in_text_layer|figure_derived_requires_human|
                 claim_not_in_text_layer|page_out_of_range|pdf_unreadable",
       "evidence_type_detected":"text|figure|...",
       "found_at":..., "page_text_excerpt":...}
    调用时机：lit-review Step 4 结构化抽取协议——任何"来自正文/表格文本层"的声明，
    落库前先用本工具核一次；来自图的声明标 evidence_type="figure" 交人工双读复核。
    """
    res = sg.verify_source_span(pdf_path, page, value=value, claim_text=claim_text,
                                evidence_type=evidence_type)
    return json.dumps(res, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()
