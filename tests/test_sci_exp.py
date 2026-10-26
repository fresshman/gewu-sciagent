"""通用实验注册表引擎的回归测试。

关键：用「合成 registry」验证引擎**与学科无关**——不依赖 coal 项目也能跑通
list/get/rerun/audit 全流程；同时确认真实 coal_mil.json 能被正确加载。
"""
import json
import os
import sys
import tempfile
import textwrap

import pytest

# 让测试能 import gewu/mcp/sci_exp
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "gewu", "mcp"))
import sci_exp as E  # noqa: E402


def _make_synthetic_registry(tmpdir: str):
    """写一个合成领域包：一个会被重算（一致）、一个会被重算（漂移）、一个需原始脚本。"""
    script = os.path.join(tmpdir, "fake_exp.py")
    # 该脚本打印 JSON，输出键 rmse_kcal_mean=200.0（与注册记录一致）
    with open(script, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(
            "import json\n"
            "print(json.dumps({'mean_rmse_kcal_kg': 200.0}))\n"
        ))
    drift_script = os.path.join(tmpdir, "fake_drift.py")
    with open(drift_script, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(
            "import json\n"
            "print(json.dumps({'mean_rmse_kcal_kg': 999.0}))\n"
        ))
    reg = {
        "domain": "synthetic",
        "domain_label": "测试用合成领域（不对应任何真实学科）",
        "schema_version": 1,
        "experiments": [
            {
                "id": "syn_ok", "name": "合成-一致", "category": "ours",
                "metrics": {"rmse_kcal_mean": 200.0},
                "source": "fake", "source_of_truth": "fake",
                "reproducibility": "realizable_by_gewu",
                "rerun": {
                    "type": "cli", "python": "system",
                    "script": script, "args": [],
                    "metrics_path": "", "key_map": {"rmse_kcal_mean": "mean_rmse_kcal_kg"},
                    "tolerance": {"rmse_kcal_mean": 1.0}, "timeout": 30,
                },
            },
            {
                "id": "syn_drift", "name": "合成-漂移", "category": "ours",
                "metrics": {"rmse_kcal_mean": 200.0},
                "source": "fake", "source_of_truth": "fake",
                "reproducibility": "realizable_by_gewu",
                "rerun": {
                    "type": "cli", "python": "system",
                    "script": drift_script, "args": [],
                    "metrics_path": "", "key_map": {"rmse_kcal_mean": "mean_rmse_kcal_kg"},
                    "tolerance": {"rmse_kcal_mean": 1.0}, "timeout": 30,
                },
            },
            {
                "id": "syn_needs_script", "name": "合成-需原始脚本", "category": "comparison",
                "metrics": {"rmse_kcal_mean": 123.0},
                "source": "fake", "source_of_truth": "fake",
                "reproducibility": "requires_original_script",
                "rerun": {"type": "none"},
                "rerun_hint": "python fake_compare.py",
            },
        ],
    }
    path = os.path.join(tmpdir, "synthetic.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)
    return path, [script, drift_script]


@pytest.fixture
def synthetic_registry(monkeypatch, tmp_path):
    path, scripts = _make_synthetic_registry(str(tmp_path))
    monkeypatch.setenv("GEWU_REGISTRY_DIR", str(tmp_path))
    # 重新加载（模块级 _REGISTRY_DIR 已在 import 时绑定，需强制重算）
    monkeypatch.setattr(E, "_REGISTRY_DIR", str(tmp_path))
    return str(tmp_path), scripts


def test_synthetic_list(synthetic_registry):
    out = E.list_experiments()
    ids = {e["id"] for e in out["experiments"]}
    assert ids == {"syn_ok", "syn_drift", "syn_needs_script"}
    assert out["n_experiments"] == 3
    assert all(e["domain"] == "synthetic" for e in out["experiments"])


def test_synthetic_get(synthetic_registry):
    ok = E.get_experiment("syn_ok")
    assert ok["status"] == "ok"
    assert ok["live_metrics_available"] is True
    needs = E.get_experiment("syn_needs_script")
    assert needs["reproducibility"] == "requires_original_script"
    assert E.get_experiment("nope")["status"] == "not_found"


def test_synthetic_rerun_consistent(synthetic_registry):
    r = E.rerun_experiment("syn_ok")
    assert r["status"] == "reproduced"
    assert r["all_consistent"] is True
    assert r["recomputed"]["rmse_kcal_mean"]["ok"] is True


def test_synthetic_rerun_drift_detected(synthetic_registry):
    r = E.rerun_experiment("syn_drift")
    assert r["status"] == "reproduced"
    assert r["all_consistent"] is False  # 999 vs 200 → 漂移被检出
    assert r["recomputed"]["rmse_kcal_mean"]["ok"] is False


def test_synthetic_rerun_needs_script(synthetic_registry):
    r = E.rerun_experiment("syn_needs_script")
    assert r["status"] == "needs_original_script"
    assert r["rerun_hint"] == "python fake_compare.py"


def test_synthetic_audit(synthetic_registry):
    r = E.audit_experiments()
    assert r["n_experiments"] == 3
    # syn_drift 漂移 → n_drift=1, all_consistent=False
    assert r["n_drift"] == 1
    assert r["all_consistent"] is False


def test_real_coal_registry_loads():
    """真实 coal_mil.json 能被引擎加载，且 our_hybrid 标记为可重算。"""
    exps = E.load_experiments()
    assert "our_hybrid" in exps
    assert exps["our_hybrid"]["domain"] == "coal-mil"
    assert exps["our_hybrid"]["reproducibility"] == "realizable_by_gewu"
    assert exps["our_hybrid"]["rerun"]["type"] == "cli"
    # 15 条对比/消融实验诚实标注为 requires_original_script
    n_needs = sum(1 for e in exps.values() if e["reproducibility"] == "requires_original_script")
    assert n_needs == 15
