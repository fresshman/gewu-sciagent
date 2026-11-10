#!/usr/bin/env python3
"""7-mode 失败自检的**可执行门禁**（把 SKILL.md 里那句「必须阻断」变成退出码）。

为什么需要它
------------
`failure_mode_selfcheck/SKILL.md` 写得很硬：任一非 NOT APPLICABLE 项为 SUSPECTED 或
INSUFFICIENT EVIDENCE 就必须阻断，「绝不静默放行」。但在补上本脚本之前，这条规则
**没有任何执行体**：审计日志是可选的、schema 没人校验、写「结论 PASS」也没人比对。
实测（2026-11-10）仓库里从来没有一份 `failure_audit_log.json`，
`handoff_4_improver.json` 里那个 `failure_audit` 字段是 `{"verdict":"PASS_WITH_NOTES"}`
这种自由文本——名字在、内容不是 7 条四态裁决。也就是说：**规则存在，执行不存在。**

本脚本做四件事（每件都能让流程失败）：
1. schema 校验：必须 7 条、mode 1–7 各一条、state 在四态枚举内、evidence 非空。
2. 裁决重算：由 7 条 state 自己算出 gate，**不采信日志里写的 gate**。
   自报 PASS 而某条是 SUSPECTED → 直接失败（这是最容易发生的一种撒谎）。
3. 空话检测：CLEAR 但没有 evidence 的条目算失败——「CLEAR」若无法指出证据，
   与没做审计没有区别，而这正是 7-mode 想拦的 Mode 3/6。
4. 旧格式识别：把 `{"verdict": "PASS_WITH_NOTES"}` 这类自由文本明确报成
   「不是 7-mode 日志」，而不是当成 PASS 放过去。

退出码（与 verify_all / e2e 同一套口径）：
    0 = 通过（全部 CLEAR 或 NOT APPLICABLE）
    1 = 阻断（存在 SUSPECTED / INSUFFICIENT EVIDENCE，或 schema 不合格、自报与裁决矛盾）
    2 = 不适用（没找到任何审计日志；**这不是通过**）

用法::

    python scripts/failure_audit_gate.py                       # 自动搜仓库里的日志
    python scripts/failure_audit_gate.py --path a/b.json       # 指定日志
    python scripts/failure_audit_gate.py --json                # 机器可读
    python scripts/failure_audit_gate.py --self-test           # 用内置样例验证判据本身
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Any, Iterable

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STATES = ("CLEAR", "SUSPECTED", "INSUFFICIENT EVIDENCE", "NOT APPLICABLE")
BLOCKING = ("SUSPECTED", "INSUFFICIENT EVIDENCE")

# 失败模式清单（Lu et al. 2026 Nature 651:914-919，与 SKILL.md 表一致）
MODES = {
    1: "Implementation bug passes review",
    2: "Hallucinated citation",
    3: "Hallucinated experimental result",
    4: "Shortcut reliance",
    5: "Bug reframed as insight",
    6: "Methodology fabrication",
    7: "Frame-lock at early stage",
}

# 日志默认搜索位置（按优先级）
_SEARCH_PATTERNS = (
    "output/**/failure_audit_log.json",
    "openclaw/workspace/**/failure_audit_log.json",
    "docs/**/failure_audit_log.json",
)


class AuditFormatError(ValueError):
    """日志结构不合格（不是「审计没通过」，是「这份日志算不上一次审计」）。"""


def _looks_like_legacy(doc: Any) -> bool:
    """识别旧式自由文本结论（`{"verdict": "PASS_WITH_NOTES", "notes": [...]}`）。"""
    if not isinstance(doc, dict):
        return False
    if "verdicts" in doc or "gate" in doc:
        return False
    return any(k in doc for k in ("verdict", "notes", "conclusion", "summary"))


def validate(doc: Any) -> dict[str, Any]:
    """校验一份审计日志，返回结构化结论。结构不合格抛 AuditFormatError。

    Returns:
        {ok, gate, blocking, stage, n_verdicts, problems, caveats}
    """
    if _looks_like_legacy(doc):
        raise AuditFormatError(
            "这不是 7-mode 审计日志：只有自由文本结论（如 verdict/notes），"
            "没有逐条四态裁决。7-mode 的整个意义在于「每类失败都必须单独给裁决 + 证据」，"
            "一句总评无法满足这个 intent。请按 SKILL.md 的 schema 重写。"
        )
    if not isinstance(doc, dict):
        raise AuditFormatError(f"日志顶层应为对象，实际是 {type(doc).__name__}")

    verdicts = doc.get("verdicts")
    if not isinstance(verdicts, list):
        raise AuditFormatError("缺少 verdicts 数组")
    if len(verdicts) != 7:
        raise AuditFormatError(f"verdicts 必须正好 7 条，实际 {len(verdicts)} 条")

    problems: list[str] = []
    caveats: list[str] = []
    seen: dict[int, dict] = {}

    for i, v in enumerate(verdicts):
        if not isinstance(v, dict):
            problems.append(f"第 {i + 1} 条不是对象")
            continue
        mode = v.get("mode")
        if not isinstance(mode, int) or mode not in MODES:
            problems.append(f"第 {i + 1} 条 mode 非法：{mode!r}（应为 1–7 的整数）")
            continue
        if mode in seen:
            problems.append(f"mode {mode} 重复出现")
            continue
        seen[mode] = v

        state = v.get("state")
        if state not in STATES:
            problems.append(f"mode {mode} 的 state 非法：{state!r}（应为 {STATES}）")
            continue
        evidence = (v.get("evidence") or "")
        if not isinstance(evidence, str):
            problems.append(f"mode {mode} 的 evidence 不是字符串")
        elif not evidence.strip() and state in ("CLEAR", "NOT APPLICABLE"):
            # CLEAR 却指不出证据 = 没做审计。这是 Mode 3/6 的典型外观。
            problems.append(
                f"mode {mode} 判为 {state} 但 evidence 为空：无证据的「没问题」与没查无法区分"
            )
        # 名称必须与清单一致，否则「第 3 条」到底指什么就说不清了
        name = v.get("name")
        if isinstance(name, str) and name.strip() and name.strip() != MODES[mode]:
            caveats.append(f"mode {mode} 的 name 与清单不一致：{name!r}")

    missing = sorted(set(MODES) - set(seen))
    if missing:
        problems.append(f"缺少 mode {missing} 的裁决")

    blocking = [
        {"mode": m, "state": v.get("state"), "evidence": (v.get("evidence") or "")[:200]}
        for m, v in sorted(seen.items())
        if v.get("state") in BLOCKING
    ]

    computed_gate = "BLOCK" if (blocking or problems) else "PASS"
    claimed = doc.get("gate")
    if claimed is not None and claimed != computed_gate:
        problems.append(
            f"日志自报 gate={claimed!r}，但按 7 条裁决应为 {computed_gate}"
            f"（阻断项 {len(blocking)} 个、结构问题 {len(problems)} 个）"
            "——自报通过是最需要拦的一种"
        )

    return {
        "ok": computed_gate == "PASS",
        "gate": computed_gate,
        "claimed_gate": claimed,
        "blocking": blocking,
        "stage": doc.get("stage"),
        "n_verdicts": len(seen),
        "problems": problems,
        "caveats": caveats,
    }


def find_logs(patterns: Iterable[str] = _SEARCH_PATTERNS, root: str = REPO) -> list[str]:
    """按模式收集日志路径（排除 .venv 与 node_modules）。"""
    out: list[str] = []
    for pat in patterns:
        for p in glob.glob(os.path.join(root, pat), recursive=True):
            if os.sep + ".venv" + os.sep in p or "node_modules" in p:
                continue
            out.append(os.path.abspath(p))
    return sorted(set(out))


def audit_paths(paths: list[str]) -> dict[str, Any]:
    """审计一批日志；任一份阻断即整体阻断。"""
    results = []
    for p in paths:
        try:
            doc = json.loads(open(p, encoding="utf-8").read())
        except Exception as e:  # noqa: BLE001
            results.append({"path": p, "gate": "BLOCK", "ok": False,
                            "problems": [f"读不出 JSON：{e}"], "blocking": [],
                            "stage": None, "n_verdicts": 0, "caveats": []})
            continue
        try:
            r = validate(doc)
        except AuditFormatError as e:
            r = {"ok": False, "gate": "BLOCK", "claimed_gate": None, "blocking": [],
                 "stage": None, "n_verdicts": 0, "problems": [str(e)], "caveats": []}
        r["path"] = p
        results.append(r)

    gate = "PASS" if results and all(r["gate"] == "PASS" for r in results) else "BLOCK"
    return {"gate": gate, "n_logs": len(results), "logs": results}


def _self_test() -> int:
    """用内置样例验证判据本身（防止「门禁永远通过」这种假门禁）。"""
    base = {
        "stage": "distillation", "run_at": "2026-11-10T00:00:00Z",
        "verdicts": [
            {"mode": m, "name": MODES[m], "state": "CLEAR", "evidence": "见 run.log 第 N 行",
             "action_required": ""}
            for m in sorted(MODES)
        ],
        "gate": "PASS", "block_reasons": [], "next": "固化",
    }
    cases = []

    r = validate(json.loads(json.dumps(base)))
    cases.append(("干净日志应通过", r["ok"] and r["gate"] == "PASS"))

    bad = json.loads(json.dumps(base))
    bad["verdicts"][2]["state"] = "SUSPECTED"
    bad["verdicts"][2]["evidence"] = "R² 恰为 0.5，疑似实现 bug"
    r = validate(bad)
    cases.append(("SUSPECTED 应阻断", r["gate"] == "BLOCK" and r["blocking"]))

    bad2 = json.loads(json.dumps(base))
    bad2["verdicts"][5]["state"] = "INSUFFICIENT EVIDENCE"
    bad2["verdicts"][5]["evidence"] = "无运行日志"
    bad2["gate"] = "PASS"          # 自报通过
    r = validate(bad2)
    cases.append(("自报 PASS 但有阻断项，应被识破",
                  r["gate"] == "BLOCK" and any("自报 gate" in p for p in r["problems"])))

    bad3 = json.loads(json.dumps(base))
    bad3["verdicts"][0]["evidence"] = "   "
    r = validate(bad3)
    cases.append(("CLEAR 但无证据，应阻断", r["gate"] == "BLOCK"))

    bad4 = json.loads(json.dumps(base))
    bad4["verdicts"] = bad4["verdicts"][:6]
    try:
        validate(bad4)
        cases.append(("只有 6 条应报格式错", False))
    except AuditFormatError:
        cases.append(("只有 6 条应报格式错", True))

    try:
        validate({"verdict": "PASS_WITH_NOTES", "notes": ["合成数据不可外推"]})
        cases.append(("自由文本结论应被拒", False))
    except AuditFormatError:
        cases.append(("自由文本结论应被拒", True))

    ok = True
    for name, passed in cases:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print(f"\n自检 {len(cases)} 条：{'全部通过' if ok else '存在失败'}")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="7-mode 失败自检门禁")
    ap.add_argument("--path", action="append", default=[], help="指定日志路径（可多次）")
    ap.add_argument("--json", action="store_true", help="输出机器可读结果")
    ap.add_argument("--self-test", action="store_true", help="验证判据本身")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()

    paths = [os.path.abspath(p) for p in args.path] or find_logs()
    if not paths:
        msg = ("未找到任何 failure_audit_log.json —— 这说明 7-mode 审计没有留下记录。"
               "按 SKILL.md 它本该在 reproduction/improver/writer/distillation 各阶段末产出。"
               "本项记为「不适用」，**不记为通过**。")
        if args.json:
            print(json.dumps({"gate": "SKIP", "n_logs": 0, "reason": msg},
                             ensure_ascii=False, indent=2))
        else:
            print(f"SKIP  {msg}")
        return 2

    rep = audit_paths(paths)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        for r in rep["logs"]:
            print(f"[{r['gate']}] {r['path']}  stage={r.get('stage')} "
                  f"裁决={r.get('n_verdicts')}/7")
            for p in r["problems"]:
                print(f"        ✗ {p}")
            for b in r["blocking"]:
                print(f"        ⊘ mode {b['mode']} = {b['state']}：{b['evidence']}")
            for c in r["caveats"]:
                print(f"        ~ {c}")
        print(f"\n汇总：{rep['n_logs']} 份日志，门禁 {rep['gate']}")
        if rep["gate"] == "BLOCK":
            print("7-mode 铁律触发阻断：SUSPECTED / INSUFFICIENT EVIDENCE 未清零前不得进入下一阶段。",
                  file=sys.stderr)
    return 0 if rep["gate"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
