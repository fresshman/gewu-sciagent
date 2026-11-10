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


# ── 以下覆盖真实 claims.json 暴露出来的语法坑 ──


@pytest.fixture
def list_registry(monkeypatch):
    """带列表型 metric 的注册表：验证「不写下标不猜」。"""
    exps = {
        "multi": {
            "id": "multi", "domain": "synthetic",
            "metrics": {"per_fold": [1.0, 2.0, 3.0], "scalar": 5.0},
            "reproducibility": "requires_original_script",
        },
    }
    monkeypatch.setattr(cp._sci_exp, "load_experiments", lambda: exps)
    return exps


def test_legacy_anchor_source_still_resolves(patch_registry):
    """`registry:<domain>#<exp>.metrics.<m>` 是真实稿子里出现过的写法，仍须解析。"""
    claims = [{"text": "RMSE", "metric": "rmse_kcal_mean", "value": 214.5699,
               "source": "registry:synthetic#our_hybrid.metrics.rmse_kcal_mean"}]
    r = cp.verify_claims(claims)["claims"][0]
    assert r["status"] == "grounded"
    assert r["source_style"] == "legacy-anchor"
    assert r["experiment_id"] == "our_hybrid"


def test_note_with_colon_does_not_truncate_source(patch_registry):
    """括注里带冒号不能把 exp_id 切断——否则好数字被判成「注册表无此实验」。"""
    claims = [{"text": "R2", "metric": "r2_mean", "value": 0.8963,
               "source": "registry:synthetic#our_hybrid.metrics.r2_mean (源: summary.json)"}]
    r = cp.verify_claims(claims)["claims"][0]
    assert r["status"] == "grounded"
    assert r["experiment_id"] == "our_hybrid"


def test_list_metric_without_index_is_refused(list_registry):
    """列表型 metric 不写下标 → 明确拒绝，不静默取第一项。"""
    r = cp.verify_claims([{"text": "x", "metric": "per_fold", "value": 1.0,
                           "source": "registry:multi"}])["claims"][0]
    assert r["status"] == "metric_not_scalar"
    assert r["length"] == 3


def test_list_metric_with_index_compares_that_element(list_registry):
    r = cp.verify_claims([{"text": "x", "metric": "per_fold[1]", "value": 2.0,
                           "source": "registry:multi"}])["claims"][0]
    assert r["status"] == "grounded"
    assert r["truth"] == 2.0


def test_index_out_of_range(list_registry):
    r = cp.verify_claims([{"text": "x", "metric": "per_fold[9]", "value": 1.0,
                           "source": "registry:multi"}])["claims"][0]
    assert r["status"] == "metric_index_out_of_range"


def test_claim_metric_miss_falls_back_to_source_anchor(patch_registry, list_registry):
    """claim.metric 名字写错、但 source 锚点指得对 → 用锚点救回来，并记录 claim_metric。"""
    r = cp.verify_claims([{"text": "x", "metric": "fold0", "value": 1.0,
                           "source": "registry:synthetic#multi.metrics.per_fold[0]"}])["claims"][0]
    assert r["status"] == "grounded"
    assert r["metric"] == "per_fold[0]"
    assert r["claim_metric"] == "fold0"


def test_scientific_notation_string_value(patch_registry):
    """1.1e-05 这类小量：早先的正则只截到 1.1，会判出个假 drift。"""
    r = cp.verify_claims([{"text": "diff", "metric": "r2_mean", "value": "8.963e-1",
                           "source": "registry:our_hybrid"}])["claims"][0]
    assert r["status"] == "grounded"
    assert r["value"] == pytest.approx(0.8963)


def test_real_claims_json_is_not_green():
    """回归锚点：真实 claims.json 至今 4 条可核、7 条非注册表来源、1 条 metric 不在注册表。

    这条测试的意义是防止有人把「带 source 字段」当成「已核」——数字没动过，
    错的只是指针写法。若将来清理了 claims.json，这条断言需要跟着更新。
    """
    path = os.path.join(ROOT, "output", "documents", "coal_report", "claims.json")
    if not os.path.exists(path):
        pytest.skip("仓库里没有 coal_report/claims.json")
    claims = json.load(open(path, encoding="utf-8"))
    rep = cp.verify_claims(claims)
    assert rep["n_claims"] == 12
    assert rep["n_grounded"] == 4
    assert rep["n_drift"] == 0
    assert not rep["all_grounded"]

