"""D3 引用完整性 lint 回归测试。"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gewu", "mcp"))
import citation_lint as cl  # noqa: E402


SAMPLE_TEX = r"""
前文 \cite{ilse2018, resnet2016} 已有研究 \citep{vaswani2017}。
我们与 \citet{li2020cn, wang2021} 对比，另见 \autocite{ghost2022}。
"""


def test_extract_cite_keys():
    keys = cl.extract_cite_keys(SAMPLE_TEX)
    assert keys == ["ilse2018", "resnet2016", "vaswani2017", "li2020cn", "wang2021", "ghost2022"]


def test_all_verified():
    rep = cl.lint_citations(["a", "b"], verified_papers=["a", "b"])
    assert rep["all_verified"] is True
    assert rep["n_phantom"] == 0
    assert all(r["status"] == "verified" for r in rep["citations"])


def test_phantom_detected():
    rep = cl.lint_citations(["a", "ghost"], verified_papers=["a"])
    assert rep["all_verified"] is False
    ghost = [r for r in rep["citations"] if r["key"] == "ghost"][0]
    assert ghost["status"] == "phantom"
    assert rep["n_phantom"] == 1


def test_chinese_degradation_not_phantom():
    """P1-2：中文文献人工确认后标 accepted_unverified，而非误判 phantom。"""
    rep = cl.lint_citations(
        ["ilse2018", "li2020cn"],
        verified_papers=["ilse2018"],
        manually_confirmed=["li2020cn"],
    )
    by_key = {r["key"]: r["status"] for r in rep["citations"]}
    assert by_key["ilse2018"] == "verified"
    assert by_key["li2020cn"] == "accepted_unverified"
    assert rep["all_verified"] is True
    assert rep["n_phantom"] == 0


def test_tex_and_explicit_merge():
    keys = ["explicit1"] + cl.extract_cite_keys(SAMPLE_TEX)
    rep = cl.lint_citations(
        keys, verified_papers=["ilse2018", "resnet2016", "vaswani2017", "explicit1"],
    )
    keys = {r["key"] for r in rep["citations"]}
    assert "ghost2022" in keys
    assert "explicit1" in keys
    # ghost2022 不在任何集合 → phantom
    ghost = [r for r in rep["citations"] if r["key"] == "ghost2022"][0]
    assert ghost["status"] == "phantom"
