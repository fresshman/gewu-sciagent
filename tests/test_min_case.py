"""最小课题（七阶段端到端）的正向 + 负向测试。

正向：从零生成数据 → 5 折 → 成稿 → 校验，全链路必须通过。
负向：一个"永远 PASS"的校验器等于没有校验器，所以逐层篡改产物，
      要求校验器必须报错——这才能证明它真的在读数据。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from gewu.demo import pipeline, verify

# 测试用小数据集（加速）；机制与 70 bag 版一致
N_BAGS = 25


@pytest.fixture(scope="module")
def case(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("min_case") / "case"
    pipeline.run(out, n_bags=N_BAGS, offline=True, commit_registry=False)
    return out


@pytest.fixture()
def copy_case(case: Path, tmp_path: Path) -> Path:
    dst = tmp_path / "case_copy"
    shutil.copytree(case, dst)
    return dst


# --------------------------------------------------------------------------
# 正向
# --------------------------------------------------------------------------
def test_full_chain_passes(case: Path) -> None:
    rep = verify.validate(case, determinism=True)
    assert rep["ok"], rep["errors"]
    assert rep["n_checks"] >= 50


def test_seven_handoffs_chained(case: Path) -> None:
    stages = []
    for agent, fname in verify.HANDOFF_FILES:
        p = case / "agents" / agent / fname
        assert p.is_file(), p
        stages.append(json.loads(p.read_text(encoding="utf-8")))
    assert [s["stage"] for s in stages] == list(range(1, 8))
    for i in range(1, 7):
        assert stages[i]["inputs"], f"stage{i + 1} 缺 inputs"
        # 第 i+1 阶段的首个输入应指向第 i 阶段的 handoff
        assert verify.HANDOFF_FILES[i - 1][1] in str(stages[i]["inputs"])


def test_hypothesis_verdict_is_recorded_even_if_negative(case: Path) -> None:
    h4 = json.loads(
        (case / "agents" / "gewu-improver" / "handoff_4_improver.json").read_text(encoding="utf-8")
    )
    v = h4["hypothesis_verdict"]
    assert v["criterion"] and "supported" in v, "假设判定必须有预注册判据与结论"


def test_offline_degrades_honestly(case: Path) -> None:
    h2 = json.loads(
        (case / "agents" / "gewu-ideation" / "handoff_2_litreview.json").read_text(encoding="utf-8")
    )
    d1 = h2["d1_citation_verification"]
    assert d1["status"] != "verified", "离线时不得声称已核验"
    assert d1.get("n_verified", 0) == 0


def test_journal_rank_not_overclaimed(case: Path) -> None:
    h6 = json.loads(
        (case / "agents" / "gewu-publication" / "handoff_6_publication.json").read_text(encoding="utf-8")
    )
    if h6["rank_query"]["status"] != "queried":
        assert all(j["rank_source"] == "local_seed_unverified" for j in h6["journals"])
        assert "未核验" in h6["integrity_note"] or "local_seed_unverified" in h6["integrity_note"]


def test_paper_has_real_citations(case: Path) -> None:
    tex = (case / "report" / "main.tex").read_text(encoding="utf-8")
    assert tex.count("\\bibitem{") >= 3
    assert tex.count("\\cite{") >= 2
    assert "合成" in tex.split("\\section*{摘要}")[1][:200], "摘要首段必须声明合成数据"


# --------------------------------------------------------------------------
# 负向：篡改必须被抓出
# --------------------------------------------------------------------------
def _validate_fails(path: Path) -> list[str]:
    rep = verify.validate(path, determinism=False)
    assert not rep["ok"], "篡改后校验器仍然通过 —— 校验器形同虚设"
    return rep["errors"]


def test_detects_tampered_summary_rmse(copy_case: Path) -> None:
    p = copy_case / "model" / "summary.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["summary"]["hybrid"]["rmse_mean"] = round(d["summary"]["hybrid"]["rmse_mean"] - 30, 4)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    errs = _validate_fails(copy_case)
    assert any("可重算" in e or "口径" in e for e in errs), errs


def test_detects_broken_chain(copy_case: Path) -> None:
    p = copy_case / "agents" / "gewu-writer" / "handoff_5_writer.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["inputs"] = ["handoff_1_direction.json"]
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    errs = _validate_fails(copy_case)
    assert any("stage5" in e for e in errs), errs


def test_detects_false_verified_claim(copy_case: Path) -> None:
    """离线却声称 verified 属于学术不端式失真，必须检出。"""
    p = copy_case / "agents" / "gewu-ideation" / "handoff_2_litreview.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["d1_citation_verification"] = {"status": "verified", "n_verified": 3, "n_checked": 3}
    art = copy_case / "refs" / "refs_verified.json"
    if art.exists():
        art.unlink()
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    errs = _validate_fails(copy_case)
    assert any("D1" in e or "溯源" in e or "核验" in e for e in errs), errs


def test_detects_claim_value_mismatch(copy_case: Path) -> None:
    p = copy_case / "report" / "claims.json"
    claims = json.loads(p.read_text(encoding="utf-8"))
    claims[1]["value"] = claims[1]["value"] - 5.0
    p.write_text(json.dumps(claims, ensure_ascii=False, indent=2), encoding="utf-8")
    errs = _validate_fails(copy_case)
    assert any("数值与源一致" in e for e in errs), errs


def test_detects_dangling_claim_source(copy_case: Path) -> None:
    p = copy_case / "report" / "claims.json"
    claims = json.loads(p.read_text(encoding="utf-8"))
    claims[0]["source"] = {"file": "model/summary.json", "pointer": "/no/such/field"}
    p.write_text(json.dumps(claims, ensure_ascii=False, indent=2), encoding="utf-8")
    errs = _validate_fails(copy_case)
    assert any("源可解析" in e for e in errs), errs


def test_detects_tex_citation_break(copy_case: Path) -> None:
    p = copy_case / "report" / "main.tex"
    tex = p.read_text(encoding="utf-8")
    tex = tex.replace("\\bibitem{ilse2018mil}", "")
    p.write_text(tex, encoding="utf-8")
    errs = _validate_fails(copy_case)
    assert any("文献" in e or "引用" in e for e in errs), errs


def test_detects_registry_mismatch(copy_case: Path) -> None:
    p = copy_case / "registry" / "demo_synth.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["experiments"][2]["metrics"]["rmse_mean"] += 10
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    errs = _validate_fails(copy_case)
    assert any("注册表" in e or "registry" in e.lower() for e in errs), errs


def test_detects_contradiction(copy_case: Path) -> None:
    p = copy_case / "agents" / "gewu-distillation" / "handoff_7_distillation.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["note"] = "SKILL.md 未创建，REPRODUCE.md 缺失"
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    errs = _validate_fails(copy_case)
    assert any("矛盾" in e or "声称" in e for e in errs), errs


# --------------------------------------------------------------------------
# 第 10 层：PDF 成品
# --------------------------------------------------------------------------
def test_pdf_layer_passes_on_real_case(case: Path) -> None:
    """正向：正常链路产出的 PDF 必须通过 PDF 层。"""
    rep = verify.validate(case, determinism=False)
    results = [r for r in rep["results"] if r["layer"] == "10-pdf"]
    assert results, "PDF 层未执行"
    failed = [r for r in results if r["status"] == "FAIL"]
    assert not failed, failed


def test_detects_missing_pdf(copy_case: Path) -> None:
    (copy_case / "report" / "main.pdf").unlink()
    errs = _validate_fails(copy_case)
    assert any("PDF 已生成" in e or "缺失" in e for e in errs), errs


def test_detects_stale_pdf_without_key_numbers(copy_case: Path) -> None:
    """旧 PDF / 损坏 PDF 冒充新结果：handoff 说编译成功，但文件不可解析。"""
    pdf = copy_case / "report" / "main.pdf"
    pdf.write_bytes(b"%PDF-1.4\n% stub, not a real document\n")
    errs = _validate_fails(copy_case)
    assert any("PDF" in e for e in errs), errs


def test_detects_tex_markdown_residue(copy_case: Path) -> None:
    """回归：模板里漏进去的 **粗体** 必须在 lint 阶段被抓到。"""
    p = copy_case / "report" / "main.tex"
    tex = p.read_text(encoding="utf-8")
    tex = tex.replace("\\section{方法}", "\\section{方法}\n标签只在**样**级可得。", 1)
    p.write_text(tex, encoding="utf-8")
    errs = _validate_fails(copy_case)
    assert any("Markdown" in e for e in errs), errs


def test_detects_chinese_without_ctex(copy_case: Path) -> None:
    """回归：中文文档类没加载 ctex 时，编译会"成功"但正文全空，必须提前拦下。"""
    p = copy_case / "report" / "main.tex"
    tex = p.read_text(encoding="utf-8")
    tex = tex.replace(
        "\\documentclass[11pt,a4paper,UTF8]{ctexart}",
        "\\documentclass[11pt,a4paper]{article}\n\\usepackage[utf8]{inputenc}",
        1,
    )
    p.write_text(tex, encoding="utf-8")
    errs = _validate_fails(copy_case)
    assert any("ctex" in e or "CJK" in e for e in errs), errs


# --------------------------------------------------------------------------
# 机制层：MIL 的优势必须来自「定标+上尾」，而不是凑巧
# --------------------------------------------------------------------------
def test_mil_beats_bag_mean_baseline(case: Path) -> None:
    d = json.loads((case / "model" / "summary.json").read_text(encoding="utf-8"))
    assert d["summary"]["mil"]["rmse_mean"] < d["summary"]["plsr"]["rmse_mean"]
    assert d["summary"]["hybrid"]["rmse_mean"] < d["summary"]["mil"]["rmse_mean"]


def test_beta_choice_is_honest(case: Path) -> None:
    """β 允许为 0；不得为了让"LSE 有用"而排除 0。"""
    d = json.loads((case / "model" / "summary.json").read_text(encoding="utf-8"))
    first = d["per_fold"][0]["beta_scores"]
    assert "0" in first, "β=0（均值池化）必须在候选集中，否则结论有偏"


def test_deterministic_rerun(case: Path) -> None:
    d = json.loads((case / "model" / "summary.json").read_text(encoding="utf-8"))
    import numpy as np

    from gewu.demo import mil_lite, synth

    mats, ys_arr, ids, _ = synth.load_bags(case / "data")
    folds = synth.split_folds(case / "data")
    ys = {b: float(v) for b, v in zip(ids, ys_arr)}
    feats = {b: mil_lite.build_features(m) for b, m in zip(ids, mats)}
    again = mil_lite.run_cv(feats, ys, folds)
    for arm in ("plsr", "mil", "hybrid"):
        assert again["summary"][arm]["per_fold_rmse"] == d["summary"][arm]["per_fold_rmse"]
