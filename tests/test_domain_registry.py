"""第二真实领域（clinical-diabetes）的回归测试。

存在理由
--------
`sci_exp` 宣称「机制与学科无关」，但此前只有煤域一个真实领域。这里锁住三件事：

1. 注册表能被引擎加载，且三条实验都标注为 `realizable_by_gewu`（不是只登记不重算）；
2. 引擎真跑 `scripts/run_domain_diabetes.py` 后，指标与登记值在容差内一致 —— 即「换学科后重算链路仍然通」；
3. 重脚本两次逐位一致（可复现），且负向对照（打乱目标）R² 接近 0（无标签泄漏）。

刻意不做的事：不把本域结果与煤域比较（量纲与任务都不同），也不宣称「方法跨域有效」。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "gewu", "mcp"))
import sci_exp as E  # noqa: E402

SCRIPT = os.path.join(REPO_ROOT, "scripts", "run_domain_diabetes.py")
LEDGER = os.path.join(REPO_ROOT, "docs", "verification", "domain2_diabetes.json")


def _run_script(*args: str) -> dict:
    out = subprocess.run(
        [sys.executable, SCRIPT, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
        stdin=subprocess.DEVNULL,
    )
    assert out.returncode == 0, f"脚本失败：{out.stderr[-2000:]}"
    return json.loads(out.stdout)


def test_clinical_domain_registered():
    """三条实验都在台账里，且都可由格物重算（不是「只登记不验证」）。"""
    exps = E.load_experiments()
    clin = {k: v for k, v in exps.items() if v.get("domain") == "clinical-diabetes"}
    assert set(clin) == {"clin_ols_baseline", "clin_pls", "clin_ridge_poly2"}
    for k, v in clin.items():
        assert v["reproducibility"] == "realizable_by_gewu", k
        assert v["rerun"]["type"] == "cli", k
        assert v["metrics"]["rmse_mean"] > 0, k
        assert len(v["metrics"]["per_fold_rmse"]) == 5, k


def test_engine_reproduces_second_domain():
    """引擎真跑重算，指标在容差内一致 —— 这是「机制与学科无关」的实证。"""
    r = E.rerun_experiment("clin_pls")
    assert r["status"] == "reproduced", r
    for key, info in r["recomputed"].items():
        assert info["ok"], f"{key} 超出容差：{info}"


def test_script_is_deterministic():
    """同环境连跑两次必须逐位一致；否则台账数字不可信。"""
    a = _run_script("--json")
    b = _run_script("--json")
    for arm in ("ols", "ridge_poly2", "pls"):
        assert a["summary"][arm]["rmse_mean"] == b["summary"][arm]["rmse_mean"], arm
        assert a["summary"][arm]["per_fold_rmse"] == b["summary"][arm]["per_fold_rmse"], arm


def test_negative_control_has_no_leakage():
    """打乱目标后 R² 必须接近 0：明显为正说明流程把标签漏进了特征侧。"""
    payload = _run_script("--json")
    nc = payload["summary"]["negative_control_ridge_poly2_shuffled_y"]
    assert nc["r2_mean"] < 0.05, f"打乱目标后 R²={nc['r2_mean']:.4f}，疑似标签泄漏"


def test_ledger_matches_registry():
    """docs 台账与注册表不能各说各话。"""
    exps = E.load_experiments()
    with open(LEDGER, encoding="utf-8") as f:
        ledger = json.load(f)
    assert ledger["domain"] == "clinical-diabetes"
    for arm, key in (("ols", "clin_ols_baseline"), ("pls", "clin_pls"), ("ridge_poly2", "clin_ridge_poly2")):
        reg = exps[key]["metrics"]["rmse_mean"]
        led = ledger["summary"][arm]["rmse_mean"]
        assert abs(reg - led) < 0.01, f"{key}: 注册表 {reg} vs 台账 {led}"


def test_engine_stays_domain_agnostic():
    """引擎里不许出现具体学科的名字：出现即说明「与学科解耦」是话术。

    比「git diff 里没改引擎」更稳：后者会被任何一次合法的引擎重构误伤，
    而这条约束的是**原理**——新领域只能以外部注册表 + 脚本的形式接入。
    """
    path = os.path.join(REPO_ROOT, "gewu", "mcp", "sci_exp.py")
    with open(path, encoding="utf-8") as f:
        src = f.read().lower()
    for token in ("diabetes", "clinical", "coal_libs", "libs_spectra"):
        assert token not in src, f"引擎源码出现了领域专属词：{token}"
