#!/usr/bin/env python3
"""T1 压缩层测试：摘要逐字保数值、原文可字节级回取、越权路径拒绝读取。

核心不是"压得小"，而是"压完仍可溯源"——所以断言全部围绕
`expand()` 取回的内容 == 原 payload，以及 digest 里的数值 == 原文数值。
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gewu", "mcp"))
import context_compactor as cc  # noqa: E402

_PREFIX = "F:/external/coal-calorific-value/data/赛题数据划分/训练集"


@pytest.fixture
def raw_dir(tmp_path, monkeypatch):
    d = tmp_path / "mcp-raw"
    monkeypatch.setenv("GEWU_MCP_RAW_DIR", str(d))
    monkeypatch.delenv("GEWU_MCP_COMPACT", raising=False)
    return str(d).replace("\\", "/")


def _bags(n=14):
    return {
        "fold": 0,
        "n_total_bags": 70,
        "n_val_bags": n,
        "mean_rmse_kcal_kg": 214.5699,
        "std_rmse_kcal_kg": 25.7094,
        "val_bags": [
            {
                "bag_id": f"中马矿中煤矿11月{14 + i}日",
                "mine": "中马矿中煤矿",
                "bag_dir": f"{_PREFIX}/中马矿中煤矿11月{14 + i}日",
                "n_spectra": 12,
                "y_true_kcal_kg": 2931.0 + i,
            }
            for i in range(n)
        ],
    }


def _lines(s):
    return json.dumps(s, ensure_ascii=False) if not isinstance(s, str) else s


def test_small_result_passes_through(raw_dir):
    payload = {"mean_rmse_kcal_kg": 214.5699, "n_folds": 5}
    assert cc.compact(payload, server="mil-model", tool="cv_summary") == payload
    assert not os.path.exists(raw_dir), "小结果不该落盘、不该有额外往返"


def test_disable_switch_returns_raw(raw_dir, monkeypatch):
    monkeypatch.setenv("GEWU_MCP_COMPACT", "0")
    payload = _bags()
    assert cc.compact(payload, server="mil-model", tool="list_val_bags") == payload


def test_digest_keeps_top_level_numbers_verbatim(raw_dir):
    payload = _bags()
    env = cc.compact(payload, server="mil-model", tool="list_val_bags")
    assert env["__compacted"] == cc.VERSION
    dg = env["digest"]
    for k in ("fold", "n_total_bags", "n_val_bags",
              "mean_rmse_kcal_kg", "std_rmse_kcal_kg"):
        assert dg[k] == payload[k], f"顶层数值被改写了：{k}"
    # 内联条目的每个数值都必须与原文一致
    for item, origin in zip(dg["val_bags"]["items"], payload["val_bags"]):
        for k in ("n_spectra", "y_true_kcal_kg"):
            assert item[k] == origin[k]
        assert item["bag_id"] == origin["bag_id"]
    assert dg["val_bags"]["_list"] == len(payload["val_bags"])
    assert dg["val_bags"]["more"] == f"[{cc._head()}:{len(payload['val_bags'])}]"


def test_numeric_range_is_computed_from_original(raw_dir):
    env = cc.compact(_bags(), server="mil-model", tool="list_val_bags")
    agg = env["digest"]["val_bags"]["numeric_min_max"]["y_true_kcal_kg"]
    assert agg == {"min": 2931.0, "max": 2944.0, "n": 14}


def test_long_paths_get_prefix_extracted_then_recovered_exactly(raw_dir):
    payload = _bags()
    env = cc.compact(payload, server="mil-model", tool="list_val_bags")
    lb = env["digest"]["val_bags"]
    prefix = lb["_prefix"]["bag_dir"]
    assert prefix.startswith(_PREFIX)
    # 不变量：完整值 = 前缀 + 摘要里的剩余（摘要视图可复原，不是丢信息）
    for item, origin in zip(lb["items"], payload["val_bags"]):
        assert prefix + item["bag_dir"] == origin["bag_dir"]

    got = cc.expand(env["__raw_path"], "val_bags[*].bag_dir", server="mil-model")
    assert got["status"] == "ok"
    assert got["value"] == [b["bag_dir"] for b in payload["val_bags"]]


def test_expand_whole_file_is_byte_equal_to_payload(raw_dir):
    payload = _bags()
    env = cc.compact(payload, server="mil-model", tool="list_val_bags")
    got = cc.expand(env["__raw_path"], "", server="mil-model")
    assert got["status"] == "ok"
    assert _lines(got["value"]) == _lines(payload)


def test_expand_slice_and_fields_projection(raw_dir):
    payload = _bags()
    env = cc.compact(payload, server="mil-model", tool="list_val_bags")
    s = cc.expand(env["__raw_path"], "val_bags[10:14]", server="mil-model")
    assert s["value"] == payload["val_bags"][10:14]
    p = cc.expand(env["__raw_path"], "val_bags[10:14]",
                  fields=["bag_id", "y_true_kcal_kg"], server="mil-model")
    assert p["value"][0] == {"bag_id": "中马矿中煤矿11月24日", "y_true_kcal_kg": 2941.0}


def test_composed_selectors_chain(raw_dir):
    payload = _bags()
    env = cc.compact(payload, server="mil-model", tool="list_val_bags")
    got = cc.expand(env["__raw_path"], "val_bags[8:14][0:2].bag_id", server="mil-model")
    assert got["value"] == ["中马矿中煤矿11月22日", "中马矿中煤矿11月23日"]
    star = cc.expand(env["__raw_path"], "val_bags[*].n_spectra", server="mil-model")
    assert star["value"] == [12] * 14


def test_oversized_slice_compacts_again_without_losing_bytes(raw_dir):
    monkey = _bags(n=60)
    env = cc.compact(monkey, server="mil-model", tool="reproduce_fold",
                     limit=1200, head=4)
    big = cc.expand(env["__raw_path"], "val_bags[0:60]", server="mil-model",
                    max_chars=1200)
    assert big["__compacted"] == cc.VERSION
    assert big["selector_base"] == "val_bags[0:60]"
    assert big["__raw_path"] == env["__raw_path"]
    # 再压一层后，原始 60 条仍能一次取全（放大 max_chars）
    full = cc.expand(env["__raw_path"], "val_bags[0:60]", server="mil-model",
                     max_chars=2_000_000)
    assert full["value"] == monkey["val_bags"]


def test_paths_outside_raw_dir_are_refused(raw_dir):
    env = cc.compact(_bags(), server="mil-model", tool="list_val_bags")
    outside = os.path.join(ROOT, "requirements.txt").replace("\\", "/")
    got = cc.expand(outside, "", server="mil-model")
    assert got["status"] == "error"
    assert "只允许读取落盘目录" in got["detail"]
    # .. 逃逸同样拦得住：realpath 之后仍在落盘目录外
    sneaky = os.path.join(raw_dir, "..", "requirements.txt").replace("\\", "/")
    assert cc.expand(sneaky, "", server="mil-model")["status"] == "error"


def test_missing_raw_file_tells_agent_to_rerun_tool(raw_dir):
    env = cc.compact(_bags(), server="mil-model", tool="list_val_bags")
    os.remove(env["__raw_path"].replace("/", os.sep))
    got = cc.expand(env["__raw_path"], "", server="mil-model")
    assert got["status"] == "error"
    assert "重新调用原工具" in got["detail"]


def test_bad_selector_reports_available_keys(raw_dir):
    env = cc.compact(_bags(), server="mil-model", tool="list_val_bags")
    got = cc.expand(env["__raw_path"], "no_such_field", server="mil-model")
    assert got["status"] == "error"
    assert "val_bags" in got["detail"]
    got2 = cc.expand(env["__raw_path"], "val_bags[0:3", server="mil-model")
    assert got2["status"] == "error"
    assert "]" in got2["detail"]


def test_long_string_headed_not_cut_midway(raw_dir):
    payload = {"note": "热值预测" * 2000, "rmse": 214.5699}
    env = cc.compact(payload, server="mil-model", tool="x", limit=100)
    assert env["digest"]["note"]["_long_str"] == 8000
    assert env["digest"]["note"]["head"] == payload["note"][:300]
    assert cc.expand(env["__raw_path"], "note", server="mil-model",
                     max_chars=9_999_999)["value"] == payload["note"]


def test_compaction_is_skipped_when_the_envelope_costs_more(raw_dir):
    """压了反而更长就不压：信封自身有 400–500 字符固定开销。

    实测 reproduce_fold 的 14 条逐 bag 明细超出阈值一点点，压缩后 3,128→3,219 字符
    （-2.9%），等于白付一次 expand 往返的风险。这类结果必须原样透出、不落盘。
    """
    payload = {"note": "热值预测" * 200, "rmse": 214.5699}
    assert cc.compact(payload, server="mil-model", tool="fold", limit=100) == payload
    assert not os.path.exists(raw_dir), "放弃压缩时不该留下水坑目录"


def test_tally_lets_verdict_be_read_without_a_round_trip(raw_dir):
    # 与 verify_papers.PaperResult 的真实形状一致（含 identifiers 子对象）
    papers = [
        {
            "id": f"p{i}",
            "status": "verified" if i % 10 else "unverified",
            "method": "arxiv" if i % 10 else None,
            "confidence": "high" if i % 10 else None,
            "reason": "arXiv 批量命中" if i % 10 else "所有层均未命中，疑似编造引用",
            "identifiers": {"arxiv_id": f"1802.0{i:04d}", "doi": f"10.1109/TGRS.2024.{i:03d}",
                            "title": f"Multi-instance learning for LIBS calorific prediction {i}"},
        }
        for i in range(20)
    ]
    payload = {"verdict": "WARN", "hallucination_rate": 0.05, "pending_rate": 0.0,
               "warnings": ["p0 unverified"], "papers": papers}
    env = cc.compact(payload, server="sci-verify", tool="verify_papers")
    assert "__compacted" in env, "20 条带 identifiers 的核验结果应触发压缩"
    for k in ("verdict", "hallucination_rate", "pending_rate"):
        assert env["digest"][k] == payload[k], "判读闸门所需的顶层数值必须逐字保留"
    tally = env["digest"]["papers"]["tally"]["status"]
    assert tally == {"verified": 18, "unverified": 2}
    # 少数类的具体是哪几条，仍可一次取回（不靠猜）
    bad = cc.expand(env["__raw_path"], 'papers[*].id', server="sci-verify")
    assert bad["status"] == "ok" and len(bad["value"]) == 20
    one = cc.expand(env["__raw_path"], "papers[0]", server="sci-verify")
    assert one["value"] == papers[0]


def test_huge_single_string_is_not_looped_through_recompaction(raw_dir):
    b64 = "data:image/png;base64," + "A" * 120_000
    payload = {"path": "F:/x/page_001.png", "size_bytes": 120_023, "data_uri": b64}
    env = cc.compact(payload, server="sci-data", tool="image_to_data_uri")
    assert env["digest"]["path"] == payload["path"]        # 可直接用的路径逐字保留
    assert env["digest"]["size_bytes"] == payload["size_bytes"]
    got = cc.expand(env["__raw_path"], "data_uri", server="sci-data")
    assert got["status"] == "too_large"
    assert got["chars"] == len(b64)
    assert "抄不回" in got["howto"]


def test_identical_call_reuses_one_raw_file(raw_dir):
    for _ in range(3):
        cc.compact(_bags(), server="mil-model", tool="list_val_bags")
    day = os.listdir(raw_dir)
    assert len(day) == 1
    assert len(os.listdir(os.path.join(raw_dir, day[0]))) == 1


def test_drifted_repeat_call_never_points_at_stale_original(raw_dir):
    """同参重跑但内容漂移（verify_papers 实测会漂）时，信封必须指向自己那一份原文。

    曾经的缺陷：文件名按 (tool, args) 哈希 → 第二次调用命中 exists 跳过写入，
    digest 说 unverified=3、__raw_path 里却是上一轮的 unverified=2，溯源失效。
    """
    first = _bags()
    second = _bags()
    second["val_bags"][0]["y_true_kcal_kg"] = 9999.0
    second["mean_rmse_kcal_kg"] = 299.9999

    e1 = cc.compact(first, server="mil-model", tool="list_val_bags")
    e2 = cc.compact(second, server="mil-model", tool="list_val_bags")
    assert e1["__raw_path"] != e2["__raw_path"], "内容变了就必须换新文件"

    for env, payload in ((e1, first), (e2, second)):
        back = cc.expand(env["__raw_path"], "", server="mil-model")["value"]
        assert _lines(back) == _lines(payload)
        assert env["digest"]["mean_rmse_kcal_kg"] == payload["mean_rmse_kcal_kg"]

    day = os.listdir(raw_dir)[0]
    assert len(os.listdir(os.path.join(raw_dir, day))) == 2
