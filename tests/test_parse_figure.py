"""sci_data.parse_figure 的回归测试（全离线，不联网、不需要 Key）。

为什么值得单独守：这个工具在 2026-11-04 之前是**占位实现**——不管喂什么图都回
`modality:"unknown"` + 一句 note。在一个卖点写着反幻觉的项目里，一个永远"成功返回"
的假结构比报错更糟：调用方拿到的是一个看起来像读数的东西。所以这里最硬的一条断言是
**任何降级路径都不得返回 figure/modality 字段**，失败必须长得像失败。

真实模型调用不进单测（要联网、要 Key、输出不完全稳定），本机实测记录见
docs/verification/2026-11-04-parse-figure-vision.md；这里注入假传输层覆盖契约与分支。
"""
import json
import os
import re
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "gewu", "mcp"))
import sci_data as sd  # noqa: E402

TEMPLATE = os.path.join(REPO_ROOT, "openclaw", "openclaw.json")
FAKE_KEY = "sk-FAKE-key-never-should-leak-0123456789"

_CANNED_FIGURE = {
    "modality": "spectrum",
    "title": "Synthetic LIBS spectrum",
    "x_axis": {"label": "Wavelength", "unit": "nm", "min": 200, "max": 800},
    "y_axis": {"label": "Intensity", "unit": "a.u.", "min": 0.0, "max": 1.0},
    "series": [],
    "peaks": [{"position": 450.0, "unit": "nm", "intensity": 0.33, "label_in_figure": "估读"}],
    "key_numbers": [],
    "text_in_figure": ["Synthetic LIBS spectrum"],
    "unreadable": "",
    "confidence": "high",
}


def _chat_response(content, usage=None):
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": usage or {"prompt_tokens": 1233, "completion_tokens": 1043, "total_tokens": 2276},
    }


@pytest.fixture()
def figure_png(tmp_path):
    """一张 1x1 的合法 PNG，够走完整管线又不至于让 base64 撑爆断言。"""
    import base64

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    p = tmp_path / "fig.png"
    p.write_bytes(png)
    return str(p)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """每个用例都从干净环境出发：无 Key、瘦身层关闭、原文不落 `~/.gewu`。"""
    monkeypatch.delenv("INTERN_API_KEY", raising=False)
    monkeypatch.delenv("GEWU_VL_MODEL", raising=False)
    monkeypatch.delenv("GEWU_VL_BASE_URL", raising=False)
    monkeypatch.delenv("GEWU_VL_TIMEOUT_S", raising=False)
    monkeypatch.delenv("GEWU_VL_MAX_B64", raising=False)
    monkeypatch.setenv("GEWU_MCP_COMPACT", "0")
    monkeypatch.setenv("GEWU_MCP_RAW_DIR", str(tmp_path / "mcp-raw"))


def _no_transport(monkeypatch):
    """任何一次真实网络调用都算测试失败。"""

    def _boom(body, timeout):
        raise AssertionError("不该发起网络调用")

    monkeypatch.setattr(sd, "_vl_complete", _boom)


def _with_transport(monkeypatch, resp=None, kind="", msg=""):
    seen = {}

    def _fake(body, timeout):
        seen["body"] = body
        seen["timeout"] = timeout
        return resp, kind, msg

    monkeypatch.setattr(sd, "_vl_complete", _fake)
    return seen


# ── 降级路径：失败必须像失败 ─────────────────────────────────────────────────
def test_missing_file_is_file_not_found(figure_png):
    out = sd.parse_figure(os.path.join(os.path.dirname(figure_png), "nope.png"))
    assert out["status"] == "file_not_found"
    assert "figure" not in out and "modality" not in out


def test_missing_key_never_calls_network_and_never_fakes_a_read(figure_png, monkeypatch):
    _no_transport(monkeypatch)
    out = sd.parse_figure(figure_png)
    assert out["status"] == "missing_key"
    # 这一条是本文件存在的理由：占位实现当年就是在这里返回了 modality:"unknown"
    assert "figure" not in out
    assert "modality" not in out
    # 修法必须指向配置里的 env 注入，而不是"在 shell 里 export"——后者实测对 MCP 子进程无效
    assert "bootstrap_openclaw_config.py" in out["hint"]
    assert "mcp.servers.sci-data.env" in out["hint"]


def test_unresolved_placeholder_counts_as_missing_key(figure_png, monkeypatch):
    """配置里留了未解析的 ${INTERN_API_KEY}：不能当 Key 发出去换一次 401。"""
    _no_transport(monkeypatch)
    monkeypatch.setenv("INTERN_API_KEY", "${INTERN_API_KEY}")
    out = sd.parse_figure(figure_png)
    assert out["status"] == "missing_key"
    assert "${" in out["error"]
    assert "figure" not in out


