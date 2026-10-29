#!/usr/bin/env python3
"""PDF 处理工具：元信息提取 + 全文文本提取。
供 proxy/server.mjs 通过子进程调用。
"""
import json
import sys
import re
from pathlib import Path

import pymupdf


def extract_metadata(pdf_path: str) -> dict:
    """提取 PDF 元信息：标题、作者、摘要、DOI、期刊等。"""
    doc = pymupdf.open(pdf_path)
    meta = doc.metadata or {}

    title = (meta.get("title") or "").strip()
    authors = (meta.get("author") or "").strip()
    subject = (meta.get("subject") or "").strip()

    # 从首页提取摘要（通常在前 2 页）
    abstract = ""
    for page_idx in range(min(2, len(doc))):
        page = doc[page_idx]
        text = page.get_text()
        # 匹配 "Abstract" 或 "ABSTRACT" 开头的段落
        m = re.search(
            r"(?:Abstract|ABSTRACT|摘要)\s*[:：]?\s*\n?(.+?)(?:\n\n|\n1\.|\nIntroduction|\nINTRODUCTION)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if m:
            abstract = m.group(1).strip()
            break

    # 尝试从文本中提取 DOI
    doi = ""
    for page_idx in range(min(3, len(doc))):
        page = doc[page_idx]
        text = page.get_text()
        m = re.search(r"10\.\d{4,9}/\S+", text)
        if m:
            doi = m.group(0).strip()
            break

    # 提取大纲（目录）
    toc = []
    raw_toc = doc.get_toc()
    for level, title_item, page in raw_toc[:50]:  # 最多 50 条
        toc.append({"level": level, "title": title_item.strip(), "page": page})

    # 统计
    page_count = len(doc)
    word_count = sum(len(doc[i].get_text().split()) for i in range(page_count))

    doc.close()

    return {
        "title": title or Path(pdf_path).stem,
        "authors": authors,
        "abstract": abstract[:2000] if abstract else "",
        "doi": doi,
        "subject": subject,
        "page_count": page_count,
        "word_count": word_count,
        "toc": toc,
    }


def extract_text(pdf_path: str, max_pages: int = 0) -> str:
    """提取 PDF 全文文本，可选限制页数。"""
    doc = pymupdf.open(pdf_path)
    pages = range(len(doc)) if max_pages <= 0 else range(min(max_pages, len(doc)))
    texts = []
    for i in pages:
        texts.append(doc[i].get_text())
    doc.close()
    return "\n\n".join(texts)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: pdf_tool.py <metadata|text> <pdf_path> [max_pages]"}))
        sys.exit(1)

    cmd = sys.argv[1]
    pdf_path = sys.argv[2]

    if not Path(pdf_path).exists():
        print(json.dumps({"error": f"file not found: {pdf_path}"}))
        sys.exit(1)

    if cmd == "metadata":
        result = extract_metadata(pdf_path)
    elif cmd == "text":
        max_pages = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        result = {"text": extract_text(pdf_path, max_pages)}
    else:
        print(json.dumps({"error": f"unknown command: {cmd}"}))
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False))
