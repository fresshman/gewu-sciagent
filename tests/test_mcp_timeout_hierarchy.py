#!/usr/bin/env python3
"""守护测试：MCP 工具内的超时 gate 必须严格小于客户端 requestTimeoutMs。

为什么值得守：这条错配真实烧掉过一整次阶段（2026-10-28 会话 coal-demo-v3，2404s 撞墙超时）。
`reproduce_fold` 内部允许跑 1800s，而 OpenClaw MCP 客户端 900s 就先掐，于是模型拿到的是
`MCP error -32001: Request timed out` 而不是我们那句「改用逐 bag / 分批」的可执行建议——
优雅降级路径被截胡，剩下的只有瞎摸索。

复现真超时需要真网关 + 真 torch，不适合进单测；会回归的恰恰是"有人把数字改大"或
"改了 openclaw.json 忘了改代码"，所以这里做的是**静态数值断言**：源码里的每个 gate 和
仓库模板里的每个 requestTimeoutMs 必须仍然自洽。
"""
import ast
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gewu", "mcp"))
import mil_model  # noqa: E402

TEMPLATE = os.path.join(ROOT, "openclaw", "openclaw.json")
TARGET = os.path.join(ROOT, "gewu", "mcp", "mil_model.py")
SERVER = "mil-model"


def _client_timeout_ms() -> int:
    """从仓库配置模板里取本 server 的 requestTimeoutMs（模板是带注释的 JSONC，只能扫）。"""
    src = open(TEMPLATE, encoding="utf-8-sig").read()
    block = re.search(rf'"{SERVER}"\s*:\s*\{{(?P<body>[^}}]*?)\n      \}}', src, re.S)
    assert block, f"模板里找不到 mcp.servers.{SERVER}"
    gate = re.search(r"requestTimeoutMs\s*:\s*(\d+)", block.group("body"))
    assert gate, f"{SERVER} 段里没有 requestTimeoutMs"
    return int(gate.group(1))


def _gates_in_source() -> dict[str, int]:
    """收集每个工具调用 _run 时写下的 timeout（数字或常量名都解析成秒）。"""
    tree = ast.parse(open(TARGET, encoding="utf-8").read())
    found = {}
    consts = {
        "MAX_TOOL_TIMEOUT_S": mil_model.MAX_TOOL_TIMEOUT_S,
        "CLIENT_REQUEST_TIMEOUT_S": mil_model.CLIENT_REQUEST_TIMEOUT_S,
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fname = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if fname != "_run":
            continue
        tool = None
        gate = None
        for kw in node.keywords:
            if kw.arg == "tool" and isinstance(kw.value, ast.Constant):
                tool = kw.value.value
            if kw.arg == "timeout":
                if isinstance(kw.value, ast.Constant):
                    gate = kw.value.value
                elif isinstance(kw.value, ast.Name):
                    gate = consts.get(kw.value.id)
                    assert gate is not None, f"{tool} 用了未登记的常量 {kw.value.id}"
        found[tool or f"_run@line{node.lineno}"] = gate if gate is not None \
            else mil_model.MAX_TOOL_TIMEOUT_S  # 省略 timeout 即走默认值
    return found


def test_client_gate_matches_module_constant():
    """代码里的 CLIENT_REQUEST_TIMEOUT_S 必须和配置模板一致，否则本测试失去意义。"""
    assert mil_model.CLIENT_REQUEST_TIMEOUT_S == _client_timeout_ms() / 1000


def test_every_tool_gate_fits_under_client_with_headroom():
    ceiling = _client_timeout_ms() / 1000 - mil_model.TIMEOUT_HEADROOM_S
    gates = _gates_in_source()
    assert gates, "没扫到任何 _run 调用，测试本身失效了"
    too_big = {t: g for t, g in gates.items() if g > ceiling}
    assert not too_big, (
        f"这些工具的 timeout={ceiling}s 上限被突破：{too_big}；"
        f"超过客户端 gate 只会收到 -32001，优雅降级永远浮不出来"
    )


def test_run_clamps_timeout():
    """夹取必须真实存在：调用方写更大的数字不能生效。"""
    src = open(TARGET, encoding="utf-8").read()
    assert re.search(r"timeout\s*=\s*min\(int\(timeout\),\s*MAX_TOOL_TIMEOUT_S\)", src), \
        "_run 里缺少对 timeout 的夹取"


def test_clamp_actually_applies(monkeypatch):
    """夹取真的生效：写一个远大于上限的 timeout，交给 subprocess 的必须是 840s。

    需要本机存在 coal_infer.py 且配置了煤项目根（否则 _run 会提前返回，压根不走 subprocess），
    那种环境下直接 skip，而不是让断言假失败。
    """
    if not os.path.exists(mil_model.COAL_INFER) or not mil_model._coal_root():
        pytest.skip("本机未配置煤热值项目，subprocess 分支不可达")
    import subprocess as sp

    seen = {}

    def fake_run(cmd, **kw):
        seen["timeout"] = kw["timeout"]
        raise sp.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(mil_model.subprocess, "run", fake_run)
    out = mil_model._run(["cv-summary"], timeout=10 ** 6, tool="clamp_probe")
    assert seen["timeout"] == mil_model.MAX_TOOL_TIMEOUT_S
    assert "推理超时" in out["detail"] and "-32001" not in out["detail"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
