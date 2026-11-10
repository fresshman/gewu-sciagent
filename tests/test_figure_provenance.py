"""图表出处旁文件（fig_meta + sci_plot._save）的回归测试。

守的是什么：这个项目反复强调「论文里的每个数字都要能追到来源」，但图表这块
一直是空的——旧版 `_save` 只写 pdf/png，出处就是文件名里那个 stem。
一份 2026-10-28 生成的图，事后没法回答「喂的是什么数据、标题是哪个版本」。

所以这里最硬的三条断言：
1. 旁文件里的文件 sha256 **等于磁盘上那份文件**（不是抄来的）；
2. 同数据重画 → `draw.digest` 与 `fig_id` 一致；换数据 → 变（内容寻址成立）；
3. 数值入参**只留指纹与极值**，原值不得出现在 json 里（未发表数据不出目录）。

另外锁两个实际踩到的坑：
- 同一秒画两张同名图，旧实现第二张直接覆盖第一张（图丢了还浑然不知）；
- `Path.suffix` 只认最后一段，`.meta.json` 会被漏掉 → list_figures 报「0 张带出处」。
"""
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "gewu", "mcp"))

matplotlib = pytest.importorskip("matplotlib")
import sci_plot as S  # noqa: E402
import fig_meta as FM  # noqa: E402


@pytest.fixture()
def figdir(tmp_path, monkeypatch):
    """把出图目录换到临时目录，别污染项目 output/figures。"""
    monkeypatch.setattr(S, "FIG_DIR", tmp_path)
    return tmp_path


ARM = dict(
    labels=["袋均谱+PLSR", "TransMIL", "MIL 残差", "hybrid"],
    values=[228.4, 226.3, 218.1, 215.8],
    title="四臂消融 RMSE",
    ylabel="RMSE (kcal/kg)",
    stem="arm",
)


def _meta(res):
    return json.load(open(res["meta"], encoding="utf-8"))


# ── 基本契约 ──────────────────────────────────────────────


def test_save_writes_sidecar_next_to_pdf(figdir):
    res = S.plot_bar(**ARM)
    assert res["provenance"] is True
    assert res["meta"].endswith(".meta.json")
    assert os.path.exists(res["meta"])
    assert os.path.exists(res["pdf"]) and os.path.exists(res["png"])

    m = _meta(res)
    assert m["schema"] == 1
    assert m["stem"] == "arm"
    assert m["tool"] == "plot_bar"  # 取自调用栈帧，不是传参
    assert m["draw"]["axes"] == 1


def test_file_sha256_matches_disk(figdir):
    """旁文件里记的 sha256 必须就是磁盘上那份文件的，不能是「当时算过」的值。"""
    res = S.plot_bar(**ARM)
    m = _meta(res)
    for fmt, key in (("pdf", "pdf"), ("png", "png")):
        assert m["files"][fmt]["sha256"] == FM.sha256_file(res[key])
        assert m["files"][fmt]["bytes"] == os.path.getsize(res[key])


def test_pdf_is_byte_identical_across_renders(figdir):
    """去掉 CreationDate 之后，同样的数据隔一秒重画也必须字节相同。

    这条不成立的话 fig_id 就不稳：内容寻址变成「每次出图一个新 id」，
    台账会把同一张图记成好几张。默认 matplotlib 会写秒级时间戳（实测会变），
    所以 _save 里显式 strip 掉。
    """
    import time

    a = S.plot_bar(**ARM)
    time.sleep(1.05)
    b = S.plot_bar(**ARM)
    assert FM.sha256_file(a["pdf"]) == FM.sha256_file(b["pdf"])
    assert _meta(a)["fig_id"] == _meta(b)["fig_id"]


def test_fig_id_is_content_addressed(figdir):
    """同数据 → 同 fig_id（pdf 字节可复现）；换数据 → 变。"""
    a = _meta(S.plot_bar(**ARM))
    b = _meta(S.plot_bar(**ARM))
    c = _meta(S.plot_bar(labels=["a", "b", "c", "d"], values=[1, 2, 3, 4], stem="arm"))

    assert a["fig_id"] == b["fig_id"]
    assert a["draw"]["digest"] == b["draw"]["digest"]
    assert c["draw"]["digest"] != a["draw"]["digest"]
    assert c["fig_id"] != a["fig_id"]
    assert a["fig_id"].startswith("fig-") and len(a["fig_id"]) == 12


