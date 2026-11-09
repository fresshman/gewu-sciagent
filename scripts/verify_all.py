"""一键全量门禁：把「本项目能不能用」压成一条命令、一个退出码。

设计约束（都是踩过的坑，不是理论洁癖）：
1. **不引入新依赖**：只用标准库 + 仓库已有的 pytest / node，评委机器不需要额外装东西。
2. **区分「失败」与「不适用」**：真实课题存档、外部未发表项目、TeX 引擎、Node 都是
   可选外部条件。缺了就标 SKIP 并写明缺什么，绝不当成 PASS（这是本仓库既有约定，
   `scripts/e2e_smoke_test.py` 的 exit=2 就是同一套口径）。
3. **通过与否不靠解析日志猜**：子进程退出码是唯一判据，日志只在失败时回显尾部。

用法::

    python scripts/verify_all.py            # 全量（含最小课题端到端，约 1–3 分钟）
    python scripts/verify_all.py --fast     # 只跑两套单测（跳过端到端，秒级）
    python scripts/verify_all.py --json     # 机器可读结果

退出码：0 = 没有硬失败（允许有 SKIP）；1 = 至少一项硬失败。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Sequence

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


@dataclass
class Step:
    """一个门禁项。

    hard=True 表示失败即整体失败；False 表示「环境不具备」时计为 SKIP 而非 FAIL。
    """

    name: str
    argv: list[str]
    cwd: str = REPO
    hard: bool = True
    skip_reason: str | None = None
    # 子进程退出码 → 语义；未列出的非零码一律视为失败
    exit_notes: dict[int, str] = field(default_factory=dict)
    note: str = ""


@dataclass
class Result:
    name: str
    status: str
    code: int | None
    detail: str = ""
    tail: str = ""


def _run(argv: Sequence[str], cwd: str, timeout: int) -> tuple[int, str]:
    proc = subprocess.run(
        list(argv),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    out = proc.stdout.decode("utf-8", errors="replace")
    return proc.returncode, out


def _tail(text: str, lines: int = 25) -> str:
    rows = [r for r in text.strip().splitlines() if r.strip()]
    return "\n".join(rows[-lines:])


def run_step(step: Step, runner: Callable[[Sequence[str], str], tuple[int, str]], timeout: int = 1800) -> Result:
    """执行一项。runner 可注入，便于测试时替换成假实现。"""
    if step.skip_reason:
        return Result(step.name, SKIP, None, step.skip_reason)

    try:
        code, out = runner(step.argv, step.cwd)
    except FileNotFoundError as exc:
        return Result(step.name, SKIP, None, f"可执行文件不存在：{exc}")
    except subprocess.TimeoutExpired:
        return Result(step.name, FAIL, None, f"超时（>{timeout}s）")

    if code == 0:
        return Result(step.name, PASS, 0, step.note, _tail(out, 5))

    # 显式登记过的非零码 = 不适用，不算失败
    note = step.exit_notes.get(code)
    if note is not None:
        return Result(step.name, SKIP, code, f"exit={code} {note}", _tail(out, 5))

    return Result(step.name, FAIL, code, f"exit={code}", _tail(out))


def build_steps(fast: bool = False, python: str | None = None) -> list[Step]:
    py = python or sys.executable
    steps: list[Step] = [
        Step(
            name="pytest（Python 侧全量）",
            argv=[py, "-m", "pytest", "tests", "-q"],
            note="硬指标：0 failed；skipped 随 4 个外部条件浮动",
        ),
    ]

    node = shutil.which("node")
    if node:
        steps.append(
            Step(
                name="node --test（Web 代理侧）",
                argv=[node, "--test", "tests/**/*.test.mjs"],
                cwd=os.path.join(REPO, "web"),
                note="预算状态机 / 会话名归一 / tail 划界 等",
            )
        )
    else:
        steps.append(
            Step(
                name="node --test（Web 代理侧）",
                argv=["node", "--test"],
                skip_reason="当前环境没有 node（需 ≥22.5），Web 代理侧单测未执行",
            )
        )

    if not fast:
        steps.append(
            Step(
                name="最小课题端到端（十层校验）",
                argv=[py, "scripts/run_min_case.py", "--offline"],
                note="零外部数据依赖的完整链路；本机无 TeX 引擎时编译层按设计不失败",
            )
        )
        steps.append(
            Step(
                name="真实课题 e2e 冒烟（九层）",
                argv=[py, "scripts/e2e_smoke_test.py", "--quiet"],
                exit_notes={2: "不适用：本机无未入库存档 output/documents（按设计不入库）"},
                note="有存档时校验数值/溯源/PDF 与论文自洽",
            )
        )
    return steps


def _width(text: str) -> int:
    """终端显示宽度：CJK 与全角标点占两列，用 len() 对齐会错位。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def summarize(results: list[Result]) -> int:
    pad = max(_width(r.name) for r in results)
    for r in results:
        spaces = " " * (pad - _width(r.name))
        line = f"  {r.status:<4}  {r.name}{spaces}  {r.detail}"
        print(line.rstrip())
        if r.status == FAIL and r.tail:
            for row in r.tail.splitlines():
                print(f"          | {row}")
    hard_fail = [r for r in results if r.status == FAIL]
    print()
    n_pass = sum(1 for r in results if r.status == PASS)
    n_skip = sum(1 for r in results if r.status == SKIP)
    print(f"合计 {len(results)} 项：通过 {n_pass} / 跳过 {n_skip} / 失败 {len(hard_fail)}")
    if hard_fail:
        print("门禁未通过：" + "、".join(r.name for r in hard_fail), file=sys.stderr)
        return 1
    print("门禁通过（跳过的项均已写明缺少哪个外部条件，不是失败）")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="一键全量门禁")
    ap.add_argument("--fast", action="store_true", help="只跑两套单测，跳过端到端")
    ap.add_argument("--json", action="store_true", help="输出机器可读结果")
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args(argv)

    steps = build_steps(fast=args.fast)
    results = [run_step(s, lambda a, c: _run(a, c, args.timeout), args.timeout) for s in steps]

    if args.json:
        print(
            json.dumps(
                {
                    "steps": [
                        {"name": r.name, "status": r.status, "code": r.code, "detail": r.detail}
                        for r in results
                    ],
                    "ok": not any(r.status == FAIL for r in results),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if not any(r.status == FAIL for r in results) else 1

    print("格物 · 全量门禁")
    print(f"仓库：{REPO}")
    print()
    return summarize(results)


if __name__ == "__main__":
    sys.exit(main())
