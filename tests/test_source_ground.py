#!/usr/bin/env python3
"""D4 原页理解 grounding 测试：用 fitz 现场造一个含已知数值/文本的 PDF，核对 verify_source_span。"""
import fitz
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gewu", "mcp"))
import source_ground as sg  # noqa: E402

PAGE_TEXT = (
    "Table 2. Cross-validation results for the hybrid model.\n"
    "The mean RMSE reaches 218.61 kcal/kg and the coefficient R squared equals 0.8851.\n"
    "The method alleviates the distribution discrepancy between training and test sets.\n"
)


@pytest.fixture
def sample_pdf(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), PAGE_TEXT)
    path = tmp_path / "sample.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def test_grounded_text_value(sample_pdf):
    res = sg.verify_source_span(sample_pdf, page=1, value="218.61 kcal/kg",
                                evidence_type="text")
    assert res["ok"] is True
    assert res["status"] == "grounded_text"
    assert res["evidence_type_detected"] == "text"
    assert "218.61" in res["found_at"]


def test_grounded_text_value_tolerance(sample_pdf):
    # 声明多写了尾零 / 末位误差，应在容忍度内判 grounded
    res = sg.verify_source_span(sample_pdf, page=1, value="218.6100")
    assert res["status"] == "grounded_text"


def test_value_mismatch_flagged(sample_pdf):
    # 书生末位误读 0.8851 -> 0.8551，文本层查不到，应标 figure_suspected
    res = sg.verify_source_span(sample_pdf, page=1, value="0.8551")
    assert res["status"] == "value_not_in_text_layer"
    assert res["evidence_type_detected"] == "figure_suspected"


def test_figure_evidence_honest(sample_pdf):
    # 声明来自图，文本层无该值 -> 诚实标 figure_derived_requires_human
    res = sg.verify_source_span(sample_pdf, page=1, value="0.8551",
                                evidence_type="figure")
    assert res["status"] == "figure_derived_requires_human"
    assert res["evidence_type_detected"] == "figure"


def test_claim_text_substring(sample_pdf):
    res = sg.verify_source_span(sample_pdf, page=1,
                                claim_text="alleviates the distribution discrepancy")
    assert res["status"] == "grounded_text"
    assert "alleviates" in res["found_at"]


def test_claim_text_not_found(sample_pdf):
    res = sg.verify_source_span(sample_pdf, page=1,
                                claim_text="this phrase is absent from the page")
    assert res["status"] == "claim_not_in_text_layer"


def test_page_out_of_range(sample_pdf):
    res = sg.verify_source_span(sample_pdf, page=99, value="218.61")
    assert res["ok"] is False
    assert res["status"] == "page_out_of_range"


def test_missing_file():
    res = sg.verify_source_span("/no/such/file.pdf", page=1, value="1.0")
    assert res["ok"] is False
    assert res["status"] == "pdf_unreadable"


def test_bad_input(sample_pdf):
    res = sg.verify_source_span(sample_pdf, page=1)
    assert res["ok"] is False
    assert res["status"] == "bad_input"