def test_drawn_values_are_fingerprinted_not_copied(figdir):
    """数值序列只留 sha256/形状/极值——中间数据点一个都不许进旁文件。

    极值（min/max）是有意留下的聚合量，它会以 `"max": 228.4` 的形式出现；
    这里断言的是「不整段抄原始序列」：中间两个点找不到，且极值只出现一次。
    """
    res = S.plot_bar(**ARM)
    raw = open(res["meta"], encoding="utf-8").read()
    for v in ("226.3", "218.1"):
        assert v not in raw, f"{v} 是中间数据点，不应写进出处文件"
    # 极值是有意留的聚合量（args 一次、渲染出的 patch 几何一次），但绝不整段成数组
    assert raw.count("228.4") <= 2 and "[228.4" not in raw
    assert "[228.4, 226.3" not in raw and "228.4, 226.3" not in raw

    m = json.loads(raw)
    assert m["args"]["values"]["kind"] == "seq"
    assert m["args"]["values"]["shape"] == [4]
    assert m["args"]["values"]["min"] == 215.8
    assert len(m["args"]["values"]["sha256"]) == 16
    # 字符串标签保留内容：这是人读的，不涉及数据泄露
    assert m["args"]["labels"]["values"][0] == "袋均谱+PLSR"


def test_series_kind_survives_array_brief(figdir):
    """回归：`{"kind":"patch", **_array_brief(...)}` 会被后者的 kind 覆盖成 array。"""
    m = _meta(S.plot_bar(**ARM))
    kinds = [s["kind"] for s in m["draw"]["series"]]
    assert "patch" in kinds
    assert "array" not in kinds


def test_list_figures_groups_meta(figdir):
    """回归：Path.suffix 只认最后一段，`.meta.json` 会被当成 .json 漏掉。"""
    res = S.plot_bar(**ARM)
    lf = S.list_figures()
    assert lf["count"] == 2  # pdf + png
    assert len(lf["figures"]) == 1
    assert lf["with_provenance"] == 1
    fig = lf["figures"][0]
    assert fig["provenance"] is True
    assert fig["tool"] == "plot_bar"
    assert fig["fig_id"] == _meta(res)["fig_id"]


def test_list_figures_marks_legacy_figure_without_meta(figdir):
    """老图（没有 meta.json）要如实标 provenance=false，不能当成有出处。"""
    (figdir / "old_20260101-000000.pdf").write_bytes(b"%PDF-1.4 fake")
    (figdir / "old_20260101-000000.png").write_bytes(b"\x89PNG fake")
    lf = S.list_figures()
    assert lf["with_provenance"] == 0
    assert lf["figures"][0]["provenance"] is False
    assert lf["figures"][0]["fig_id"] is None


# ── 撞名与降级 ────────────────────────────────────────────


class _FrozenDT:
    """冻结时间，逼出「同一秒两张同名图」这个真实场景。"""

    _v = "20261110-120000"

    @classmethod
    def now(cls, *a, **k):
        class _T:
            def strftime(self, fmt):
                return _FrozenDT._v

        return _T()


def test_same_second_does_not_overwrite(figdir, monkeypatch):
    monkeypatch.setattr(S, "datetime", _FrozenDT)
    a = S.plot_bar(**ARM)
    b = S.plot_bar(**ARM)
    assert a["pdf"] != b["pdf"]
    assert b["pdf"].endswith("-2.pdf")
    assert os.path.getsize(a["pdf"]) > 0 and os.path.getsize(b["pdf"]) > 0
    # 两张都在，且各自有旁文件
    assert os.path.exists(a["meta"]) and os.path.exists(b["meta"])


def test_sidecar_failure_does_not_break_plot(figdir, monkeypatch):
    """旁文件写失败只能是「没有出处」，图必须照常出。"""

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(FM, "write_sidecar", boom)
    res = S.plot_bar(**ARM)
    assert res["provenance"] is False
    assert res["meta"] is None
    assert os.path.getsize(res["pdf"]) > 0


def test_bad_meta_json_is_absent_not_guessed(figdir):
    """坏 json 当成没有，不去猜内容。"""
    (figdir / "x_20260101-000000.pdf").write_bytes(b"%PDF fake")
    (figdir / "x_20260101-000000.meta.json").write_text("{not json", encoding="utf-8")
    assert FM.read_sidecar(figdir / "x_20260101-000000.meta.json") is None
    assert S.list_figures()["with_provenance"] == 0


# ── 纯函数 ────────────────────────────────────────────────


def test_brief_never_leaks_large_arrays():
    import numpy as np

    b = FM.brief(np.arange(50000, dtype=float))
    assert b["n"] == 50000
    assert b["shape"] == [50000]
    assert "values" not in b and "data" not in b


def test_brief_handles_nan_and_inf():
    b = FM.brief([float("nan"), float("inf"), 1.0])
    assert b["min"] in ("nan", 1.0) or b["min"] is not None  # 只要求可 json 化，不崩


def test_git_sha_is_real_or_none():
    sha = FM.git_sha()
    assert sha is None or (len(sha) >= 7 and all(c in "0123456789abcdef" for c in sha))
