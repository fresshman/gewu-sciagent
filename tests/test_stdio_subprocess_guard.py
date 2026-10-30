#!/usr/bin/env python3
"""守护测试：MCP 子进程调用必须切断继承的 stdin。

为什么不是行为测试而是源码断言：这个缺陷只在"服务被 MCP stdio 拉起"时出现——
子进程默认继承那根 JSON-RPC 管道，于是要么挂到自己的 timeout，要么抢走客户端
写入的请求字节。复现它需要真网关 + 真 torch 项目，不适合放进单测；而回归方式是
"再加一个 subprocess 调用忘了 stdin"，源码断言恰好覆盖这一条。

实测代价（2026-10-29）：`mil-model.get_cached_metrics` 直接跑 0.2s，经 MCP stdio
调用挂满 60s 判超时；历史上被误记为"reproduce_fold 推理太慢"的降级，根因在此。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = [
    "gewu/mcp/mil_model.py",
    "gewu/mcp/sci_exp.py",
    "gewu/mcp/verify_papers.py",
    "gewu/domain_packs/coal_libs/tools.py",
]
CALL = re.compile(r"subprocess\.(run|check_output|call|Popen)\(", re.S)
GUARD = re.compile(r"stdin\s*=\s*subprocess\.DEVNULL")


def _calls(path):
    src = open(os.path.join(ROOT, path), encoding="utf-8").read()
    for m in CALL.finditer(src):
        # 取该调用起始处之后、到匹配的右括号附近的片段（按深度扫描，避免多行参数漏判）
        depth, i = 1, m.end()
        while i < len(src) and depth:
            if src[i] == "(":
                depth += 1
            elif src[i] == ")":
                depth -= 1
            i += 1
        yield src[:m.start()].count("\n") + 1, src[m.start():i]


def test_every_subprocess_call_detaches_stdin():
    missing = []
    for path in TARGETS:
        for lineno, call_src in _calls(path):
            if not GUARD.search(call_src):
                missing.append("%s:%d" % (path, lineno))
    assert not missing, "这些 subprocess 调用会继承 MCP 的 stdin 管道: %s" % missing
