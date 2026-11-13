"""Shared primitives for paper-repro-verifier.

Standard library only. All writes are atomic UTF-8 JSON so a crashed run still
leaves honest partial deliverables behind.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:  # keep stdout usable on Windows consoles with a legacy codepage
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

STATUS = ("success", "partial", "failed", "indeterminate")
GRADE = ("reproduced", "partially_reproduced", "not_reproducible", "indeterminate")
SOURCE_CLASS = ("paper_explicit", "code_inferred", "self_set", "unresolved")
ATTRIBUTION = ("environment", "data", "implementation", "specification", "stochastic")

# Which discovered files may legitimately be used as *paper claims*.
# Code, configs and result files must never be mined as if they were the paper.
PAPER_ROLES = frozenset({
    "document_pdf", "latex_source", "paper_main", "supplement",
    "markdown", "text", "bibliography",
})
RESULT_ROLES = frozenset({
    "results", "predictions", "data", "data_or_config", "evaluation_script", "log",
})
# Case metadata is not scientific material.
META_FILENAMES = frozenset({"case.json", "task.md", "resources.yaml", "environment.yaml"})


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n",
                   encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - honest degradation is the point
        return default if default is not None else {"_read_error": f"{type(exc).__name__}: {exc}"}


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def evidence(source: str, *, page=None, section=None, quote=None, line=None,
             field=None, confidence=None) -> dict:
    """One evidence locator. Only fields actually obtained are kept."""
    d = {"source": source}
    for k, v in (("page", page), ("section", section), ("quote", quote),
                 ("line", line), ("field", field), ("confidence", confidence)):
        if v is not None and v != "":
            d[k] = v
    return d


def missing(item: str, reason: str, *, kind="missing_input", takeover=None) -> dict:
    d = {"item": item, "reason": reason, "kind": kind}
    if takeover:
        d["takeover"] = takeover
    return d


class RunLog:
    """Append-only JSONL trace of every automated step."""

    def __init__(self, out: Path):
        self.path = out / "repro" / "run_log.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._n = 0

    def step(self, name: str, status: str, **kw) -> None:
        self._n += 1
        rec = {"seq": self._n, "ts": now_iso(), "step": name, "status": status, **kw}
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def guarded(self, name: str, fn):
        t0 = time.time()
        try:
            result = fn()
            self.step(name, "ok", elapsed_s=round(time.time() - t0, 3))
            return result
        except Exception as exc:  # noqa: BLE001
            self.step(name, "error", elapsed_s=round(time.time() - t0, 3),
                      error=f"{type(exc).__name__}: {exc}")
            return None


def load_case(case_path: Path | None) -> dict:
    """Read the real case file; never invent its shape."""
    if not case_path or not case_path.exists():
        return {"_status": "missing", "_note": "case.json not provided; contract inferred as empty"}
    d = read_json(case_path, {})
    if not isinstance(d, dict):
        return {"_status": "invalid", "_note": f"case.json root is {type(d).__name__}, expected object"}
    return d


def case_id_of(case: dict, case_path: Path | None) -> str:
    for key in ("case_id", "id", "caseId", "case"):
        v = case.get(key)
        if isinstance(v, (str, int)) and str(v).strip():
            return str(v)
    return (case_path.stem if case_path else "unknown_case")


def contract_fields(case: dict) -> tuple[list[str], str]:
    """Extract output_contract field names from any of three shapes.

    Returns (field_names, shape_note). Never hardcodes domain fields.
    """
    for key in ("output_contract", "outputContract", "expected_fields",
                "result_fields", "fields", "required_fields"):
        c = case.get(key)
        if c is None:
            continue
        if isinstance(c, list):
            names = [x if isinstance(x, str) else (x.get("name") or x.get("key"))
                     for x in c if isinstance(x, (str, dict))]
            return [n for n in names if n], f"list:{key}"
        if isinstance(c, dict):
            # JSON-Schema-like {"properties": {...}} or plain {field: hint}
            props = c.get("properties") if isinstance(c.get("properties"), dict) else c
            names = [k for k in props if isinstance(k, str) and not k.startswith("$")]
            return names, f"dict:{key}"
        if isinstance(c, str):
            return [s.strip() for s in c.split(",") if s.strip()], f"str:{key}"
    return [], "absent"
