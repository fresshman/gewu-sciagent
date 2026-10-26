"""journal_rank 单元测试（mock 网络，不触碰真实 key / 不联网）。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gewu" / "mcp"))
import journal_rank as jr


class _FakeResp:
    def __init__(self, payload: dict):
        self._b = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._b


def _fake_urlopen(payload):
    def _cb(req, timeout=None):
        return _FakeResp(payload)

    return _cb


def test_query_success_with_custom_and_official(monkeypatch):
    payload = {
        "code": 200,
        "msg": "SUCCESS",
        "data": {
            "officialRank": {
                "all": {"sci": "Q1", "ssci": "Q1", "swufe": "A"},
                "select": {"swufe": "A"},
            },
            "customRank": {
                "rankInfo": [
                    {
                        "uuid": "1614986460329492480",
                        "abbName": "DUFE",
                        "oneRankText": "TOP",
                        "twoRankText": "A",
                        "threeRankText": "B",
                        "fourRankText": "C",
                        "fiveRankText": "D",
                    }
                ],
                "rank": ["1614986460329492480&&&3"],
            },
        },
    }
    monkeypatch.setattr(jr.urllib.request, "urlopen", _fake_urlopen(payload))
    monkeypatch.setattr(jr, "_resolve_secret_key", lambda explicit=None: "fake-key")

    r = jr.query_publication_rank("Talanta")
    assert r["ok"] is True
    assert r["data"]["official_all"] == {"sci": "Q1", "ssci": "Q1", "swufe": "A"}
    # 自定义数据集解析：uuid → abbName=DUFE，rank=3 → threeRankText=B
    assert r["data"]["custom"] == [
        {"dataset": "DUFE", "rank": "B", "raw_rank": "3"}
    ]
    assert "DUFE=B" in r["summary"]
    assert "sci=Q1" in r["summary"]


def test_query_wrong_key(monkeypatch):
    payload = {"code": 40002, "msg": "Key错误", "data": None}
    monkeypatch.setattr(jr.urllib.request, "urlopen", _fake_urlopen(payload))
    monkeypatch.setattr(jr, "_resolve_secret_key", lambda explicit=None: "bad")

    r = jr.query_publication_rank("Talanta")
    assert r["ok"] is False
    assert r["code"] == 40002
    assert "Key错误" in r["error"]


def test_query_empty_name(monkeypatch):
    monkeypatch.setattr(jr, "_resolve_secret_key", lambda explicit=None: "fake")
    r = jr.query_publication_rank("   ")
    assert r["ok"] is False
    assert "为空" in r["error"]


def test_query_no_secret(monkeypatch):
    # 强制秘钥解析为空，模拟未配置凭据
    monkeypatch.setattr(jr, "_resolve_secret_key", lambda explicit=None: None)
    r = jr.query_publication_rank("Talanta")
    assert r["ok"] is False
    assert "秘钥" in r["error"]


def test_bad_rank_entry_skipped(monkeypatch):
    payload = {
        "code": 200,
        "msg": "SUCCESS",
        "data": {
            "officialRank": {"all": {}},
            "customRank": {
                "rankInfo": [
                    {"uuid": "u1", "abbName": "X", "oneRankText": "A"}
                ],
                "rank": ["garbage-no-amp", "u1&&&1"],
            },
        },
    }
    monkeypatch.setattr(jr.urllib.request, "urlopen", _fake_urlopen(payload))
    monkeypatch.setattr(jr, "_resolve_secret_key", lambda explicit=None: "fake")

    r = jr.query_publication_rank("J")
    assert r["ok"] is True
    assert r["data"]["custom"] == [{"dataset": "X", "rank": "A", "raw_rank": "1"}]


def test_verify_server_tool_wrapper(monkeypatch):
    # 验证 sci-verify 暴露的 get_journal_rank 调用链正确
    import verify_server as vs

    monkeypatch.setattr(
        jr, "query_publication_rank",
        lambda name: {"ok": True, "data": {"official_all": {"sci": "Q1"}},
                      "summary": "官方: sci=Q1"}
    )
    out = vs.get_journal_rank("Talanta")
    d = json.loads(out)
    assert d["ok"] is True
    assert d["data"]["official_all"]["sci"] == "Q1"
