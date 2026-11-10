"""成本审计的算术复核测试。

为什么值得单测：成本表是最容易被拍出来的数字。这里锁住三件事——
**算术闭合**（报告值必须等于 token × 单价）、**单价有出处**（每条必须带 source 与检索日期）、
**台账与脚本一致**（`docs/verification/cost_audit.json` 不能和脚本输出各说各话）。
"""
from __future__ import annotations

import importlib.util
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(REPO_ROOT, "docs", "verification", "cost_audit.json")


def _load_module():
    path = os.path.join(REPO_ROOT, "scripts", "cost_audit.py")
    spec = importlib.util.spec_from_file_location("cost_audit_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_totals_are_measured_not_guessed():
    m = _load_module()
    data = m.build()
    t = data["totals"]
    assert t["output_tokens"]["o200k_base"] > 1000, "handoff 产出应有实际 token"
    assert t["input_tokens_lower_bound"]["o200k_base"] > t["output_tokens"]["o200k_base"], \
        "输入侧（技能文档 + 上游上下文）应大于输出侧"
    assert t["local_compute_cost_cny"] == 0.0
    # 7 个阶段都要有记录，缺阶段说明脚本扫漏了
    assert len(data["stages"]) == 7
    assert all(s["output_exists"] for s in data["stages"]), "有阶段的 handoff 产物没找到"


def test_cost_arithmetic_closes():
    """报告的成本必须等于「token × 单价」手算结果，误差只允许来自四舍五入。"""
    m = _load_module()
    data = m.build()
    t = data["totals"]
    out_side = t["output_tokens_counted_for_cost"]
    in_side = t["input_tokens_lower_bound"]
    for c, price in zip(data["cost_per_full_run"], data["pricing"]):
        lo, hi = c["cost_range"]
        expect_lo = (in_side["o200k_base"] * price["input_per_mtok"]
                     + out_side["o200k_base"] * price["output_per_mtok"]) / 1e6
        assert abs(lo - expect_lo) < 5e-4, f"{c['model']} 下界不闭合：{lo} vs {expect_lo}"
        # 两个分词器的结果构成误差带，cl100k 不应低于 o200k
        assert hi >= lo


def test_every_price_has_source_and_date():
    m = _load_module()
    data = m.build()
    assert data["pricing"], "至少给一档公开牌价"
    for p in data["pricing"]:
        assert p["source"].strip(), "单价必须写来源"
        assert p["retrieved"], "单价必须写检索日期"
        assert p["input_per_mtok"] > 0 and p["output_per_mtok"] > 0


def test_ledger_matches_script_output():
    m = _load_module()
    data = m.build()
    with open(LEDGER, encoding="utf-8") as f:
        ledger = json.load(f)
    assert ledger["totals"]["output_tokens"] == data["totals"]["output_tokens"]
    assert ledger["totals"]["input_tokens_lower_bound"] == data["totals"]["input_tokens_lower_bound"]
    assert [c["model"] for c in ledger["cost_per_full_run"]] == [c["model"] for c in data["cost_per_full_run"]]


def test_caveats_are_explicit():
    """成本口径的三条自我限制必须写在产物里，否则后人会把它当账单用。"""
    m = _load_module()
    data = m.build()
    joined = " ".join(data["caveats"])
    for kw in ("下界", "重试", "不是账单"):
        assert kw in joined, f"缺口径说明：{kw}"
