"""Web 右栏 case bundle 的一致性测试。

右栏是唯一给评委看的 UI，最容易出的问题不是「接口 500」，而是
**数字对不上**：UI 显示 7.9%、论文写 8.28%；或者把仓库快照当成
本机实测展示。这里锁住三件事：

1. 三级取数（本机真源 → 本机重算 → 仓库快照）都能产出可用 bundle，
   且快照模式必须带「非本机重算」标注；
2. ``validate_bundle`` 真的能抓错——篡改数值、删文献、去掉消融口径
   警示，每一条都必须被检出（否则校验器就是橡皮章）；
3. 文献解析的边界：arXiv 编号不能被当成出版年，非 \\textit 的出版方
   也要能识别。

不依赖网络；无外部课题时走仓库快照，因此评委机也能跑。
"""
import copy
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import export_case_bundle as E  # noqa: E402


def _bundle_without_local_truth(monkeypatch) -> dict:
    """模拟评委机：本机重算产物不存在，也没有外部课题根。"""
    monkeypatch.setattr(E, "TRUTH_FILE", Path("Z:/definitely-not-here/metrics_recomputed.json"))
    return E.build_bundle(None)


# --------------------------------------------------------------------------- #
# 正向：能产出、且数字与论文口径一致
# --------------------------------------------------------------------------- #
def test_snapshot_fallback_available(monkeypatch):
    """无本机真源、无外部项目时，必须回退到仓库快照而不是留下空白右栏。"""
    if not E.REPO_SNAPSHOT.is_file():
        pytest.skip("仓库快照未生成（python scripts/export_case_bundle.py --emit-snapshot）")
    b = _bundle_without_local_truth(monkeypatch)
    assert b["available"] is True
    assert b["mode"] == "repo_snapshot"
    assert "非本机重算" in b["mode_label"]
    assert E.validate_bundle(b) == []


def test_metrics_match_paper(monkeypatch):
    """右栏数字必须与论文正文一致：214.57 / 233.95 / 8.28% / p=0.041。"""
    if not E.REPO_SNAPSHOT.is_file():
        pytest.skip("仓库快照未生成")
    b = _bundle_without_local_truth(monkeypatch)
    m = b["metrics"]
    assert m["hybrid"]["summary"]["rmse"]["mean"] == pytest.approx(214.5699, abs=0.01)
    assert m["plsr_baseline"]["summary"]["rmse"]["mean"] == pytest.approx(233.9521, abs=0.01)
    assert m["improvement_pct"] == pytest.approx(8.28, abs=0.02)
    pt = m["paired_test"]
    assert pt["available"] is True
    assert pt["p"] == pytest.approx(0.041, abs=0.002)
    assert pt["mean_diff"] < 0
    assert pt["ci95"][0] < pt["ci95"][1] < 0


def test_two_conventions_are_distinct(monkeypatch):
    """逐折均值与合并 OOF 是两个口径，必须同时给出且数值不同。"""
    if not E.REPO_SNAPSHOT.is_file():
        pytest.skip("仓库快照未生成")
    m = _bundle_without_local_truth(monkeypatch)["metrics"]
    pooled = m["improvement_pct_pooled"]
    assert pooled is not None
    assert pooled > 0 and m["improvement_pct"] > 0
    assert pooled != m["improvement_pct"], "两口径数值相同，说明其中一处在冒用另一处的口径"
    assert m["hybrid"]["pooled"]["rmse"] > m["hybrid"]["summary"]["rmse"]["mean"], (
        "合并 OOF 的 RMSE 通常略高于逐折均值（本文 216.10 vs 214.57），若反了需检查口径"
    )


def test_papers_all_verified_and_complete():
    """论文引用几篇，右栏就展示几篇，且每篇都要有 D1 核验结论。"""
    papers = E.build_papers()
    bib = E._parse_bibitems()
    if not bib:
        pytest.skip("未找到 main.tex 的 bibliography")
    assert len(papers) == len(bib)
    assert {p["status"] for p in papers} == {"verified"}
    assert all(p["title"] for p in papers)
    summary = E.refs_summary()
    assert summary and summary["verdict"] == "PASS"


