"""7-mode 失败自检门禁测试。

一个门禁最危险的失效方式不是误报，是**永远通过**。所以这里重点测「该红时必须红」：
SUSPECTED 阻断、自报 PASS 被识破、CLEAR 无证据被拒、旧式自由文本被拒。
"""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import failure_audit_gate as G  # noqa: E402


def _log(**over):
    doc = {
        "stage": "improver",
        "run_at": "2026-11-10T09:00:00Z",
        "verdicts": [
            {"mode": m, "name": G.MODES[m], "state": "CLEAR",
             "evidence": f"见 run 日志 mode {m}", "action_required": ""}
            for m in sorted(G.MODES)
        ],
        "gate": "PASS",
        "block_reasons": [],
        "next": "进入 write",
    }
    for k, v in over.items():
        doc[k] = v
    return doc


# ---------------------------------------------------------------- 结构与枚举
def test_clean_log_passes():
    r = G.validate(_log())
    assert r["ok"] is True and r["gate"] == "PASS"
    assert r["n_verdicts"] == 7


def test_legacy_freeform_is_rejected_not_passed():
    """真实仓库里的 handoff 就长这样：{"verdict": "PASS_WITH_NOTES", "notes": [...]}。
    它必须被明确判成「不是 7-mode 日志」，不能当成通过。"""
    with pytest.raises(G.AuditFormatError, match="自由文本结论"):
        G.validate({"verdict": "PASS_WITH_NOTES",
                    "notes": ["本课题为合成数据，不可外推绝对精度"]})


def test_six_verdicts_is_format_error():
    doc = _log()
    doc["verdicts"] = doc["verdicts"][:6]
    with pytest.raises(G.AuditFormatError, match="正好 7 条"):
        G.validate(doc)


def test_duplicate_mode_is_rejected():
    doc = _log()
    doc["verdicts"][1]["mode"] = 1
    r = G.validate(doc)
    assert r["gate"] == "BLOCK"
    assert any("重复" in p for p in r["problems"]) or any("缺少 mode" in p for p in r["problems"])


def test_illegal_state_is_rejected():
    doc = _log()
    doc["verdicts"][0]["state"] = "LOOKS_FINE"
    r = G.validate(doc)
    assert r["gate"] == "BLOCK"
    assert any("state 非法" in p for p in r["problems"])


# ---------------------------------------------------------------- 铁律是否真的咬
@pytest.mark.parametrize("state", ["SUSPECTED", "INSUFFICIENT EVIDENCE"])
def test_blocking_states_block(state):
    doc = _log()
    doc["verdicts"][3]["state"] = state
    doc["verdicts"][3]["evidence"] = "消融未排除最明显 shortcut"
    r = G.validate(doc)
    assert r["gate"] == "BLOCK"
    assert [b["mode"] for b in r["blocking"]] == [4]


def test_self_reported_pass_is_caught():
    """日志写 gate=PASS 但有条目 SUSPECTED —— 这是最常见的一种「自欺」，必须识破。"""
    doc = _log()
    doc["verdicts"][2]["state"] = "SUSPECTED"
    doc["verdicts"][2]["evidence"] = "R² 恰为 0.5，疑似实现 bug"
    assert doc["gate"] == "PASS"
    r = G.validate(doc)
    assert r["gate"] == "BLOCK"
    assert any("自报 gate" in p for p in r["problems"])


def test_clear_without_evidence_blocks():
    """「CLEAR 但指不出证据」= 没查。这正是 7-mode 想拦的 Mode 3/6。"""
    doc = _log()
    doc["verdicts"][0]["evidence"] = "  "
    r = G.validate(doc)
    assert r["gate"] == "BLOCK"
    assert any("evidence 为空" in p for p in r["problems"])


def test_not_applicable_also_needs_evidence():
    doc = _log()
    doc["verdicts"][4]["state"] = "NOT APPLICABLE"
    doc["verdicts"][4]["evidence"] = ""
    assert G.validate(doc)["gate"] == "BLOCK"


def test_name_mismatch_is_caveat_not_block():
    doc = _log()
    doc["verdicts"][0]["name"] = "Some other name"
    r = G.validate(doc)
    assert r["gate"] == "PASS"
    assert r["caveats"]


# ---------------------------------------------------------------- 多份日志与 CLI
def test_any_blocking_log_blocks_whole_run(tmp_path):
    ok = tmp_path / "a.json"
    ok.write_text(json.dumps(_log(), ensure_ascii=False), encoding="utf-8")
    bad_doc = _log()
    bad_doc["verdicts"][6]["state"] = "SUSPECTED"
    bad = tmp_path / "b.json"
    bad.write_text(json.dumps(bad_doc, ensure_ascii=False), encoding="utf-8")

    rep = G.audit_paths([str(ok), str(bad)])
    assert rep["gate"] == "BLOCK" and rep["n_logs"] == 2
    assert G.audit_paths([str(ok)])["gate"] == "PASS"


def test_unreadable_json_blocks_not_skips(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    rep = G.audit_paths([str(p)])
    assert rep["gate"] == "BLOCK"
    assert any("读不出 JSON" in x for x in rep["logs"][0]["problems"])


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "failure_audit_gate.py"), *args],
        capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
    )


def test_cli_exit_codes():
    ok = _run_cli("--self-test")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    # 无日志时必须是 2（不适用），不能是 0
    empty = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "failure_audit_gate.py"),
         "--path", os.path.join(ROOT, "no_such_log.json")],
        capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
    )
    assert empty.returncode == 1        # 显式指定的路径不存在 → 阻断（不是「没找到日志」）
