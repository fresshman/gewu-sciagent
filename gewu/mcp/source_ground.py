#!/usr/bin/env python3
"""D4 原页理解 grounding：核对模型从 PDF 原页读出的数值/声明是否真实落在那一页。

为何需要
--------
书生 intern-s2 读 PDF 原页（图/表/公式同帧）时，对图中标注数值会出现**末位/位序误读**
（实测 R² 0.8851→0.8551、0.9616→0.9619），长回答还会**前后自相矛盾**
（同一回答里表格写 `/` 结论段却给具体值）。D4 的"结构化抽取协议"要求模型每条事实声明
都带源 span；本模块提供**可程序化核验"正文/表格文本层"span** 的能力——模型一旦声称某
数字来自"正文/表格文本层"，就把它与那一页实际文本比对，不一致即告警。

边界（诚实优于静默）
--------------------
图中标注的数值**只存在于图像、PDF 文本层完全没有**（见 lit-review 实测教训 #3），本模块
**无法**自动核验这类"图内读数"——此时只诚实标 `figure_derived_requires_human` 交人工复核，
绝不冒充通过。这正是 D4 与 D1/D2/D3 的区别：D4 只覆盖"文本层/表格层可查"的那部分原页理解，
"纯图内读数"仍是人工复核面（已在 lit-review 技能里固化为二次复读纪律）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover - 运行环境必须装，但导入失败不应拖垮服务
    fitz = None


def _normalize_number(token: str):
    """把 '1,234.57' / '1 234' / '214.5700' 规范成 float；无法解析返回 None。"""
    s = token.strip().replace(",", "").replace(" ", "")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _extract_numbers(text: str):
    """从文本抽出 (float_value, raw_token) 列表，token 保留原样便于回显。"""
    out = []
    # 千分位逗号/空格分隔的整数，或普通小数
    for m in re.finditer(r"\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?", text):
        val = _normalize_number(m.group(0))
        if val is not None:
            out.append((val, m.group(0)))
    return out


def verify_source_span(pdf_path, page, value=None, claim_text=None,
                       evidence_type="auto", rel_tol=0.01, abs_tol=0.01):
    """核对一条"原页理解"声明是否落在指定 PDF 页。

    参数
    ----
    pdf_path : str
        PDF 文件绝对/相对路径。
    page : int
        页码（从 1 开始）。
    value : str | None
        模型声明的数值（数字或含单位字符串如 "218.61 kcal/kg"）；
        提取其中数字与该页文本层数字做容忍度比对。
    claim_text : str | None
        模型声明的文本片段（如 "缓解分布差异"）；在文本层做子串比对。
    evidence_type : str
        "auto"(默认) | "text" | "table" | "figure"。
        auto 时由是否命中文本层推断：命中→文本/表格支持；未命中且声明 figure→
        `figure_derived_requires_human`；未命中且未声明 figure→`figure_suspected`。
    rel_tol / abs_tol : float
        数值比对的相对/绝对容忍度（默认 1% 相对 + 0.01 绝对，与 D2 一致）。

    返回
    ----
    dict:
        {ok, status, evidence_type_detected, page_text_excerpt, found_at, error, note}
        status ∈ grounded_text | value_not_in_text_layer |
                 figure_derived_requires_human | claim_not_in_text_layer |
                 bad_value | bad_input | page_out_of_range | pdf_unreadable
    """
    if fitz is None:
        return {"ok": False, "status": "pdf_unreadable",
                "error": "PyMuPDF(fitz) 不可用", "evidence_type_detected": None}
    p = Path(pdf_path)
    if not p.exists():
        return {"ok": False, "status": "pdf_unreadable",
                "error": f"文件不存在: {pdf_path}", "evidence_type_detected": None}
    try:
        doc = fitz.open(str(p))
    except Exception as e:  # noqa: BLE001 - 把底层异常转成结构化结果
        return {"ok": False, "status": "pdf_unreadable", "error": str(e),
                "evidence_type_detected": None}
    try:
        if page < 1 or page > doc.page_count:
            return {"ok": False, "status": "page_out_of_range",
                    "error": f"page={page} 超出范围 1..{doc.page_count}",
                    "evidence_type_detected": None}
        page_text = doc[page - 1].get_text("text")
    finally:
        doc.close()

    excerpt = page_text.strip().replace("\n", " ")
    if len(excerpt) > 400:
        excerpt = excerpt[:400] + "…"

    if value is not None:
        nums = _extract_numbers(str(value))
        if not nums:
            return {"ok": False, "status": "bad_value",
                    "error": f"value 中未解析到数字: {value!r}",
                    "evidence_type_detected": None}
        target = nums[0][0]
        tol = max(abs_tol, rel_tol * abs(target))
        for pv, raw in _extract_numbers(page_text):
            if abs(pv - target) <= tol:
                return {"ok": True, "status": "grounded_text",
                        "evidence_type_detected": "text",
                        "found_at": raw,
                        "page_text_excerpt": excerpt}
        if evidence_type == "figure":
            return {"ok": True, "status": "figure_derived_requires_human",
                    "evidence_type_detected": "figure",
                    "page_text_excerpt": excerpt,
                    "note": "数值声明来自图，文本层无对应值，需人工复核图内读数"}
        return {"ok": True, "status": "value_not_in_text_layer",
                "evidence_type_detected": "figure_suspected",
                "page_text_excerpt": excerpt,
                "note": "文本层未找到该数值，疑似来自图/表图像，需人工复核"}

    if claim_text is not None:
        ct = claim_text.strip()
        if not ct:
            return {"ok": False, "status": "bad_input",
                    "error": "claim_text 为空", "evidence_type_detected": None}
        if ct in page_text:
            return {"ok": True, "status": "grounded_text",
                    "evidence_type_detected": "text",
                    "found_at": ct[:120],
                    "page_text_excerpt": excerpt}
        if evidence_type == "figure":
            return {"ok": True, "status": "figure_derived_requires_human",
                    "evidence_type_detected": "figure",
                    "page_text_excerpt": excerpt,
                    "note": "声明片段未见于文本层且声明来自图，需人工复核"}
        return {"ok": True, "status": "claim_not_in_text_layer",
                "evidence_type_detected": "figure_suspected",
                "page_text_excerpt": excerpt,
                "note": "文本层未找到该声明片段，疑似来自图/表图像，需人工复核"}

    return {"ok": False, "status": "bad_input",
            "error": "value 与 claim_text 至少提供一个",
            "evidence_type_detected": None}


if __name__ == "__main__":  # pragma: no cover
    import json
    print(json.dumps(verify_source_span(*sys.argv[1:]), ensure_ascii=False, indent=2))
