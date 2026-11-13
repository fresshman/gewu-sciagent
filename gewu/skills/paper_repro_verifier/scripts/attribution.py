"""Verifiable difference attribution + graded reproduction conclusion.

A FAIL is never left as "doesn't match". It becomes a list of checkable
hypotheses, each with the evidence required and the action that would confirm
or kill it. The grade is derived from evidence counts, not from prose.
"""
from __future__ import annotations

from common import now_iso

TREE = [
    ("environment", "dependency/driver/hardware/precision or threading differs from the paper",
     "environment_snapshot.json + the paper's stated stack",
     "pin the declared versions, rebuild, rerun with the same thread/seed settings"),
    ("data", "data version, split, preprocessing, unit or leakage differs",
     "data checksum/version, split script, fold assignment",
     "hash the dataset, replay the exact split, verify units and normalisation"),
    ("implementation", "code default != paper hyper-parameter; metric definition or aggregation differs",
     "parameters.json conflict rows + metric implementation",
     "apply resolved paper parameters; recompute the metric with the paper's definition "
     "(e.g. population vs sample std)"),
    ("specification", "paper under-specifies: missing table values, ambiguous formula, caption/text conflict",
     "page/line locator of the ambiguous statement",
     "quote the exact passage; mark unverifiable if no value can be recovered; do not guess"),
    ("stochastic", "seed / fold shuffle / init variance; run-to-run fluctuation",
     "multiple runs with recorded seeds and a dispersion interval",
     "repeat >=3 seeds, report mean±spread; only classify as numerical_variation "
     "if it falls inside the PRE-DECLARED tolerance"),
]


def build(comparison: dict, env_checks: dict, parameters: dict,
          materials: dict, execution: dict, external: dict | None = None) -> dict:
    fails = [r for r in comparison.get("rows", []) if r.get("verdict") == "FAIL"]
    unver = [r for r in comparison.get("rows", []) if r.get("verdict") == "UNVERIFIABLE"]
    conflicts = [r for r in parameters.get("executable_parameter_table", [])
                 if r.get("conflict")]
    gaps = [g for g in materials.get("checklist", []) if g.get("status") == "missing"]
    items = []

    for r in fails:
        hypotheses = []
        for cat, claim, need, action in TREE:
            weight = "primary" if (
                (cat == "implementation" and conflicts) or
                (cat == "data" and any(g["category"] == "data" for g in gaps)) or
                (cat == "environment" and any(c.get("status") == "version_mismatch"
                                              for c in env_checks.get("checks", [])))
            ) else "candidate"
            hypotheses.append({"category": cat, "weight": weight, "hypothesis": claim,
                               "evidence_required": need, "verification_action": action,
                               "status": "untested", "evidence_locators": []})
        items.append({"id": f"DIFF-{len(items)+1:03d}", "metric": r.get("metric"),
                      "declared": r.get("declared"), "observed": r.get("observed"),
                      "abs_diff": r.get("abs_diff"), "tolerance": r.get("tolerance"),
                      "kind": r.get("difference_kind"),
                      "paper_evidence": r.get("evidence"),
                      "observed_source": r.get("observed_source"),
                      "hypotheses": hypotheses,
                      "resolution": None,
                      "note": "fill resolution with the hypothesis actually confirmed AND its evidence"})
    for r in unver:
        items.append({"id": f"DIFF-{len(items)+1:03d}", "metric": r.get("metric"),
                      "declared": r.get("declared"), "observed": None,
                      "kind": "unverifiable", "paper_evidence": r.get("evidence"),
                      "reason": r.get("reason"), "resolution": None,
                      "note": "no comparable run output; record as uncertainty, never as a fact"})

    c = comparison.get("counts", {})
    grade, basis = _grade(c, gaps, conflicts, unver, execution)
    ext = external if external is not None else comparison.get("external_verified", {})
    ext_summary = {"n_sources": ext.get("n_sources", 0), "n_pass": 0, "n_fail": 0}
    if ext.get("n_sources"):
        for s in ext.get("sources", []):
            ext_summary["n_pass"] += s.get("n_pass", 0)
            ext_summary["n_fail"] += s.get("n_fail", 0)
        basis += (f"；实际运行验证脚本的数值比较 "
                  f"{ext_summary['n_pass']} PASS / {ext_summary['n_fail']} FAIL（优先采信），"
                  f"启发式比较仅作兜底")
    return {"generated_at": now_iso(),
            "external_summary": ext_summary,
            "decision_tree": [{"order": i + 1, "category": c_, "hypothesis": h,
                               "evidence_required": e, "verification_action": a}
                              for i, (c_, h, e, a) in enumerate(TREE)],
            "n_items": len(items), "items": items,
            "context": {"n_parameter_conflicts": len(conflicts),
                        "missing_material_categories": [g["category"] for g in gaps],
                        "n_environment_mismatches": sum(1 for x in env_checks.get("checks", [])
                                                        if x.get("status") == "version_mismatch")},
            "grade": grade, "basis": basis,
            "rule": "numeric_variation only if inside a tolerance declared BEFORE comparison; "
                    "a methodological difference must not be hidden by widening tolerance."}


def _grade(counts, gaps, conflicts, unver, execution) -> tuple[str, str]:
    total = counts.get("total", 0)
    n_pass, n_fail = counts.get("pass", 0), counts.get("fail", 0)
    n_unv = counts.get("unverifiable", 0)
    exec_status = (execution or {}).get("status", "not_run")
    if total == 0:
        return "indeterminate", "no comparable declared/observed metric pair could be built from the inputs"
    if n_pass == total and not gaps and not conflicts:
        return "reproduced", f"all {n_pass} comparable metrics within pre-declared tolerance"
    if n_fail == 0 and n_unv and n_pass:
        return "partially_reproduced", (
            f"{n_pass} metrics agree, {n_unv} cannot be verified; "
            f"missing categories: {[g['category'] for g in gaps]}")
    if n_fail and exec_status == "failed":
        return "indeterminate", "run failed; differences cannot be attributed to the method yet"
    if n_pass:
        return "partially_reproduced", (
            f"{n_pass}/{total} metrics agree, {n_fail} exceed tolerance, {n_unv} unverifiable; "
            f"{len(conflicts)} parameter conflicts; see attribution items")
    if n_unv >= n_fail:
        return "indeterminate", "most comparisons lack run outputs; evidence insufficient for a verdict"
    return "not_reproducible", f"0/{total} comparable metrics agree within tolerance"
