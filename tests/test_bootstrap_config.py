"""网关配置生成脚本的关键逻辑回归测试。

覆盖两处最容易悄悄坏、又直接决定「评委能不能跑起来」的判断：
  1. `_node_gate_ok`：openclaw 的 Node 版本闸门（≥24.16 且 <25，或 ≥26.1），
     判错会让生成的配置指向一个网关拒绝启动的 node。
  2. `inject_coal_env`：把 GEWU_COAL_PYTHON / COAL_PROJECT_ROOT 注入 mil-model 的
     env 段。openclaw 给 stdio 子进程的是 15 键白名单，不注入时真实推理会退到
     无 torch 的解释器；注入写坏则整个 mil-model 起不来。

不依赖网络、不依赖本机 venv，纯文本层面的断言。
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
import bootstrap_openclaw_config as B  # noqa: E402


def test_node_gate():
    assert B._node_gate_ok("v26.9.0") is True
    assert B._node_gate_ok("v26.1.0") is True
    assert B._node_gate_ok("v27.0.0") is True
    assert B._node_gate_ok("v24.16.0") is True
    assert B._node_gate_ok("v24.15.9") is False   # 差一点点也不放行
    assert B._node_gate_ok("v22.22.2") is False   # WorkBuddy 自带版本，实测会被网关拒
    assert B._node_gate_ok("v25.0.0") is False    # 24 与 26 之间的空档同样不行
    assert B._node_gate_ok("") is False
    assert B._node_gate_ok("not-a-version") is False


SNIPPET = """{
  mcp: {
    servers: {
      "mil-model": {
        command: "py",
        args: ["mil_model.py"],
      },
      "sci-plot": {
        command: "py",
        args: ["sci_plot.py"],
      },
    },
  },
}
"""


def test_inject_coal_env_creates_env_block():
    out, note = B.inject_coal_env(
        SNIPPET,
        "C:/envs/coal-torch/Scripts/python.exe",
        "F:/external/coal-project",
    )
    # mil-model 段里出现了两条 env
    assert 'GEWU_COAL_PYTHON: "C:/envs/coal-torch/Scripts/python.exe"' in out
    assert 'COAL_PROJECT_ROOT: "F:/external/coal-project"' in out
    assert "新增" in note and "mil-model.env" in note
    # sci-plot 段不该被污染
    plot_seg = out.split('"sci-plot"', 1)[1]
    assert "GEWU_COAL_PYTHON" not in plot_seg
    # 花括号仍配平（注入不能破坏 JSONC 结构）
    assert out.count("{") == out.count("}")


def test_inject_coal_env_updates_existing_env():
    with_env = SNIPPET.replace(
        '      "mil-model": {\n        command: "py",',
        '      "mil-model": {\n        env: { OLD_KEY: "1" },\n        command: "py",',
    )
    out, note = B.inject_coal_env(with_env, "C:/py.exe", "")
    assert "更新" in note
    assert "OLD_KEY" not in out                      # 旧 env 被替换而非叠加
    assert 'GEWU_COAL_PYTHON: "C:/py.exe"' in out
    assert "COAL_PROJECT_ROOT" not in out            # 只给 python 时不凭空加 root
    assert out.count("{") == out.count("}")


def test_inject_coal_env_noop_when_nothing_detected():
    out, note = B.inject_coal_env(SNIPPET, "", "")
    assert out == SNIPPET
    assert note == ""


def test_posix_and_escape():
    # 反斜杠在 JSONC 字符串里是非法转义，注入前必须转正斜杠
    assert B.as_posix(r"C:\Users\x\py.exe") == "C:/Users/x/py.exe"
    assert B.json_escape('a"b') == 'a\\"b'
