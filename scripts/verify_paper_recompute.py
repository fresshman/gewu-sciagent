#!/usr/bin/env python3
"""Independently recompute 5-fold aggregate metrics and compare with the paper.

This is a REAL verification script for the coal LIBS / MIL paper, used to
exercise the paper-repro-verifier Skill on actual project material.

It reads:
  --metrics  output/documents/coal_report/metrics_recomputed.json (per-fold values)
  --tex      docs/paper/coal_report/main.tex (the paper's declared table/summary)
  --out      where to write recompute_check.json

The tolerance is declared BEFORE comparison and written into the output.
Nothing about the paper's numbers is hardcoded: declared values are parsed
from the actual .tex table header + mean row and the abstract sentence.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from pathlib import Path

TOLERANCE = {"abs": 0.01, "rel": 0.0,
             "declared_before_comparison": True,
             "reason": "paper table keeps 4 decimals and abstract 2 decimals; "
                       "recomputed values are full precision, so 0.01 absolute is "
                       "the tightest tolerance that does not punish rounding"}

COLUMN_MAP = {
    "plsr rmse": "plsr.mean_rmse",
    "hybrid rmse": "hybrid.mean_rmse",
    "plsr r2": "plsr.mean_r2",
    "hybrid r2": "hybrid.mean_r2",
    "plsr r": "plsr.mean_r2",
    "hybrid r": "hybrid.mean_r2",
    "delta rmse": "delta_rmse",
}


def _clean(cell: str) -> str:
    s = cell.strip()
    # Keep the exponent as "2" so "$R^2$" becomes "R2" and maps to mean_r2.
    s = re.sub(r"\^\{?2\}?", "2", s)
    s = re.sub(r"\$|\\[a-zA-Z]+\{|\\rm|\\text\{", " ", s)
    s = s.replace("{", "").replace("}", "").replace("\\", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def parse_declared(tex_path: Path) -> list[dict]:
    """Parse the paper's aggregate table (header + '均值' row) and the abstract."""
    lines = tex_path.read_text(encoding="utf-8").splitlines()
    out: list[dict] = []
    header = None
    for ln, line in enumerate(lines, 1):
        if "Fold" in line and "PLSR RMSE" in line and "Hybrid RMSE" in line:
            header = [_clean(c) for c in line.split("&")]
            continue
        if header and ("均值" in line or "mean" in line.lower()) and "&" in line:
            cells = [c.strip() for c in line.split("&")]
            for col, cell in zip(header[1:], cells[1:]):
                m = re.search(r"-?\d+\.\d+", cell.replace("$-$", "-"))
                if not m:
                    continue
                key = COLUMN_MAP.get(col)
                for cand in (col, col.replace("  ", " ")):
                    if cand in COLUMN_MAP:
                        key = COLUMN_MAP[cand]
                        break
                if not key:
                    for k, v in COLUMN_MAP.items():
                        if k in col:
                            key = v
                            break
                if key:
                    out.append({"metric": key, "declared": float(m.group()),
                                "evidence": {"source": str(tex_path), "line": ln,
                                             "section": "5-fold summary table",
                                             "quote": line.strip()[:200]},
                                "column": col})
            header = None

    # Abstract sentence: "5 折 hybrid RMSE 均值 $214.57 \pm 25.71$ kcal/kg"
    for ln, line in enumerate(lines, 1):
        m = re.search(r"RMSE\s*均值\s*\$?\s*(\d+\.\d+)\s*(?:\\pm|\±)\s*(\d+\.\d+)", line)
        if m:
            out.append({"metric": "hybrid.mean_rmse_abstract", "declared": float(m.group(1)),
                        "evidence": {"source": str(tex_path), "line": ln,
                                     "section": "abstract", "quote": line.strip()[:200]},
                        "column": "abstract mean"})
            out.append({"metric": "hybrid.std_rmse_pop_abstract", "declared": float(m.group(2)),
                        "evidence": {"source": str(tex_path), "line": ln,
                                     "section": "abstract", "quote": line.strip()[:200]},
                        "column": "abstract spread"})
            break
    return out


