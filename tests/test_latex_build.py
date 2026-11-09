"""LaTeX 编译引擎（``gewu.latex_build``）的正向 + 负向测试。

编译很慢（tectonic 首次要拉 bundle），所以真正的编译用例统一挂 ``needs_engine``：
本机没有引擎时跳过而不是失败——但那三个**判定逻辑**（缺字、TeX error、无引擎）
必须能被测到，否则等于没验证。这三个用构造的日志文本测，不依赖引擎。
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from gewu import latex_build

REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# 引擎探测
# --------------------------------------------------------------------------
def test_find_engine_returns_known_pair() -> None:
    found = latex_build.find_engine()
    if found is None:
        pytest.skip("本机无 LaTeX 引擎")
    name, exe = found
    assert name in {"tectonic", "xelatex", "lualatex", "latexmk", "pdflatex"}
    assert Path(exe).is_file()


def test_find_engine_explicit_bad_path_raises() -> None:
    with pytest.raises(latex_build.LatexEngineError):
        latex_build.find_engine("/definitely/not/here/tectonic")


def test_find_engine_none_when_unavailable(monkeypatch) -> None:
    """PATH 与常见位置都没有引擎时必须返回 None，而不是随便返回一个。"""
    monkeypatch.setattr(latex_build.shutil, "which", lambda _n: None)
    monkeypatch.setattr(latex_build, "_COMMON_ENGINE_PATHS", {"linux": []}, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("GEWU_LATEX_ENGINE", raising=False)
    assert latex_build.find_engine() is None


def test_build_reports_no_engine_instead_of_faking_success(tmp_path: Path, monkeypatch) -> None:
    """无引擎时必须 status=no_engine 且 ok=False —— 不允许静默"成功"。"""
    tex = tmp_path / "a.tex"
    tex.write_text("\\documentclass{article}\\begin{document}x\\end{document}", encoding="utf-8")
    monkeypatch.setattr(latex_build, "find_engine", lambda explicit=None: None)
    r = latex_build.build(tex)
    assert r["ok"] is False
    assert r["status"] == "no_engine"
    assert "tectonic" in r["install_hint"]["tectonic"]


def test_build_missing_file(tmp_path: Path) -> None:
    r = latex_build.build(tmp_path / "nope.tex")
    assert r["ok"] is False and r["status"] == "not_found"


# --------------------------------------------------------------------------
# 日志解析（判定逻辑，不编译）
# --------------------------------------------------------------------------
def test_parse_log_detects_tex_error() -> None:
    log = "! Undefined control sequence.\nl.5 \\foo\n"
    p = latex_build._parse_log(log)
    assert p["errors"] == ["! Undefined control sequence."]


def test_parse_log_detects_missing_glyphs() -> None:
    """中文掉字是 Missing character，不是 error；单看退出码会漏判。"""
    log = 'Missing character: There is no 摘 ("6458) in font ec-lmbx12!\n'
    p = latex_build._parse_log(log)
    assert len(p["missing_glyphs"]) == 1
    assert "摘" in p["missing_glyphs"][0]


def test_parse_log_detects_undefined_citation_and_ref() -> None:
    log = (
        "LaTeX Warning: Citation `p9' on page 1 undefined on input line 10.\n"
        "LaTeX Warning: Reference `sec:x' on page 2 undefined on input line 20.\n"
    )
    p = latex_build._parse_log(log)
    assert p["undefined_citations"] == ["p9"]
    assert p["undefined_references"] == ["sec:x"]


def test_parse_log_counts_overfull() -> None:
    log = "Overfull \\hbox (12.3pt too wide) in paragraph at lines 1--2\n" * 3
    assert latex_build._parse_log(log)["overfull_hbox"] == 3


def test_parse_log_clean_log() -> None:
    p = latex_build._parse_log("This is XeTeX\nOutput written on main.pdf (3 pages).\n")
    assert p == {
        "errors": [],
        "missing_glyphs": [],
        "undefined_citations": [],
        "undefined_references": [],
        "overfull_hbox": 0,
    }


# --------------------------------------------------------------------------
# 真实编译
# --------------------------------------------------------------------------
needs_engine = pytest.mark.skipif(
    latex_build.find_engine() is None, reason="本机无 LaTeX 引擎"
)

GOOD_TEX = r"""\documentclass[11pt]{ctexart}
\begin{document}
\section{测试}
中文正文，数值 $214.57$ kcal/kg。
\end{document}
"""

BAD_TEX = r"""\documentclass{article}
\begin{document}
\thisMacroDoesNotExist
\end{document}
"""

# article 不含 CJK 支持：中文会被记成 Missing character 并丢弃
NO_CJK_TEX = r"""\documentclass{article}
\usepackage[utf8]{inputenc}
\begin{document}
中文正文会被丢弃
\end{document}
"""


@needs_engine
def test_build_success(tmp_path: Path) -> None:
    tex = tmp_path / "good.tex"
    tex.write_text(GOOD_TEX, encoding="utf-8")
    r = latex_build.build(tex, out_dir=tmp_path / "out", timeout=600)
    assert r["ok"], r
    assert r["status"] == "ok"
    assert Path(r["pdf"]).is_file() and r["pdf_bytes"] > 0
    assert r["log"]["errors"] == []
    assert r["log"]["missing_glyphs"] == []
    # 中文真的进了 PDF
    assert "中文正文" in latex_build.pdf_text(r["pdf"])


@needs_engine
def test_build_tex_error_is_not_success(tmp_path: Path) -> None:
    tex = tmp_path / "bad.tex"
    tex.write_text(BAD_TEX, encoding="utf-8")
    r = latex_build.build(tex, out_dir=tmp_path / "out", timeout=600)
    assert r["ok"] is False
    assert r["status"] == "compile_error"
    assert r["log"]["errors"], "应记录 TeX error"


@needs_engine
def test_build_chinese_without_ctex_fails(tmp_path: Path) -> None:
    """回归：article+fontenc 写中文，编译"成功"但正文全空，必须判失败。"""
    tex = tmp_path / "nocjk.tex"
    tex.write_text(NO_CJK_TEX, encoding="utf-8")
    r = latex_build.build(tex, out_dir=tmp_path / "out", timeout=600)
    assert r["ok"] is False, "缺字必须判失败，否则会交出空白 PDF"
    assert r["log"]["missing_glyphs"]
    assert "字形缺失" in r["reason"]


@needs_engine
def test_pdf_page_count(tmp_path: Path) -> None:
    tex = tmp_path / "good.tex"
    tex.write_text(GOOD_TEX, encoding="utf-8")
    r = latex_build.build(tex, out_dir=tmp_path / "out", timeout=600)
    assert latex_build.pdf_page_count(r["pdf"]) == 1


# --------------------------------------------------------------------------
# 内容指纹
# --------------------------------------------------------------------------
@needs_engine
def test_fingerprint_stable_across_rebuilds(tmp_path: Path) -> None:
    """同一 tex 连编两次：二进制哈希不同（内嵌时间戳），内容指纹必须相同。"""
    tex = tmp_path / "good.tex"
    tex.write_text(GOOD_TEX, encoding="utf-8")
    digests, bins = [], []
    for i in range(2):
        r = latex_build.build(tex, out_dir=tmp_path / f"o{i}", timeout=600)
        assert r["ok"], r
        digests.append(latex_build.pdf_text_fingerprint(r["pdf"]))
        bins.append(hashlib.sha256(Path(r["pdf"]).read_bytes()).hexdigest())
    assert digests[0] == digests[1]
    assert bins[0] != bins[1], "若二进制一致，说明该引擎去掉了时间戳，测试前提需更新"


def test_fingerprint_normalizes_date(tmp_path: Path, monkeypatch) -> None:
    """日期归一化：只有 YYYY-MM-DD 不同的两份文本，指纹应相同。"""
    monkeypatch.setattr(latex_build, "pdf_text", lambda _p: "报告 2026-11-09 结论 73.03")
    a = latex_build.pdf_text_fingerprint("x")
    monkeypatch.setattr(latex_build, "pdf_text", lambda _p: "报告 2026-12-31 结论 73.03")
    b = latex_build.pdf_text_fingerprint("x")
    assert a == b and a

    monkeypatch.setattr(latex_build, "pdf_text", lambda _p: "报告 2026-12-31 结论 99.99")
    assert latex_build.pdf_text_fingerprint("x") != a


def test_fingerprint_empty_when_no_text(monkeypatch) -> None:
    monkeypatch.setattr(latex_build, "pdf_text", lambda _p: "")
    assert latex_build.pdf_text_fingerprint("x") == ""


# --------------------------------------------------------------------------
# 命令行入口（README 里承诺过，必须真的能用）
# --------------------------------------------------------------------------
@needs_engine
def test_cli_success(tmp_path: Path) -> None:
    tex = tmp_path / "good.tex"
    tex.write_text(GOOD_TEX, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "gewu.latex_build", str(tex), "--out", str(tmp_path / "o")],
        cwd=REPO, capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    assert "OK" in proc.stdout


def test_cli_failure_exit_code(tmp_path: Path) -> None:
    tex = tmp_path / "none.tex"
    proc = subprocess.run(
        [sys.executable, "-m", "gewu.latex_build", str(tex)],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 1
    assert "FAIL" in proc.stdout
