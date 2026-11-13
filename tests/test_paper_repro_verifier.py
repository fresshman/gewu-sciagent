"""Regression tests for the paper-repro-verifier Skill reused inside gewu.

These tests use only repository-tracked material: the Skill's own synthetic
example fixture and the desensitised metrics snapshot under docs/verification/.
They never need the private spectra/weights or a live model.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "gewu" / "skills" / "paper_repro_verifier"
CLI = SKILL / "scripts" / "repro_cli.py"
SNAPSHOT = ROOT / "docs" / "verification" / "paper-repro-skill"


def _cli(*args: str, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *args], cwd=ROOT,
        capture_output=True, text=True, timeout=timeout,
    )


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def selftest_out(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("repro_skill") / "out"
    work = tmp_path_factory.mktemp("repro_work")
    r = _cli("run", "--case", str(SKILL / "examples" / "minimal_case.json"),
             "--inputs", str(SKILL / "examples" / "fixture"),
             "--work", str(work), "--out", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    return out


def test_skill_source_is_platform_compliant():
    files = [p for p in SKILL.rglob("*")
             if p.is_file() and "__pycache__" not in p.parts]
    assert files, "skill sources missing"
    assert len(files) <= 50
    assert all(p.stat().st_size <= 500 * 1024 for p in files)
    assert sum(p.stat().st_size for p in files) <= 2 * 1024 * 1024
    assert not any(p.is_symlink() for p in files)
    for p in files:
        p.read_bytes().decode("utf-8")   # all resources must be UTF-8 text


def test_run_builds_contract_skeleton(selftest_out: Path):
    result = _json(selftest_out / "result.json")
    assert result["case_id"] == "EXAMPLE-ONLY-0001"
    # output_contract is a dict in this fixture: every field must exist.
    for field in ("answer", "evidence", "uncertainty", "status"):
        assert field in result
    for field in ("sources", "change_records", "reproduction", "limits"):
        assert field in result
    for artifact in ("materials_ledger.json", "environment_snapshot.json",
                     "parameters.json", "comparison.json", "attribution.json",
                     "execution.json", "repro_report.md", "repro/run_log.jsonl",
                     "repro/evidence_index.json"):
        assert (selftest_out / artifact).is_file(), artifact


def test_three_source_parameter_conflicts_are_surfaced(selftest_out: Path):
    params = _json(selftest_out / "parameters.json")
    conflicts = {r["name"] for r in params["executable_parameter_table"]
                 if r["conflict"]}
    # paper 0.001 vs config 0.002; paper 32 vs code default 64
    assert {"lr", "batch_size"} <= conflicts
    assert params["n_conflicts"] == 2
    for row in params["executable_parameter_table"]:
        assert row["source_class"] in ("paper_explicit", "code_inferred",
                                       "self_set", "unresolved")
        assert "agent_action" in row


def test_comparison_does_not_invent_failures(selftest_out: Path):
    comparison = _json(selftest_out / "comparison.json")
    assert comparison["tolerance"]["declared_before_comparison"] is True
    counts = comparison["counts"]
    assert counts["fail"] == 0
    # The example paper contains ONLY a narrative declaration ("achieves RMSE
    # 0.1234 ... across five folds"). The Skill deliberately defers narrative
    # statements instead of nearest-number matching them, so zero auto-judged
    # rows is the CORRECT outcome. Requiring a PASS here would pressure the
    # comparison into inventing one - the exact failure mode this guards against.
    assert counts["total"] == 0
    assert counts["needs_review"] >= 1
    assert any(r["metric"] == "rmse" and r["verdict"] == "NEEDS_REVIEW"
               for r in comparison["deferred_rows"])
    for row in comparison["rows"]:
        assert "tolerance" in row and "evidence" in row
        assert row["verdict"] in ("PASS", "FAIL", "UNVERIFIABLE")


def test_aggregate_declaration_matches_only_aggregate_output():
    """Positive path: a clearly-scoped aggregate claim IS auto-judged, and only
    against an aggregate run output - never against a per_fold[i] value.
    Tolerance is fixed before comparison and cannot be relaxed afterwards.
    """
    sys.path.insert(0, str(SKILL / "scripts"))
    import compare as compare_mod

    def decl(value):
        return {"metric": "rmse", "declared": value, "declared_spread": None,
                "scope": "aggregate", "unit_hint": "kcal/kg",
                "evidence": {"source": "paper.md", "page": 1, "line": 9,
                             "quote": f"Mean RMSE = {value}"}}

    observed = [
        {"metric": "rmse", "observed": 0.1235,
         "source": {"path": "results.json", "json_path": "metrics.rmse"}},
        {"metric": "rmse", "observed": 0.131,
         "source": {"path": "results.json", "json_path": "per_fold[0].rmse"}},
    ]
    out = compare_mod.compare([decl(0.1234)], observed)
    assert out["tolerance"]["declared_before_comparison"] is True
    assert out["counts"] == {"total": 1, "pass": 1, "fail": 0,
                             "unverifiable": 0, "needs_review": 0, "discarded": 0}
    row = out["rows"][0]
    assert row["verdict"] == "PASS"
    assert row["observed"] == 0.1235
    assert row["match_basis"]["aggregate_field"] is True
    assert row["observed_source"]["json_path"] == "metrics.rmse"

    # A genuinely different declared value must FAIL under the same fixed
    # tolerance - no post-hoc widening to manufacture agreement.
    loose = compare_mod.compare([decl(5.0)], observed)
    assert loose["counts"]["fail"] == 1
    assert loose["rows"][0]["difference_kind"] == "methodological_difference_candidate"


def test_execute_records_real_exit_code(selftest_out: Path):
    r = _cli("execute", "--out", str(selftest_out),
             "--cmd", f'"{sys.executable}" --version')
    assert r.returncode == 0, r.stdout + r.stderr
    execution = _json(selftest_out / "execution.json")
    assert execution["exit_code"] == 0
    assert execution["status"] == "ok"
    assert "Python" in execution["stdout"]
    assert execution["command"]


def test_finalize_validates_contract(selftest_out: Path):
    r = _cli("finalize", "--case", str(SKILL / "examples" / "minimal_case.json"),
             "--out", str(selftest_out))
    assert r.returncode == 0, r.stdout + r.stderr
    validation = _json(selftest_out / "validation.json")
    assert validation["verdict"] == "PASS"
    assert validation["problems"] == []


def test_recompute_matches_paper_table(tmp_path: Path):
    out = tmp_path / "recompute_check.json"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_paper_recompute.py"),
         "--metrics", str(SNAPSHOT / "metrics_snapshot.json"),
         "--tex", str(ROOT / "docs" / "paper" / "coal_report" / "main.tex"),
         "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    data = _json(out)
    assert data["tolerance"]["declared_before_comparison"] is True
    assert data["comparison"]["counts"]["total"] == 7
    assert data["comparison"]["counts"]["pass"] == 7
    assert data["comparison"]["counts"]["fail"] == 0
    assert data["stored_aggregate_cross_check"]["n_fail"] == 0
    assert data["comparison"]["grade"] == "reproduced"