def test_oversized_image_is_refused_before_transport(figure_png, monkeypatch):
    _no_transport(monkeypatch)
    monkeypatch.setenv("GEWU_VL_MAX_B64", "10")
    out = sd.parse_figure(figure_png)
    assert out["status"] == "too_large"
    assert out["image_base64_chars"] > 10
    assert "figure" not in out


def test_explicit_max_b64_overrides_env_gate_and_proceeds(figure_png, monkeypatch):
    monkeypatch.setenv("GEWU_VL_MAX_B64", "10")
    monkeypatch.setenv("INTERN_API_KEY", FAKE_KEY)
    seen = _with_transport(monkeypatch, _chat_response(json.dumps(_CANNED_FIGURE)))
    out = sd.parse_figure(figure_png, max_b64=100_000)
    assert out["status"] == "ok"
    assert seen["body"], "显式放大 max_b64 后应当真的发起调用"


# ── 成功路径：契约透传 ───────────────────────────────────────────────────────
def test_ok_returns_figure_model_latency_and_usage(figure_png, monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", FAKE_KEY)
    _with_transport(monkeypatch, _chat_response(json.dumps(_CANNED_FIGURE)))
    out = sd.parse_figure(figure_png)
    assert out["status"] == "ok"
    assert out["modality"] == "spectrum"
    assert out["figure"]["peaks"][0]["position"] == 450.0
    assert out["usage"]["total_tokens"] == 2276
    assert out["latency_s"] >= 0
    # 二次对照纪律必须随结果一起浮出来，而不是只写在文档里
    assert "二次对照" in out["warning"]


def test_markdown_fenced_json_is_stripped(figure_png, monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", FAKE_KEY)
    fenced = "```json\n" + json.dumps(_CANNED_FIGURE) + "\n```"
    _with_transport(monkeypatch, _chat_response(fenced))
    assert sd.parse_figure(figure_png)["status"] == "ok"


def test_prose_wrapped_json_is_recovered_by_outer_braces(figure_png, monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", FAKE_KEY)
    content = "好的，以下是解析结果：\n" + json.dumps(_CANNED_FIGURE) + "\n以上。"
    _with_transport(monkeypatch, _chat_response(content))
    assert sd.parse_figure(figure_png)["status"] == "ok"


def test_unparsable_reply_returns_status_not_partial_structure(figure_png, monkeypatch):
    """模型跑偏时宁可只回原文头部，也不"尽量救一下"——半截结构会被下游当成读数。"""
    monkeypatch.setenv("INTERN_API_KEY", FAKE_KEY)
    _with_transport(monkeypatch, _chat_response("抱歉，我无法解析这张图。"))
    out = sd.parse_figure(figure_png)
    assert out["status"] == "unparsable"
    assert "figure" not in out and "modality" not in out
    assert "无法解析" in out["reply_head"]


def test_empty_choices_is_empty_response(figure_png, monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", FAKE_KEY)
    _with_transport(monkeypatch, {"choices": []})
    out = sd.parse_figure(figure_png)
    assert out["status"] == "empty_response"
    assert "figure" not in out


@pytest.mark.parametrize(
    "kind,msg,expected",
    [
        ("http_error", 'HTTP 401 {"error":{"message":"invalid api key"}}', "http_error"),
        ("timeout", "请求超时（180s 内未返回）：timed out", "timeout"),
        ("network", "网络失败：[Errno 11001] getaddrinfo failed", "network"),
        ("bad_json", "响应不是合法 JSON：<html>", "bad_json"),
    ],
)
def test_transport_errors_map_to_honest_status(figure_png, monkeypatch, kind, msg, expected):
    monkeypatch.setenv("INTERN_API_KEY", FAKE_KEY)
    _with_transport(monkeypatch, None, kind, msg)
    out = sd.parse_figure(figure_png)
    assert out["status"] == expected
    assert msg in out["error"]
    assert out["hint"]
    assert "figure" not in out


def test_real_transport_timeout_is_classified_timeout(figure_png, monkeypatch):
    """真传输层：urlopen 抛 URLError(timeout) 必须归到 timeout，而不是被字符串嗅探漏判。"""
    import urllib.error

    monkeypatch.setenv("INTERN_API_KEY", FAKE_KEY)

    def _raise(*a, **kw):
        raise urllib.error.URLError(TimeoutError("The read operation timed out"))

    monkeypatch.setattr(sd.urllib.request, "urlopen", _raise)
    resp, kind, msg = sd._vl_complete({"model": "x"}, 1)
    assert resp is None and kind == "timeout" and "timed out" in msg


# ── 请求体与配置 ─────────────────────────────────────────────────────────────
def test_request_body_is_openai_compatible_with_inline_image(figure_png, monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", FAKE_KEY)
    seen = _with_transport(monkeypatch, _chat_response(json.dumps(_CANNED_FIGURE)))
    sd.parse_figure(figure_png, question="只读 400-500nm 的峰")
    body = seen["body"]
    assert body["model"] == sd.VL_DEFAULT_MODEL
    assert body["temperature"] == 0
    user = body["messages"][1]["content"]
    assert user[0]["type"] == "text" and user[1]["type"] == "image_url"
    assert user[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "只读 400-500nm 的峰" in user[0]["text"]
    # 反幻觉指令必须在 system 里，而不是靠调用方自觉
    system = body["messages"][0]["content"]
    assert "禁止用领域常识" in system and "null" in system


def test_model_and_timeout_come_from_env_at_call_time(figure_png, monkeypatch):
    """MCP 进程会被复用，import 时读死就等于改了配置不生效。"""
    monkeypatch.setenv("INTERN_API_KEY", FAKE_KEY)
    monkeypatch.setenv("GEWU_VL_MODEL", "internvl3.5-38b")
    monkeypatch.setenv("GEWU_VL_TIMEOUT_S", "77")
    seen = _with_transport(monkeypatch, _chat_response(json.dumps(_CANNED_FIGURE)))
    out = sd.parse_figure(figure_png)
    assert seen["body"]["model"] == "internvl3.5-38b"
    assert seen["timeout"] == 77
    assert out["model"] == "internvl3.5-38b"


def test_timeout_is_clamped_below_the_mcp_client_gate():
    """内层 HTTP 超时上限必须留在 sci-data 的 requestTimeoutMs 之下（同 mil_model 的教训）。"""
    src = open(TEMPLATE, encoding="utf-8-sig").read()
    block = re.search(r'"sci-data"\s*:\s*\{(?P<body>[^}]*?)\n      \}', src, re.S)
    assert block, "模板里找不到 mcp.servers.sci-data"
    gate_ms = int(re.search(r"requestTimeoutMs\s*:\s*(\d+)", block.group("body")).group(1))
    assert sd.VL_TIMEOUT_CEILING_S * 1000 < gate_ms, (
        f"VL 超时上限 {sd.VL_TIMEOUT_CEILING_S}s 会撞上客户端闸门 {gate_ms / 1000}s："
        "模型拿到的是 -32001 而不是我们的降级建议"
    )
    assert sd.VL_DEFAULT_TIMEOUT_S < sd.VL_TIMEOUT_CEILING_S


def test_bad_env_int_falls_back_to_default(figure_png, monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", FAKE_KEY)
    monkeypatch.setenv("GEWU_VL_TIMEOUT_S", "not-a-number")
    seen = _with_transport(monkeypatch, _chat_response(json.dumps(_CANNED_FIGURE)))
    sd.parse_figure(figure_png)
    assert seen["timeout"] == sd.VL_DEFAULT_TIMEOUT_S


# ── 密钥不外泄 ───────────────────────────────────────────────────────────────
def test_api_key_never_appears_in_any_returned_field(figure_png, monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", FAKE_KEY)
    seen = _with_transport(monkeypatch, _chat_response(json.dumps(_CANNED_FIGURE)))
    assert FAKE_KEY not in json.dumps(sd.parse_figure(figure_png), ensure_ascii=False)
    # Key 只进 Authorization 头，不进请求体——否则一次工具调用的 body 就把它写进了轨迹表
    assert FAKE_KEY not in json.dumps(seen["body"], ensure_ascii=False)
    assert FAKE_KEY not in json.dumps(seen, ensure_ascii=False)

    _with_transport(monkeypatch, None, "http_error", 'HTTP 401 {"error":{"message":"invalid api key"}}')
    out = sd.parse_figure(figure_png)
    assert out["status"] == "http_error"
    assert FAKE_KEY not in json.dumps(out, ensure_ascii=False)


def test_extract_json_rejects_half_structures():
    assert sd._vl_extract_json('{"a": 1}')[0] == {"a": 1}
    obj, err = sd._vl_extract_json('{"a": ')
    assert obj is None and err
    obj, err = sd._vl_extract_json("纯文字没有花括号")
    assert obj is None and "JSON" in err
