"""verify_papers 第 4 层（CrossRef 标题检索回退）回归测试。

背景：只有标题、没有 DOI 的文献原本只能走 Semantic Scholar 模糊匹配，
无 key 时几乎必然 429 → verify_pending，反幻觉校验对这批文献形同失效。
2026-10-23 实测三篇英文 LIBS 论文时命中该问题（Talanta 那篇 S2 pending）。

需要网络（CrossRef）。无网络或 CrossRef 拒绝时 skip，不算失败。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gewu", "mcp"))

import verify_papers as vp  # noqa: E402

# 真实存在、且首次核验时 S2 限流导致 pending 的那篇
REAL_TITLE = (
    "A temporal and spatial dual-dimension fusion spectra mapping method for "
    "rapid detection of coal quality in laser-induced breakdown spectroscopy"
)
REAL_DOI = "10.1016/j.talanta.2025.128106"

# The P1-1 regression case: Ilse 2018 (ICML) fell through arXiv/CrossRef/S2 as
# "unverified" even though it is real. OpenAlex indexes the ICML proceedings via
# its arXiv DOI and must catch it.
ILSE_TITLE = "Attention-based Deep Multiple Instance Learning"

FAKE_TITLE = (
    "Deep quantum blockchain neural network for perpetual motion energy "
    "harvesting in LIBS spectra"  # 编造，必须判 unverified
)


def _skip_if_pending(status):
    if status == "verify_pending":
        pytest.skip("CrossRef 暂时不可用/限流（verify_pending），非代码缺陷")


def test_real_title_resolves_to_doi():
    status, ids = vp.verify_title_crossref(REAL_TITLE, "test@example.com")
    _skip_if_pending(status)
    assert status == "verified", f"真实论文应被 CrossRef 命中，实际 {status}"
    assert ids and ids.get("doi", "").lower() == REAL_DOI
    assert float(ids["crossref_title_ratio"]) >= 0.82


def test_fabricated_title_is_rejected():
    status, ids = vp.verify_title_crossref(FAKE_TITLE, "test@example.com")
    _skip_if_pending(status)
    assert status == "unverified", "编造标题不能被判为 verified"
    assert ids is None


def test_empty_title_is_unverified():
    assert vp.verify_title_crossref("", "test@example.com") == ("unverified", None)


def test_layer_order_uses_crossref_when_s2_misses(monkeypatch):
    """S2 返回 pending 时，verify_papers 必须继续走 CrossRef 而不是放弃。"""
    monkeypatch.setattr(vp, "verify_title_s2", lambda t, thr: ("verify_pending", None))
    monkeypatch.setattr(
        vp, "verify_title_crossref", lambda t, mail: ("verified", {"doi": REAL_DOI})
    )
    papers = [vp.PaperInput(id="p1", arxiv_id=None, doi=None, title=REAL_TITLE)]
    out = vp.verify_papers(papers, arxiv_batch_size=40, fuzzy_threshold=0.6,
                           user_email="test@example.com", cache=None)
    assert out[0].status == "verified"
    assert out[0].method == "crossref_title_fallback_from_s2"
    assert out[0].identifiers.get("doi") == REAL_DOI


def test_layer_order_uses_openalex_when_s2_crossref_miss(monkeypatch):
    """S2 与 CrossRef 都未命中时，verify_papers 必须继续走 OpenAlex（第 4 层）。
    P1-1 回归：否则 Ilse 2018 (ICML) 这类会议论文会被误判 unverified。"""
    monkeypatch.setattr(vp, "verify_title_s2", lambda t, thr: ("unverified", None))
    monkeypatch.setattr(vp, "verify_title_crossref", lambda t, mail: ("unverified", None))
    monkeypatch.setattr(
        vp, "verify_title_openalex",
        lambda t, mail, threshold=0.82: (
            "verified",
            {"doi": "10.48550/arXiv.1802.04712", "arxiv_id": "1802.04712"},
        ),
    )
    papers = [vp.PaperInput(id="p1", arxiv_id=None, doi=None, title=ILSE_TITLE)]
    out = vp.verify_papers(papers, arxiv_batch_size=40, fuzzy_threshold=0.6,
                           user_email="test@example.com", cache=None)
    assert out[0].status == "verified"
    assert out[0].method == "openalex_title_fallback"
    assert out[0].identifiers.get("arxiv_id") == "1802.04712"


def test_openalex_title_catches_ilse2018():
    """P1-1 真网回归：OpenAlex 应能命中 Ilse 2018（arXiv/CrossRef/S2 曾漏掉）。"""
    status, ids = vp.verify_title_openalex(ILSE_TITLE, "test@example.com")
    _skip_if_pending(status)
    assert status == "verified", f"OpenAlex 应命中 Ilse 2018，实际 {status}"
    assert ids and ids.get("arxiv_id") == "1802.04712"


def test_openalex_exact_doi():
    status = vp.verify_doi_openalex("10.48550/arXiv.1802.04712", "test@example.com")
    _skip_if_pending(status)
    assert status == "verified"


def test_openalex_fabricated_rejected():
    status, ids = vp.verify_title_openalex(FAKE_TITLE, "test@example.com")
    _skip_if_pending(status)
    assert status == "unverified"
    assert ids is None
