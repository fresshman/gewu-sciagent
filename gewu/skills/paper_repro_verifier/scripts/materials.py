"""Reproduction materials ledger: what exists, where it came from, what is missing.

The checklist is deliberately explicit about *categories that were not found*;
silently skipping a missing dataset or evaluation script is the failure mode
this module exists to prevent.
"""
from __future__ import annotations

from pathlib import Path

from common import now_iso, rel, sha256_file

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
             ".idea", ".vscode", "dist", "build", ".pytest_cache", ".hyperframes",
             ".aris", "repro", "work", "output", "outputs"}
MAX_FILES = 4000

CODE_EXT = {".py", ".ipynb", ".r", ".m", ".jl", ".sh", ".bat", ".ps1", ".cpp", ".c", ".java"}
FIGURE_EXT = {".png", ".jpg", ".jpeg", ".svg", ".eps", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
LOG_EXT = {".log", ".out"}
DATA_EXT = {".csv", ".tsv", ".npy", ".npz", ".parquet", ".xlsx", ".h5", ".hdf5"}
CONFIG_EXT = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".lock"}
# Files whose NAME is their identity, checked before the extension rule.
SPECIAL_NAMES = {
    "requirements.txt": "dependency_manifest", "pyproject.toml": "dependency_manifest",
    "environment.yml": "dependency_manifest", "environment.yaml": "dependency_manifest",
    "package.json": "dependency_manifest", "setup.py": "dependency_manifest",
    "poetry.lock": "dependency_lock", "uv.lock": "dependency_lock",
    "pipfile.lock": "dependency_lock", "license": "license", "license.md": "license",
    "license.txt": "license", "copying": "license", "copying.md": "license",
    "dockerfile": "environment_manifest", "makefile": "build_manifest",
}
PAPERISH_WORDS = ("main", "paper", "manuscript", "thesis", "article")
SUPP_WORDS = ("supplement", "appendix", "si_", "supp")
FIGURE_WORDS = ("fig", "plot", "fold", "probe", "curve", "scatter", "hist", "pred_true", "rmse_")

REQUIRED_CATEGORIES = {
    "paper": ["document_pdf", "latex_source", "markdown", "text",
              "paper_main", "supplement"],
    "code_or_script": ["code", "notebook", "script", "evaluation_script"],
    "data": ["data", "predictions", "results"],
    "dependency": ["dependency_manifest", "dependency_lock", "environment_manifest"],
    "license": ["license"],
    "parameter_source": ["parameter_source", "config"],
    "evaluation": ["evaluation_script"],
}


def classify(path: Path) -> str:
    """Extension fixes the broad class; the name may only refine WITHIN it.

    This ordering matters: a file called `verify_paper_recompute.py` is still
    code, and a one-page `coal_5fold_rmse.pdf` is still a figure, not the paper
    or a result table. Naive keyword matching gets both wrong.
    """
    n = path.name.lower()
    if n in SPECIAL_NAMES:
        return SPECIAL_NAMES[n]
    if path.suffix.lower() == ".lock":
        return "dependency_lock"
    ext = path.suffix.lower()

    if ext in CODE_EXT:
        if ext == ".ipynb":
            return "notebook"
        if ext in (".sh", ".bat", ".ps1"):
            return "script"
        if any(k in n for k in ("eval", "metric", "score", "verify")):
            return "evaluation_script"
        return "code"
    if ext in FIGURE_EXT:
        return "figure"
    if ext in LOG_EXT:
        return "log"
    if ext == ".pdf":
        if any(k in n for k in SUPP_WORDS):
            return "supplement"
        if any(k in n for k in FIGURE_WORDS):
            return "figure_pdf"       # never used as a paper claim source
        if any(k in n for k in PAPERISH_WORDS):
            return "paper_main"
        return "document_pdf"
    if ext == ".tex":
        if any(k in n for k in SUPP_WORDS):
            return "supplement"
        if any(k in n for k in PAPERISH_WORDS):
            return "paper_main"
        return "latex_source"
    if ext == ".md":
        return "readme" if n.startswith("readme") else "markdown"
    if ext == ".txt":
        return "text"
    if ext == ".bib":
        return "bibliography"
    if ext in DATA_EXT:
        return "data"
    if ext in CONFIG_EXT:
        if any(k in n for k in ("metric", "result", "fold", "predict", "score", "eval")):
            return "results"
        if any(k in n for k in ("param", "hparam", "setting", "config")):
            return "config"
        return "data_or_config"
    return "other"


def discover(roots: list[Path]) -> tuple[list[Path], list[str]]:
    seen, warnings = set(), []
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            warnings.append(f"input root does not exist: {root}")
            continue
        if root.is_file():
            candidates = [root]
        else:
            candidates = []
            for p in root.rglob("*"):
                # Only apply the blacklist to path parts RELATIVE to the input
                # root. Checking absolute parts would silently discard an input
                # root that itself lives under a directory named e.g. "output".
                try:
                    rel_parts = p.relative_to(root).parts[:-1]
                except ValueError:
                    continue
                if any(part in SKIP_DIRS for part in rel_parts):
                    continue
                if p.name.startswith("."):
                    continue
                if p.is_file():
                    candidates.append(p)
                if len(candidates) >= MAX_FILES:
                    warnings.append(f"file cap {MAX_FILES} reached under {root}")
                    break
        for p in candidates:
            key = str(p.resolve())
            if key not in seen:
                seen.add(key)
                files.append(p)
    return sorted(files), warnings


def build(roots: list[Path], base: Path, *, hash_limit_mb: int = 8) -> dict:
    files, warnings = discover(roots)
    items, roles = [], {}
    for p in files:
        try:
            st = p.stat()
            role = classify(p)
            item = {"path": rel(p, base), "role": role, "size_bytes": st.st_size,
                    "ext": p.suffix.lower(), "present": True}
            if st.st_size <= hash_limit_mb * 1024 * 1024:
                item["sha256"] = sha256_file(p)
            else:
                item["sha256"] = None
                item["sha256_note"] = f"skipped: >{hash_limit_mb} MiB"
            items.append(item)
            roles.setdefault(role, []).append(item["path"])
        except OSError as exc:
            warnings.append(f"stat failed for {p}: {exc}")

    gaps = []
    for category, acceptable in REQUIRED_CATEGORIES.items():
        hits = [p for r in acceptable for p in roles.get(r, [])]
        entry = {"category": category, "status": "found" if hits else "missing",
                 "evidence_paths": hits[:8]}
        if not hits:
            entry["reason"] = "no file of this category found in the provided inputs"
            entry["takeover"] = ("ask the operator for this artifact, or record it as "
                                 "restricted/unpublished; do not substitute synthetic data")
        gaps.append(entry)

    version_hints = []
    for p in files:
        if p.name.lower() in ("requirements.txt", "pyproject.toml", "package.json",
                              "environment.yml", "poetry.lock", "uv.lock"):
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")[:4000]
                version_hints.append({"path": rel(p, base), "excerpt": txt})
            except OSError:
                pass

    return {
        "generated_at": now_iso(),
        "input_roots": [str(r) for r in roots],
        "n_files": len(items),
        "items": items,
        "by_role": {k: v[:30] for k, v in sorted(roles.items())},
        "checklist": gaps,
        "version_hints": version_hints,
        "warnings": warnings,
        "how_to_use": "Tick checklist items against the PDF/code. Every 'missing' must also "
                      "appear in result.json uncertainty; never infer a missing dataset.",
    }
