"""LaTeX 结构 lint（不依赖 TeX 发行版）。

编译不了的机器上，至少要保证源码**自洽**：环境配对、花括号平衡、`\\cite` 与
`\\bibitem` 一一对应、引用的图片真实存在。这些错误若流到评审手上，比"没编译"更难看。
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

# 中文文档若没加载 CJK 支持，XeLaTeX 会把每个汉字记成 Missing character 并直接丢弃，
# 结果是"编译成功但正文空白"——比编译报错更难发现，故在 lint 阶段就拦下。
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_DOCCLASS_RE = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{([^}]+)\}")

# 从 Markdown 模板改写时最容易漏进来的残留
_MARKDOWN_RESIDUE = [
    (re.compile(r"\*\*[^*\n]+\*\*"), "Markdown 粗体 **…**"),
    (re.compile(r"(?m)^#{1,6}\s+\S"), "Markdown 标题 #"),
    (re.compile(r"\[[^\]\n]+\]\([^)\n]+\)"), "Markdown 链接 [文本](url)"),
]


def _brace_balance(tex: str) -> tuple[int, int]:
    """返回 (结束深度, 过程中最小深度)；忽略转义括号与注释行。"""
    depth = 0
    min_depth = 0
    i = 0
    n = len(tex)
    while i < n:
        c = tex[i]
        if c == "\\":
            i += 2
            continue
        if c == "%":
            while i < n and tex[i] != "\n":
                i += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            min_depth = min(min_depth, depth)
        i += 1
    return depth, min_depth


def lint(tex: str, base_dir: Path | None = None) -> dict:
    begins = Counter(re.findall(r"\\begin\{([^}]+)\}", tex))
    ends = Counter(re.findall(r"\\end\{([^}]+)\}", tex))
    unbalanced = {
        k: {"begin": begins[k], "end": ends[k]}
        for k in set(begins) | set(ends)
        if begins[k] != ends[k]
    }

    depth, min_depth = _brace_balance(tex)

    cites = set()
    for m in re.findall(r"\\cite\{([^}]+)\}", tex):
        for k in m.split(","):
            cites.add(k.strip())
    bibs = set(re.findall(r"\\bibitem\{([^}]+)\}", tex))

    figures = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", tex)
    missing_figs = []
    for f in figures:
        if base_dir is None:
            base_dir = Path(".")
        if not (Path(base_dir) / f).exists():
            missing_figs.append(f)

    errors = []
    if unbalanced:
        errors.append(f"环境不配对: {unbalanced}")
    if depth != 0 or min_depth < 0:
        errors.append(f"花括号不平衡: 结束深度={depth}, 最小深度={min_depth}")
    if cites - bibs:
        errors.append(f"引用了不存在的文献: {sorted(cites - bibs)}")
    if bibs - cites:
        errors.append(f"文献未被引用: {sorted(bibs - cites)}")
    if missing_figs:
        errors.append(f"图片缺失: {missing_figs}")
    if not cites:
        errors.append("正文零引用")

    # 中文必须配 CJK 支持（否则 PDF 正文整篇空白）
    if _CJK_RE.search(tex):
        dcm = _DOCCLASS_RE.search(tex)
        dc = dcm.group(1) if dcm else ""
        has_cjk = ("ctex" in dc) or ("xeCJK" in tex) or (r"\usepackage{CJK" in tex)
        if not has_cjk:
            errors.append(
                f"中文正文但文档类 {dc or '未声明'} 未加载 ctex/xeCJK，"
                "XeLaTeX 下会整篇缺字（Missing character），PDF 无正文"
            )

    md_hits = []
    for pat, label in _MARKDOWN_RESIDUE:
        found = pat.findall(tex)
        if found:
            md_hits.append(f"{label} ×{len(found)}，首例：{found[0][:40]}")
    if md_hits:
        errors.append("LaTeX 源含 Markdown 残留: " + "；".join(md_hits))

    return {
        "ok": not errors,
        "errors": errors,
        "n_environments": sum(begins.values()),
        "n_cites": len(cites),
        "n_bibitems": len(bibs),
        "n_figures": len(figures),
        "brace_depth": depth,
    }
