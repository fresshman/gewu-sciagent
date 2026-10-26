"""D2 数值声明溯源引擎回归测试（领域无关）。

用合成注册表验证「断言数字↔注册表 source_of_truth」一致性判定；
另含一条真实 coal_mil 注册表的廉价（非 strict）校验。
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gewu", "mcp"))
import claim_provenance as cp  # noqa: E402


def _synthetic_experiments():
    """一个可复现实验 + 一个需原始脚本的实验，覆盖主要分支。"""
    return {
        "our_hybrid": {
            "id": "our_hybrid", "domain": "synthetic",
            "metrics": {"rmse_kcal_mean": 214.5699, "r2_mean": 0.8963},
            "reproducibility": "realizable_by_gewu",
            "rerun": {"tolerance": {"rmse_kcal_mean": 1.0}},
        },
        "legacy": {
            "id": "legacy", "domain": "synthetic",
            "metrics": {"rmse_kcal_mean": 197.99},
            "reproducibility": "requires_original_script",
        },
    }


@pytest.fixture
def patch_registry(monkeypatch):
    exps = _synthetic_experiments()
    monkeypatch.setattr(cp._sci_exp, "load_experiments", lambda: exps)
    return exps


def test_grounded_within_tolerance(patch_registry):
    claims = [{"text": "RMSE", "metric": "rmse_kcal_mean", "value": 214.57,
               "source": "registry:our_hybrid"}]
    rep = cp.verify_claims(claims)
    assert rep["claims"][0]["status"] == "grounded"
    assert rep["all_grounded"] is True


def test_drift_flagged(patch_registry):
    claims = [{"text": "RMSE", "metric": "rmse_kcal_mean", "value": 300.0,
               "source": "registry:our_hybrid"}]
    rep = cp.verify_claims(claims)
    r = rep["claims"][0]
    assert r["status"] == "drift"
    assert r["abs_diff"] > r["tolerance"]
    assert rep["all_grounded"] is False


def test_rounding_r2_accepted(patch_registry):
    claims = [{"text": "R2", "metric": "r2_mean", "value": 0.90,
               "source": "registry:our_hybrid"}]
    rep = cp.verify_claims(claims)
    assert rep["claims"][0]["status"] == "grounded"


def test_unknown_experiment(patch_registry):
    claims = [{"text": "x", "metric": "rmse_kcal_mean", "value": 1.0,
               "source": "registry:ghost"}]
    rep = cp.verify_claims(claims)
    assert rep["claims"][0]["status"] == "unknown_experiment"


def test_metric_not_in_registry(patch_registry):
    claims = [{"text": "x", "metric": "foo_bar", "value": 1.0,
               "source": "registry:our_hybrid"}]
    rep = cp.verify_claims(claims)
    assert rep["claims"][0]["status"] == "metric_not_in_registry"


def test_value_with_unit_string_parsed(patch_registry):
    claims = [{"text": "RMSE", "metric": "rmse_kcal_mean", "value": "214.57 kcal/kg",
               "source": "registry:our_hybrid"}]
    rep = cp.verify_claims(claims)
    assert rep["claims"][0]["status"] == "grounded"
    assert rep["claims"][0]["value"] == 214.57


def test_bad_value(patch_registry):
    claims = [{"text": "x", "metric": "rmse_kcal_mean", "value": "not-a-number",
               "source": "registry:our_hybrid"}]
    rep = cp.verify_claims(claims)
    assert rep["claims"][0]["status"] == "bad_value"


def test_paper_grounded_vs_unverified(patch_registry):
    claims = [{"text": "lit claim", "value": 8.1, "source": "paper:ilse2018"}]
    rep_ok = cp.verify_claims(claims, verified_papers=["ilse2018"])
    assert rep_ok["claims"][0]["status"] == "paper_grounded"
    rep_bad = cp.verify_claims(claims, verified_papers=[])
    assert rep_bad["claims"][0]["status"] == "paper_unverified"


def test_strict_uses_live_recomputed(monkeypatch):
    exps = _synthetic_experiments()
    monkeypatch.setattr(cp._sci_exp, "load_experiments", lambda: exps)
    # 模拟 rerun 返回实时重算真值 215.0（与记录 214.5699 略有差，但仍在 1% 内）
    monkeypatch.setattr(
        cp._sci_exp, "rerun_experiment",
        lambda eid: {"status": "reproduced",
                     "recomputed": {"rmse_kcal_mean": {"actual": 215.0, "ok": True}}},
    )
    claims = [{"text": "RMSE", "metric": "rmse_kcal_mean", "value": 215.0,
               "source": "registry:our_hybrid"}]
    rep = cp.verify_claims(claims, strict=True)
    r = rep["claims"][0]
    assert r["status"] == "grounded"
    assert r["truth"] == 215.0          # 用了实时重算真值，而非记录值
    assert "strict" in (r.get("note") or "")


def test_real_coal_registry_grounded():
    """真实 coal_mil 注册表（非 strict，廉价）：our_hybrid 的 rmse 应 grounded。"""
    claims = [{"text": "MIL RMSE", "metric": "rmse_kcal_mean", "value": 214.57,
               "source": "registry:our_hybrid"}]
    rep = cp.verify_claims(claims)
    assert rep["claims"][0]["status"] == "grounded"
    assert rep["claims"][0]["domain"] == "coal-mil"