def test_ablation_carries_caveat():
    """消融与最终配置不同组，caveat 缺了就会被误读成「可相减」。"""
    abl = E.build_ablation()
    assert abl is not None
    assert abl["caveat"].strip()
    assert len(abl["pooling"]) == 6 and len(abl["path"]) == 4
    # 组内按 RMSE 升序
    rm = [x["rmse"] for x in abl["pooling"]]
    assert rm == sorted(rm)


def test_component_ablation_is_its_own_group():
    """组件级消融是第三组（基准 215.75），不得混进 pooling/path 与 347.55 那组排序。"""
    abl = E.build_ablation()
    assert abl is not None
    comp = abl.get("component") or []
    assert len(comp) == 4
    assert all(x["id"].startswith("abl_comp_") for x in comp)
    assert not [x for x in abl["pooling"] + abl["path"] if x["id"].startswith("abl_comp_")]
    assert (abl.get("component_caveat") or "").strip()
    # 三组基准互不相同，caveat 必须说清「不可相减」
    assert "不可相减" in abl["component_caveat"]
    rm = [x["rmse"] for x in comp]
    assert rm == sorted(rm)


# --------------------------------------------------------------------------- #
# 文献解析边界
# --------------------------------------------------------------------------- #
def test_arxiv_id_is_not_a_year():
    """`arXiv:1402.2060` 里的 2060 不能被当成出版年。"""
    item = E._split_bibitem(
        "The application of spectrum standardization method for carbon analysis "
        "in coal using laser-induced breakdown spectroscopy. arXiv:1402.2060."
    )
    assert item["year"] is None
    assert item["arxiv"] == "1402.2060"


def test_venue_without_textit():
    """`... Spectroscopy. Wiley, 2021.` 要能识别出版方 Wiley。"""
    item = E._split_bibitem(
        "Coal Analysis by Laser-Induced Breakdown Spectroscopy. Wiley, 2021. "
        "DOI: 10.1002/9781119758396.ch27."
    )
    assert item["venue"] == "Wiley"
    assert item["year"] == 2021


# --------------------------------------------------------------------------- #
# 负向：校验器必须真能抓错
# --------------------------------------------------------------------------- #
@pytest.fixture()
def bundle(monkeypatch):
    if not E.REPO_SNAPSHOT.is_file():
        pytest.skip("仓库快照未生成")
    return _bundle_without_local_truth(monkeypatch)


def test_detects_tampered_metric(bundle):
    b = copy.deepcopy(bundle)
    b["metrics"]["hybrid"]["summary"]["rmse"]["mean"] = 999.99
    errs = E.validate_bundle(b)
    assert any("hybrid.mean_rmse" in e or "汇总均值" in e for e in errs), errs


def test_detects_dropped_paper(bundle):
    b = copy.deepcopy(bundle)
    b["papers"] = b["papers"][:-1]
    errs = E.validate_bundle(b)
    assert any("bibitem" in e for e in errs), errs


def test_detects_unverified_paper(bundle):
    b = copy.deepcopy(bundle)
    b["papers"][0]["status"] = "pending"
    errs = E.validate_bundle(b)
    assert any("未核验" in e for e in errs), errs


def test_detects_missing_ablation_caveat(bundle):
    b = copy.deepcopy(bundle)
    b["ablation"]["caveat"] = "  "
    errs = E.validate_bundle(b)
    assert any("caveat" in e for e in errs), errs


def test_detects_unlabelled_snapshot(bundle):
    b = copy.deepcopy(bundle)
    b["mode"] = "repo_snapshot"
    b["mode_label"] = ""
    errs = E.validate_bundle(b)
    assert any("mode_label" in e for e in errs), errs


def test_detects_inconsistent_significance(bundle):
    """p 显著却给出正差值，方向自相矛盾，必须报错。"""
    b = copy.deepcopy(bundle)
    b["metrics"]["paired_test"]["p"] = 0.01
    b["metrics"]["paired_test"]["mean_diff"] = 5.0
    errs = E.validate_bundle(b)
    assert any("矛盾" in e for e in errs), errs


def test_detects_missing_pooled_convention(bundle):
    b = copy.deepcopy(bundle)
    b["metrics"]["improvement_pct_pooled"] = None
    errs = E.validate_bundle(b)
    assert any("pooled" in e for e in errs), errs
