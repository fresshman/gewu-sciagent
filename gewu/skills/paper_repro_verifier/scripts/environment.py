"""Reproducible environment snapshot (no secrets, no invented software state)."""
from __future__ import annotations

import importlib.metadata as md
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from common import now_iso

TRACKED_PACKAGES = (
    "numpy", "scipy", "pandas", "scikit-learn", "torch", "tensorflow", "jax",
    "matplotlib", "pillow", "statsmodels", "sympy", "networkx", "xgboost",
    "lightgbm", "pypdf", "PyPDF2", "pdfplumber", "PyMuPDF", "pytest",
    "transformers", "datasets", "opencv-python", "seaborn", "numba",
)
# Names only: values may contain credentials and are never written down.
SAFE_ENV_NAMES = (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "CUDA_VISIBLE_DEVICES",
    "PYTHONHASHSEED", "PYTHONPATH", "CONDA_DEFAULT_ENV", "VIRTUAL_ENV",
    "TF_DETERMINISTIC_OPS", "CUBLAS_WORKSPACE_CONFIG",
)


def _versions() -> dict:
    out = {}
    for name in TRACKED_PACKAGES:
        try:
            out[name] = md.version(name)
        except md.PackageNotFoundError:
            continue
        except Exception:
            continue
    return out


def _gpu() -> dict:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {"status": "not_probed", "note": "nvidia-smi unavailable"}
    try:
        p = subprocess.run([exe, "--query-gpu=name,driver_version,memory.total",
                            "--format=csv,noheader"], capture_output=True, timeout=20)
        return {"status": "ok" if p.returncode == 0 else "error",
                "raw": p.stdout.decode("utf-8", "replace").strip()[:500]}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "note": f"{type(exc).__name__}: {exc}"}


def build() -> dict:
    versions = _versions()
    env_names = {k: ("set" if os.environ.get(k) else "unset") for k in SAFE_ENV_NAMES}
    seeds = {"python_hashseed": os.environ.get("PYTHONHASHSEED") or "unset",
             "note": "model/library seeds must be read from the actual config/code; "
                     "this field does not guess them"}
    snap = {
        "generated_at": now_iso(),
        "python": {"version": sys.version.split()[0], "implementation": platform.python_implementation(),
                   "executable": sys.executable, "bits": 64 if sys.maxsize > 2 ** 32 else 32},
        "platform": {"system": platform.system(), "release": platform.release(),
                     "machine": platform.machine(), "processor": platform.processor() or "unknown"},
        "cpu_count": os.cpu_count(),
        "installed_packages": versions,
        "n_packages_detected": len(versions),
        "threading_env": env_names,
        "seeds": seeds,
        "gpu": _gpu(),
        "secrets_policy": "only environment variable NAMES are recorded, never values",
    }
    lines = ["#!/usr/bin/env bash", "# Rebuild hint generated from the ACTUAL run environment.",
             "# Versions are those detected at runtime; pin them in your own lockfile.",
             f"# python {snap['python']['version']} ({snap['platform']['system']}/{snap['platform']['machine']})"]
    if versions:
        pins = " ".join(f"{k}=={v}" for k, v in sorted(versions.items()))
        lines.append(f"# pip install {pins}")
    lines.append("# Then run the exact command recorded in repro/execution.json")
    snap["rebuild_hint"] = "\n".join(lines) + "\n"
    return snap


_VERSION_RX = re.compile(
    r"(?:^|\s)(numpy|scipy|pandas|scikit-learn|sklearn|torch|pytorch|tensorflow|"
    r"matplotlib|python|jax|transformers|opencv|pillow)\s*"
    r"(?:version\s*)?(?:==|>=|~=|v)?\s*(\d+\.\d+(?:\.\d+)?)", re.I)


def compare_to_paper(index: dict, snap: dict) -> dict:
    """Find dependency/version statements in PAPER text only and flag mismatches."""
    from common import PAPER_ROLES
    claims = []
    for doc in index.get("documents", []):
        if doc.get("role") not in PAPER_ROLES:
            continue
        for pg in doc.get("pages", []):
            for ln, line in enumerate(pg.get("lines", []), 1):
                for m in _VERSION_RX.finditer(line):
                    claims.append({"package": m.group(1).lower(), "paper_version": m.group(2),
                                   "evidence": {"source": doc["path"], "page": pg["page"],
                                                "line": ln, "quote": line.strip()[:200]}})
    alias = {"sklearn": "scikit-learn", "pytorch": "torch", "opencv": "opencv-python"}
    found = snap["installed_packages"]
    mismatches = []
    for c in claims:
        name = alias.get(c["package"], c["package"])
        actual = found.get(name)
        if name == "python":
            actual = snap["python"]["version"]
        if actual is None:
            mismatches.append({**c, "actual": None, "status": "not_installed",
                               "note": "declared in paper but absent from this environment"})
        elif not actual.startswith(c["paper_version"]):
            mismatches.append({**c, "actual": actual, "status": "version_mismatch"})
        else:
            mismatches.append({**c, "actual": actual, "status": "consistent"})
    return {"n_claims": len(claims), "checks": mismatches[:80],
            "note": "regex-based extraction; every hit keeps its page/line locator for review"}
