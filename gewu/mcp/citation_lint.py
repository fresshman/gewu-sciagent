#!/usr/bin/env python3
"""D3 — 引用完整性 lint（领域无关，反幻觉横向防线之三）。

成稿末尾抽取全部引用键，逐一比对 D1 已核验文献集合，拦截"幽灵引用"
（指向未核验 / 不存在文献的 \\cite）。

关键降级策略（P1-2）：中文文献（CNKI/万方）OpenAlex/CrossRef 不收录，D1 无法自动核验。
按 P1-2，这类引用**绝不静默通过**，也不该被误判为幻觉——应显式标
`accepted_unverified`（已人工确认 / 待人工核验清单），与"从未出现过的幽灵引用
`phantom`"区分开。故 lint 接受两个集合：
  verified_papers     — D1 自动核验通过的文献 id（来自 verify_papers）
  manually_confirmed  — 用户/人工已确认、但 D1 无法自动核验的文献（如中文期刊），
                        产出"人工核验清单"交用户

状态枚举：
    verified           — 在 D1 已核验集合内，可信
    accepted_unverified— 在人工确认集合内（中文等 D1 免入），待人工复核，非幻觉
    phantom            — 既不在 D1 也不在人工确认集合，幽灵引用，必须修正/剔除
"""
from __future__ import annotations

import re
from typing import Iterable

# 覆盖常见 LaTeX 引用命令：\cite \citep \citet \autocite \footcite \textcite 等
_CITE_RE = re.compile(
    r"\\(?:cite|citep|citet|autocite|footcite|textcite|parencite)"
    r"(?:\[[^\]]*\])?\{",
    re.IGNORECASE,
)


def extract_cite_keys(tex: str) -> list[str]:
    """从 LaTeX 文本抽取全部引用键（如 \\cite{a, b}\\citep{c} → ['a','b','c']）。"""
    keys: list[str] = []
    for m in _CITE_RE.finditer(tex or ""):
        depth = 0
        i = m.end() - 1  # 指向 '{'
        buf = []
        while i < len(tex):
            ch = tex[i]
            if ch == "{":
                depth += 1
                if depth == 1:
                    i += 1
                    continue
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            if depth >= 1:
                buf.append(ch)
            i += 1
        for part in "".join(buf).split(","):
            k = part.strip()
            if k:
                keys.append(k)
    # 去重保序
    seen = set()
    out = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def lint_citations(
    citations: Iterable[str],
    verified_papers: Iterable[str] | None = None,
    manually_confirmed: Iterable[str] | None = None,
) -> dict:
    """比对引用键与 D1 已核验集合，返回逐条状态与汇总。

    citations         — 成稿中的引用键列表（也可先用 extract_cite_keys 从 .tex 抽取）
    verified_papers   — D1 自动核验通过的文献 id 集合
    manually_confirmed— 人工已确认 / 待人工复核的文献 id（中文等），标 accepted_unverified
    """
    vset = set(verified_papers or [])
    mset = set(manually_confirmed or [])
    rows = []
    for key in citations:
        key = str(key).strip()
        if not key:
            continue
        if key in vset:
            status = "verified"
        elif key in mset:
            status = "accepted_unverified"
        else:
            status = "phantom"
        rows.append({"key": key, "status": status})

    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    n_phantom = counts.get("phantom", 0)
    n_total = len(rows)
    n_real = n_total - n_phantom
    return {
        # 无幽灵引用、且无空引用，即视为通过（accepted_unverified 需人工复核但不阻断）
        "all_verified": (n_phantom == 0) and (n_total > 0),
        "n_citations": n_total,
        "n_verified": counts.get("verified", 0),
        "n_accepted_unverified": counts.get("accepted_unverified", 0),
        "n_phantom": n_phantom,
        "counts": counts,
        "citations": rows,
    }
