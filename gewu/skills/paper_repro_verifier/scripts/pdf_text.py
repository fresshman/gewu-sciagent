"""Page-aware text extraction with honest degradation.

Backends are probed in order; whichever actually works is recorded in the
output. A PDF with no text layer is reported as `needs_ocr`, never as empty
content that could be mistaken for "the paper says nothing".
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

TEXT_EXT = {".txt", ".md", ".tex", ".json", ".yaml", ".yml", ".csv", ".py", ".log", ".bib"}
PDF_EXT = {".pdf"}


def _pdftotext(path: Path):
    exe = shutil.which("pdftotext")
    if not exe:
        return None
    try:
        p = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(path), "-"],
                           capture_output=True, timeout=90)
        if p.returncode != 0:
            return None
        pages = p.stdout.decode("utf-8", "replace").split("\f")
        pages = [x for x in pages if x.strip()]
        return (pages, "pdftotext") if pages else None
    except Exception:
        return None


def _pypdf(path: Path):
    for mod in ("pypdf", "PyPDF2"):
        try:
            lib = __import__(mod)
            reader = lib.PdfReader(str(path))
            pages = [(pg.extract_text() or "") for pg in reader.pages]
            if any(x.strip() for x in pages):
                return pages, f"{mod}"
        except Exception:
            continue
    return None


def _pdfplumber(path: Path):
    try:
        import pdfplumber  # type: ignore
        with pdfplumber.open(str(path)) as pdf:
            pages = [(pg.extract_text() or "") for pg in pdf.pages]
        if any(x.strip() for x in pages):
            return pages, "pdfplumber"
    except Exception:
        pass
    return None


def _fitz(path: Path):
    try:
        import fitz  # type: ignore
        with fitz.open(str(path)) as doc:
            pages = [pg.get_text() for pg in doc]
        if any(x.strip() for x in pages):
            return pages, "pymupdf"
    except Exception:
        pass
    return None


def extract(path: Path) -> dict:
    """Return {status, backend, pages:[{page,text,lines,n_chars}], note}."""
    ext = path.suffix.lower()
    if ext in TEXT_EXT:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return {"status": "unreadable", "backend": None, "pages": [],
                    "note": f"{type(exc).__name__}: {exc}"}
        lines = text.splitlines()
        return {"status": "ok", "backend": "plain-text", "pages": [
            {"page": 1, "text": text, "lines": lines, "n_chars": len(text)}],
            "note": "plain text file; page=1 denotes the whole file"}
    if ext not in PDF_EXT:
        return {"status": "unsupported", "backend": None, "pages": [],
                "note": f"no text extractor for {ext}; binary kept as material only"}
    result = None
    for fn in (_pdftotext, _pypdf, _pdfplumber, _fitz):
        result = fn(path)
        if result:
            break
    if not result:
        return {"status": "needs_ocr", "backend": None, "pages": [],
                "note": "no usable PDF text backend and/or no embedded text layer; "
                        "try OCR (tesseract) and record the command; do NOT guess content"}
    raw_pages, backend = result
    pages = []
    for i, text in enumerate(raw_pages, 1):
        pages.append({"page": i, "text": text,
                      "lines": [ln.rstrip() for ln in text.splitlines()],
                      "n_chars": len(text)})
    return {"status": "ok", "backend": backend, "pages": pages, "note": ""}


def build_index(paths: list[Path], root: Path, *, max_chars: int = 120000,
                roles: dict | None = None, meta_names: set | None = None) -> dict:
    """Build a page/line level evidence index across all readable documents.

    `roles` maps relative path -> material role so downstream consumers can
    restrict *claims* to paper-like documents and never mistake a result file
    for the paper. Case metadata files are explicitly excluded.
    """
    from common import META_FILENAMES, now_iso, rel
    import materials
    skip = set(meta_names or META_FILENAMES)
    docs = []
    for p in paths:
        if p.name.lower() in skip:
            continue
        relpath = rel(p, root)
        role = (roles or {}).get(relpath) or materials.classify(p)
        r = extract(p)
        docs.append({"path": relpath, "abs_path": str(p), "role": role,
                     "status": r["status"],
                     "backend": r["backend"], "n_pages": len(r["pages"]),
                     "note": r["note"],
                     "pages": [{"page": pg["page"], "n_chars": pg["n_chars"],
                                "lines": pg["lines"]} for pg in r["pages"]]})
    used = sum(sum(len("\n".join(pg["lines"])) for pg in d["pages"]) for d in docs)
    return {"generated_at": now_iso(),
            "backend_note": "pages[] holds line-numbered text; line index is 1-based",
            "claim_policy": "only documents whose role is in PAPER_ROLES may supply paper claims",
            "truncated": used > max_chars, "total_chars": used, "documents": docs}


def locate(index: dict, query: str, *, max_hits: int = 20) -> list[dict]:
    """Keyword/regex search over the index, returning precise locators."""
    try:
        rx = re.compile(query, re.I)
    except re.error:
        rx = re.compile(re.escape(query), re.I)
    hits = []
    for d in index.get("documents", []):
        for pg in d.get("pages", []):
            for lineno, line in enumerate(pg.get("lines", []), 1):
                if rx.search(line):
                    hits.append({"source": d["path"], "page": pg["page"],
                                 "line": lineno, "quote": line.strip()[:300]})
                    if len(hits) >= max_hits:
                        return hits
    return hits
