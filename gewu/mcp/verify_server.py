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


if __name__ == "__main__":
    mcp.run()