def recompute(metrics: dict) -> dict:
    folds = metrics.get("per_fold", [])
    if not folds:
        raise ValueError("per_fold is empty; cannot recompute from actual values")
    hyb = [f["hybrid"]["rmse"] for f in folds]
    pls = [f["plsr"]["rmse"] for f in folds]
    hyb_r2 = [f["hybrid"]["r2"] for f in folds]
    pls_r2 = [f["plsr"]["r2"] for f in folds]
    delta = [f.get("delta_rmse", h - p) for f, h, p in zip(folds, hyb, pls)]
    r = {
        "hybrid.mean_rmse": statistics.mean(hyb),
        "hybrid.std_rmse_pop": statistics.pstdev(hyb),
        "hybrid.std_rmse_sample": statistics.stdev(hyb),
        "hybrid.mean_mae": statistics.mean(f["hybrid"]["mae"] for f in folds),
        "hybrid.mean_r2": statistics.mean(hyb_r2),
        "plsr.mean_rmse": statistics.mean(pls),
        "plsr.std_rmse_pop": statistics.pstdev(pls),
        "plsr.mean_r2": statistics.mean(pls_r2),
        "delta_rmse": statistics.mean(delta),
        "hybrid.mean_rmse_abstract": statistics.mean(hyb),
        "hybrid.std_rmse_pop_abstract": statistics.pstdev(hyb),
        "n_folds": len(folds),
    }
    return r


def compare(declared: list[dict], values: dict) -> dict:
    rows = []
    for d in declared:
        key = d["metric"]
        obs = values.get(key)
        if obs is None:
            rows.append({**d, "recomputed": None, "verdict": "UNVERIFIABLE",
                         "reason": "no recomputed value for this metric"})
            continue
        diff = abs(float(obs) - float(d["declared"]))
        allowed = TOLERANCE["abs"] + TOLERANCE["rel"] * abs(float(d["declared"]))
        rows.append({**d, "recomputed": round(float(obs), 10),
                     "abs_diff": round(diff, 10), "tolerance_effective": allowed,
                     "verdict": "PASS" if diff <= allowed else "FAIL",
                     "difference_kind": "numerical_variation" if diff <= allowed
                                        else "methodological_difference_candidate"})
    npass = sum(1 for x in rows if x["verdict"] == "PASS")
    nfail = sum(1 for x in rows if x["verdict"] == "FAIL")
    return {"counts": {"total": len(rows), "pass": npass, "fail": nfail},
            "rows": rows,
            "grade": "reproduced" if nfail == 0 and npass else "partially_reproduced"}


def cross_check(metrics: dict, values: dict) -> dict:
    """Also verify the stored aggregate block against the independent recompute."""
    checks = []
    for group in ("hybrid", "plsr"):
        agg = metrics.get(group, {})
        for field, key in (("mean_rmse", f"{group}.mean_rmse"),
                           ("std_rmse_pop", f"{group}.std_rmse_pop"),
                           ("mean_r2", f"{group}.mean_r2")):
            if field not in agg or key not in values:
                continue
            diff = abs(float(agg[field]) - float(values[key]))
            checks.append({"item": f"{group}.{field}", "stored": agg[field],
                           "recomputed": values[key], "abs_diff": diff,
                           "status": "PASS" if diff <= 1e-9 else "FAIL"})
    return {"n_pass": sum(1 for c in checks if c["status"] == "PASS"),
            "n_fail": sum(1 for c in checks if c["status"] == "FAIL"),
            "checks": checks}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--metrics", required=True)
    ap.add_argument("--tex", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    metrics = json.loads(Path(args.metrics).read_text(encoding="utf-8"))
    declared = parse_declared(Path(args.tex))
    values = recompute(metrics)
    comparison = compare(declared, values)
    result = {
        "inputs": {"metrics": args.metrics, "tex": args.tex},
        "tolerance": TOLERANCE,
        "recomputed": values,
        "comparison": comparison,
        "stored_aggregate_cross_check": cross_check(metrics, values),
        "note": "declared values parsed from the actual .tex; recomputed values "
                "derived only from per_fold entries. Nothing is hardcoded.",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"comparison": comparison["counts"],
                      "grade": comparison["grade"],
                      "cross_check": {"n_pass": result["stored_aggregate_cross_check"]["n_pass"],
                                      "n_fail": result["stored_aggregate_cross_check"]["n_fail"]},
                      "out": str(out)}, ensure_ascii=False))
    return 0 if comparison["counts"]["fail"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
