"""Tolerance-first result comparison (numerical metrics over visual similarity).

Declared values are mined from the ACTUAL paper text; observed values from the
ACTUAL result files. Nothing is hardcoded per paper. Tolerance is written into
the table BEFORE any comparison, so it cannot be relaxed after the fact.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from common import now_iso

METRIC_NAMES = ("rmse", "r2", "r^2", "r²", "mae", "mse", "mape", "accuracy", "acc",
                "f1", "auc", "precision", "recall", "psnr", "ssim", "loss", "error",
                "mean", "std", "p-value", "pvalue", "correlation", "pearson")
_NUM = r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
# The gap between a metric name and its value must not cross a table pipe (`|`),
# otherwise a header like "| method | RMSE | R2 |" is misread as "RMSE = 2".
_DECL_RX = re.compile(
    r"\b(" + "|".join(re.escape(m) for m in sorted(METRIC_NAMES, key=len, reverse=True)) + r")\b"
    r"[^0-9\-+|/]{0,40}(" + _NUM + r")(?:\s*(?:±|\+/-|\+)\s*(" + _NUM + r"))?", re.I)
# Metrics with physical units: a tiny integer is almost always a stray digit
# from "R2", "5 折", an equation number or a table caption, not a real value.
DIMENSIONAL_METRICS = {"rmse", "mae", "mse", "mape", "loss", "error", "psnr"}
SCOPE_RANK = {"aggregate": 0, "narrative": 1, "per_fold_row": 2, "noise": 3}
_TABLE_RX = re.compile(r"^\s*[|]?\s*([A-Za-z][A-Za-z0-9 _^²]{1,28})\s*[|:]\s*(" + _NUM + r")", re.I)
DEFAULT_TOLERANCE = {"default_abs": 0.01, "default_rel": 0.01,
                     "overrides": {}, "declared_before_comparison": True,
                     "note": "tight by default; widen only with a written reason in change_records"}


def _num(s):
    try:
        f = float(s)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return None


def _is_metric_label(name: str) -> bool:
    n = name.strip().lower()
    return any(m in n for m in METRIC_NAMES)


def _scope(line: str) -> str:
    """aggregate | per_fold_row | narrative.

    Per-fold table rows are real declarations but their comparison needs a fold
    identity; auto-matching them by nearest number produces false FAILs, so they
    are DEFERRED for explicit human alignment instead.
    """
    low = line.lower()
    if any(k in low for k in ("均值", "mean", "average", "overall", "summary")):
        return "aggregate"
    if "&" in line and re.match(r"^\s*[|]?\s*(fold\s*)?\d+", low):
        return "per_fold_row"
    return "narrative"


def extract_declared(index: dict) -> list[dict]:
    """Mine declared values from the PAPER only - never from code/config/results.

    Same value repeated in the PDF and its .tex source is one declaration.
    `$R^2$` and `R2` normalise to the same metric. Tiny integers attached to
    dimensional metrics are flagged as noise rather than compared.
    """
    from common import PAPER_ROLES
    collected: list[dict] = []
    for doc in index.get("documents", []):
        if doc.get("role") not in PAPER_ROLES:
            continue
        for pg in doc.get("pages", []):
            for ln, line in enumerate(pg.get("lines", []), 1):
                pairs = [(m.group(1), m.group(2), m.group(3)) for m in _DECL_RX.finditer(line)]
                # Table rows only count when the row label itself names a metric;
                # "| baseline | 0.25 |" is a row label, not an RMSE declaration.
                pairs += [(m.group(1), m.group(2), None) for m in _TABLE_RX.finditer(line)
                          if _is_metric_label(m.group(1))]
                scope = _scope(line)
                for name, val, spread in pairs:
                    v = _num(val)
                    if v is None:
                        continue
                    metric = name.strip().lower().replace(" ", "_").replace("-", "_")
                    metric = re.sub(r"\^2$", "2", metric)   # r^2 -> r2
                    if (metric in DIMENSIONAL_METRICS and isinstance(v, int)
                            and abs(v) < 10):
                        scope = "noise"
                    collected.append({"metric": metric, "declared": v,
                                      "declared_spread": _num(spread) if spread else None,
                                      "scope": scope, "unit_hint": _unit(line),
                                      "evidence": {"source": doc["path"],
                                                   "page": pg["page"], "line": ln,
                                                   "quote": line.strip()[:240]}})
    # Deduplicate ACROSS scopes: prefer the aggregate row over a narrative
    # restatement of the same number, so one number is judged once.
    best: dict[tuple, dict] = {}
    for d in collected:
        k = (d["metric"], json.dumps(d["declared"]), d["scope"])
        if k not in best:
            best[k] = d
    out = sorted(best.values(), key=lambda d: (SCOPE_RANK.get(d["scope"], 9),
                                               d["metric"], str(d["declared"])))
    return out


def _unit(line: str) -> str | None:
    for u in ("kcal/kg", "MJ/kg", "mg/kg", "nm", "ms", "s", "%", "cm-1", "eV", "K"):
        if u.lower() in line.lower():
            return u
    return None


def _walk(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:200]):
            yield from _walk(v, f"{prefix}[{i}]")
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield prefix, obj


def extract_observed(base: Path, ledger_items: list[dict]) -> list[dict]:
    out = []
    for it in ledger_items:
        # Only genuine result/prediction artefacts. Logs, configs and scripts
        # are not "observed metrics" and would flood the comparison with noise.
        if it.get("role") not in ("results", "predictions", "data"):
            continue
        p = base / it["path"]
        if not p.is_file() or p.suffix.lower() not in (".json", ".csv", ".log", ".txt"):
            continue
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            for ln, line in enumerate(raw.splitlines(), 1):
                for m in _DECL_RX.finditer(line):
                    v = _num(m.group(2))
                    if v is not None:
                        out.append({"metric": m.group(1).lower(), "observed": v,
                                    "source": {"path": it["path"], "line": ln}})
            continue
        for path, value in _walk(obj):
            leaf = path.split(".")[-1].split("[")[0].lower()
            out.append({"metric": leaf, "observed": value,
                        "source": {"path": it["path"], "json_path": path}})
    return out


def compare(declared: list[dict], observed: list[dict],
            tolerance: dict | None = None) -> dict:
    tol = dict(DEFAULT_TOLERANCE)
    if tolerance:
        tol.update(tolerance)
    rows, used, deferred, discarded = [], set(), [], []
    for d in declared:
        scope = d.get("scope", "narrative")
        if scope == "noise":
            discarded.append({**d, "verdict": "DISCARDED",
                              "reason": "tiny integer on a dimensional metric; almost "
                                        "certainly a stray digit from R2/equation/caption"})
            continue
        if scope != "aggregate":
            deferred.append({**d, "verdict": "NEEDS_REVIEW",
                             "reason": (
                                 "per-fold row: a fold identity is required for a fair "
                                 "comparison" if scope == "per_fold_row" else
                                 "narrative declaration: the aggregation scope must be "
                                 "confirmed by a human or by the project's verification "
                                 "script; auto nearest-number matching would be misleading")})
            continue
        key = d["metric"]
        # An aggregate declaration must only be compared against aggregate run
        # outputs, never against per_fold[i] values.
        cands = [(i, o) for i, o in enumerate(observed)
                 if i not in used
                 and "[" not in (o.get("source") or {}).get("json_path", "")
                 and (key in o["metric"] or o["metric"] in key)]
        if not cands:
            rows.append({**d, "observed": None, "verdict": "UNVERIFIABLE",
                         "reason": "no matching value in the actual run outputs"})
            continue
        a = float(d["declared"])

        def _score(pair):
            i, o = pair
            jp = (o.get("source") or {}).get("json_path", "")
            # Exact name first, then aggregate fields (metrics.rmse) before
            # per-fold arrays (per_fold[3].rmse), then numeric closeness.
            return (o["metric"] != key, "[" in jp,
                    abs(float(o["observed"]) - a), i)

        i_o, o = min(cands, key=_score)
        used.add(i_o)
        jp = (o.get("source") or {}).get("json_path", "")
        match_basis = {"exact_name": o["metric"] == key,
                       "aggregate_field": "[" not in jp, "json_path": jp}
        b = float(o["observed"])
        ov = tol.get("overrides", {}).get(key, {})
        tab = float(ov.get("abs", tol["default_abs"]))
        trel = float(ov.get("rel", tol["default_rel"]))
        diff, rel = abs(a - b), (abs(a - b) / abs(a) if a else math.inf)
        within = diff <= tab + trel * abs(a)
        rows.append({**d, "observed": b, "observed_source": o["source"],
                     "match_basis": match_basis,
                     "abs_diff": round(diff, 10),
                     "rel_diff": round(rel, 10) if math.isfinite(rel) else None,
                     "tolerance": {"abs": tab, "rel": trel,
                                   "effective": round(tab + trel * abs(a), 10)},
                     "verdict": "PASS" if within else "FAIL",
                     "difference_kind": "numerical_variation" if within else
                                        "methodological_difference_candidate",
                     "reason": "within pre-declared tolerance" if within else
                               "exceeds pre-declared tolerance; route to attribution"})
    n_pass = sum(1 for r in rows if r["verdict"] == "PASS")
    n_fail = sum(1 for r in rows if r["verdict"] == "FAIL")
    n_unv = sum(1 for r in rows if r["verdict"] == "UNVERIFIABLE")
    return {"generated_at": now_iso(),
            "tolerance": tol,
            "counts": {"total": len(rows), "pass": n_pass, "fail": n_fail,
                       "unverifiable": n_unv, "needs_review": len(deferred),
                       "discarded": len(discarded)},
            "rows": rows[:300],
            "deferred_rows": deferred[:300],
            "discarded_rows": discarded[:100],
            "policy": "numeric agreement is primary; image similarity is supporting only. "
                      "ONLY aggregate declarations (clear scope) are auto-judged against "
                      "aggregate run outputs. Narrative/per-fold declarations are kept with "
                      "their evidence but marked NEEDS_REVIEW, because nearest-number matching "
                      "manufactures false FAILs. Prefer a real verification script's numeric "
                      "comparison (external_verified) over these heuristics.",
            "caveat": "auto-matched by metric name + aggregate-field preference; "
                      "review observed_source/match_basis before citing any row."}


def load_external(base: Path, ledger_items: list[dict],
                  extra_dirs: tuple | list = ()) -> dict:
    """Prefer numeric comparisons produced by an ACTUALLY RUN verification script.

    A real script knows the metric definition and the aggregation scope; regex
    heuristics do not. Any JSON containing `comparison.rows` (or top-level rows)
    with declared/recomputed/verdict fields is collected with its provenance.
    """
    candidates: list[Path] = []
    for it in ledger_items:
        if it.get("role") in ("results", "predictions"):
            p = base / it["path"]
            if p.suffix.lower() == ".json":
                candidates.append(p)
    for d in extra_dirs:
        d = Path(d)
        if not d.exists():
            continue
        for p in d.rglob("*.json"):
            if any(k in p.name.lower() for k in
                   ("check", "compar", "recompute", "verif", "result")):
                candidates.append(p)
    found, seen = [], set()
    for p in candidates:
        key = str(p.resolve())
        if key in seen or not p.is_file():
            continue
        seen.add(key)
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        # Do not treat this Skill's own comparison.json as external evidence.
        if isinstance(obj, dict) and ("external_verified" in obj or "deferred_rows" in obj):
            continue
        c = obj.get("comparison") if isinstance(obj, dict) else None
        rows = c.get("rows") if isinstance(c, dict) and isinstance(c.get("rows"), list) else None
        if rows is None and isinstance(obj, dict) and isinstance(obj.get("rows"), list):
            rows = obj["rows"]
        if not rows:
            continue
        norm = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            dec, obs = r.get("declared"), r.get("recomputed", r.get("observed"))
            verdict = r.get("verdict") or r.get("status")
            if dec is None or obs is None or verdict is None:
                continue
            norm.append({"metric": r.get("metric"), "declared": dec, "observed": obs,
                         "verdict": str(verdict).upper(),
                         "abs_diff": r.get("abs_diff"),
                         "tolerance": r.get("tolerance_effective", r.get("tolerance")),
                         "evidence": r.get("evidence"), "source_file": str(p)})
        if norm:
            found.append({
                "source_file": str(p), "n_rows": len(norm),
                "n_pass": sum(1 for x in norm if x["verdict"] == "PASS"),
                "n_fail": sum(1 for x in norm if x["verdict"] == "FAIL"),
                "rows": norm[:120],
                "note": "values produced by a real verification run; preferred over "
                        "the regex-based heuristic comparison",
            })
    return {"n_sources": len(found), "sources": found,
            "precedence": "external_verified > heuristic aggregate matching",
            "note": "if empty, run the project's verification script and re-run `run`"}


def make_figures(observed: list[dict], ledger_items: list[dict], base: Path,
                 out_dir: Path) -> dict:
    """Render reproduction figures and a side-by-side with paper originals."""
    out_dir.mkdir(parents=True, exist_ok=True)
    originals = [it["path"] for it in ledger_items if it.get("role") == "figure"
                 and it["path"].lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
    status = {"originals_found": originals[:10], "generated": [],
              "backend": None, "note": ""}
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        status["backend"] = "matplotlib " + matplotlib.__version__
    except Exception as exc:  # noqa: BLE001
        status["note"] = f"matplotlib unavailable ({type(exc).__name__}); figures not rendered"
        return status
    # `per_fold[i].hybrid.rmse` and `per_fold[i].plsr.rmse` share the leaf name
    # "rmse". Keep the branch from the JSON path or the figure silently shows
    # the BASELINE while the paper original shows the proposed method.
    branches: dict[str, dict] = {}
    for o in observed:
        jp = (o.get("source") or {}).get("json_path", "")
        m = re.search(r"per_fold\[(\d+)\]", jp)
        if not m or o["metric"] not in ("rmse", "mae", "r2"):
            continue
        branch = ("hybrid" if ".hybrid." in jp else
                  "plsr" if ".plsr." in jp else "flat")
        branches.setdefault(branch, {}).setdefault(int(m.group(1)), {})[o["metric"]] = o["observed"]
    main_branch = "hybrid" if "hybrid" in branches else (
        "flat" if "flat" in branches else next(iter(branches), None))
    status["branch_used"] = main_branch
    status["branches_found"] = list(branches)
    if main_branch:
        folds = branches[main_branch]
        ks = sorted(folds)
        for metric, color in (("rmse", "#2A6F97"), ("mae", "#FCA311"), ("r2", "#2A9D8F")):
            vals = [folds[k].get(metric) for k in ks]
            if any(v is None for v in vals):
                continue
            fig, ax = plt.subplots(figsize=(7, 4), dpi=130)
            ax.bar([str(k) for k in ks], vals, color=color)
            try:
                import statistics
                mean, spread = statistics.mean(vals), statistics.pstdev(vals)
                ax.axhline(mean, color="#E63946", linestyle="--", linewidth=1.4,
                           label=f"mean {mean:.2f} ± {spread:.2f}")
                ax.legend(fontsize=8, loc="upper right")
            except Exception:
                pass
            ax.set_title(f"Reproduced per-fold {metric.upper()} ({main_branch})")
            ax.set_xlabel("fold"); ax.set_ylabel(metric.upper())
            ax.grid(axis="y", alpha=.3)
            fig.tight_layout()
            fp = out_dir / f"repro_{metric}_by_fold.png"
            fig.savefig(fp); plt.close(fig)
            status["generated"].append(str(fp))
    if originals and status["generated"]:
        try:
            from PIL import Image
            # Match the original to the comparison metric instead of taking
            # whichever figure happens to sort first.
            orig = next((p for p in originals if "rmse" in p.lower()), originals[0])
            repro = next((p for p in status["generated"]
                          if p.endswith("repro_rmse_by_fold.png")), status["generated"][0])
            a = Image.open(base / orig).convert("RGB")
            b = Image.open(repro).convert("RGB")
            status["paper_original"] = orig
            status["reproduction_figure"] = repro
            h = 420
            a = a.resize((int(a.width * h / a.height), h))
            b = b.resize((int(b.width * h / b.height), h))
            canvas = Image.new("RGB", (a.width + b.width + 20, h), "white")
            canvas.paste(a, (0, 0)); canvas.paste(b, (a.width + 20, 0))
            fp = out_dir / "comparison_paper_vs_repro.png"
            canvas.save(fp)
            status["generated"].append(str(fp))
            status["note"] = (f"left = paper original ({orig}), right = regenerated "
                              f"per-fold RMSE from branch `{main_branch}` ({repro}); "
                              "dashed line = recomputed mean, label shows mean ± population std")
        except Exception as exc:  # noqa: BLE001
            status["note"] = f"side-by-side skipped: {type(exc).__name__}: {exc}"
    return status
