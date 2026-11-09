"""`scripts/verify_all.py` 的门禁语义测试。

重点不是「命令能跑」，而是三条判定规则不能被改坏：
1. 退出码 0 = PASS；
2. **登记过的非零码（如 e2e 的 exit=2）是 SKIP，不是 FAIL** —— 这是本仓库
   「缺外部条件就说清缺什么」的约定，写成 FAIL 会让干净 clone 永远红；
3. 未登记的非零码才是 FAIL，且必须回显日志尾部，否则失败不可诊断。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import verify_all as V  # noqa: E402


def _runner(code: int, out: str = ""):
    def run(argv, cwd):  # noqa: ARG001
        return code, out

    return run


def test_pass_on_zero():
    step = V.Step(name="t", argv=["x"])
    r = V.run_step(step, _runner(0, "ok"))
    assert r.status == V.PASS and r.code == 0


def test_registered_nonzero_is_skip_not_fail():
    """e2e 无存档返回 2，必须记为 SKIP —— 否则干净 clone 的门禁永远是红的。"""
    step = V.Step(name="e2e", argv=["x"], exit_notes={2: "不适用：无存档"})
    r = V.run_step(step, _runner(2, "no archive"))
    assert r.status == V.SKIP
    assert "不适用" in r.detail


def test_unregistered_nonzero_is_fail_and_keeps_tail():
    step = V.Step(name="t", argv=["x"])
    r = V.run_step(step, _runner(1, "line1\nAssertionError: boom\nline3"))
    assert r.status == V.FAIL
    assert "AssertionError: boom" in r.tail


def test_missing_executable_is_skip_not_fail():
    """评委机器没装 node 时不能判失败，只能是 SKIP。"""
    def boom(argv, cwd):  # noqa: ARG001
        raise FileNotFoundError("node")

    r = V.run_step(V.Step(name="node", argv=["node"]), boom)
    assert r.status == V.SKIP
    assert "node" in r.detail


def test_timeout_is_fail():
    import subprocess

    def slow(argv, cwd):  # noqa: ARG001
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)

    r = V.run_step(V.Step(name="t", argv=["x"]), slow)
    assert r.status == V.FAIL and "超时" in r.detail


def test_skip_reason_short_circuits_without_running():
    called = []

    def spy(argv, cwd):  # noqa: ARG001
        called.append(argv)
        return 0, ""

    r = V.run_step(V.Step(name="t", argv=["x"], skip_reason="没装 node"), spy)
    assert r.status == V.SKIP
    assert called == [], "标了 skip_reason 就不该真的执行命令"


def test_build_steps_fast_drops_e2e():
    names = [s.name for s in V.build_steps(fast=True)]
    assert not any("端到端" in n for n in names)
    full = [s.name for s in V.build_steps(fast=False)]
    assert any("最小课题" in n for n in full)
    assert any("e2e" in n for n in full)


def test_summarize_exit_code_reflects_hard_fail(capsys):
    ok = [V.Result("a", V.PASS, 0), V.Result("b", V.SKIP, 2, "不适用")]
    assert V.summarize(ok) == 0
    out = capsys.readouterr().out
    assert "通过 1 / 跳过 1 / 失败 0" in out

    bad = [V.Result("a", V.PASS, 0), V.Result("c", V.FAIL, 1, tail="boom")]
    assert V.summarize(bad) == 1
    assert "boom" in capsys.readouterr().out


def test_main_json_contract(capsys, monkeypatch):
    """JSON 契约：不真的跑子进程，替换成假步骤，避免 pytest 内部再启动整套门禁。"""
    monkeypatch.setattr(V, "build_steps", lambda fast=False, python=None: [V.Step(name="假步骤", argv=["x"])])
    monkeypatch.setattr(V, "run_step", lambda step, runner, timeout=1800: V.Result(step.name, V.PASS, 0, "ok"))

    code = V.main(["--fast", "--json"])
    payload = capsys.readouterr().out
    import json

    data = json.loads(payload)
    assert code == 0
    assert data["ok"] is True
    assert data["steps"] == [{"name": "假步骤", "status": "PASS", "code": 0, "detail": "ok"}]


@pytest.mark.parametrize("flag", [[], ["--fast"]])
def test_cli_help_is_available(flag):
    """--help 不应触发任何子进程。"""
    with pytest.raises(SystemExit) as exc:
        V.main([*flag, "--help"])
    assert exc.value.code == 0
