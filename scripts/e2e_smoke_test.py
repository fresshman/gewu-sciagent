#!/usr/bin/env python3
"""端到端冒烟测试：验证七阶段 handoff 串联不断链。

检查项：
1. 七个标准 handoff 文件均存在（handoff_1 ~ handoff_7）
2. 每个 handoff 的 next_input 指向正确的前序 handoff
3. 关键产出物存在（main.tex, claims.json, case.json）
4. handoff 状态合理（至少 ①②③⑤ 为 completed，④⑥⑦ 可为 partial）

用法：
  python scripts/e2e_smoke_test.py

退出码：
  0 = 全部通过
  1 = 有失败项
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKSPACE = REPO / "openclaw" / "workspace" / "agents"

# 七阶段 handoff 文件路径
HANDOFF_PATHS = {
    1: WORKSPACE / "gewu-director" / "handoff_1_direction.json",
    2: WORKSPACE / "gewu-ideation" / "handoff_2_litreview.json",
    3: WORKSPACE / "gewu-reproduction" / "handoff_3_repro.json",
    4: WORKSPACE / "gewu-improver" / "handoff_4_improver.json",
    5: WORKSPACE / "gewu-writer" / "handoff_5_writer.json",
    6: WORKSPACE / "gewu-publication" / "handoff_6_publication.json",
    7: WORKSPACE / "gewu-distillation" / "handoff_7_distillation.json",
}

# 关键产出物
ARTIFACTS = [
    REPO / "output" / "documents" / "coal_report" / "main.tex",
    REPO / "output" / "documents" / "coal_report" / "claims.json",
    REPO / "web" / ".local" / "case.json",
]

# 期望状态
EXPECTED_STATUS = {
    1: "completed",
    2: "completed",
    3: "completed",  # 或 completed_with_caveat
    4: "partial",    # 消融实验待补
    5: "completed",
    6: "completed",  # journal-match 已完整跑通
    7: "partial",    # 部分技能待沉淀
}


def check_handoff_files_exist() -> list[str]:
    """检查七个 handoff 文件是否均存在。"""
    errors = []
    for stage, path in HANDOFF_PATHS.items():
        if not path.exists():
            errors.append(f"handoff_{stage} 缺失: {path}")
    return errors


def check_handoff_chain() -> list[str]:
    """检查 handoff 串联：每个 handoff 的 next_input 指向前序 handoff。"""
    errors = []
    for stage in range(2, 8):
        path = HANDOFF_PATHS[stage]
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            inputs = data.get("inputs", [])
            if not inputs:
                errors.append(f"handoff_{stage} 无 inputs 字段")
                continue
            # 检查第一个 input 是否为前序 handoff
            first_input = inputs[0]
            expected_prefix = f"handoff_{stage - 1}"
            if not first_input.startswith(expected_prefix):
                errors.append(
                    f"handoff_{stage} 的第一个 input 应为 {expected_prefix}_*，"
                    f"实际为 {first_input}"
                )
        except Exception as e:
            errors.append(f"handoff_{stage} 解析失败: {e}")
    return errors


def check_handoff_status() -> list[str]:
    """检查 handoff 状态是否符合期望。"""
    errors = []
    for stage, expected in EXPECTED_STATUS.items():
        path = HANDOFF_PATHS[stage]
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            status = data.get("status")
            if stage == 3:
                # ③ 可以是 completed 或 completed_with_caveat
                if status not in ("completed", "completed_with_caveat"):
                    errors.append(
                        f"handoff_{stage} 状态应为 completed 或 completed_with_caveat，"
                        f"实际为 {status}"
                    )
            elif status != expected:
                errors.append(
                    f"handoff_{stage} 状态应为 {expected}，实际为 {status}"
                )
        except Exception as e:
            errors.append(f"handoff_{stage} 状态检查失败: {e}")
    return errors


def check_artifacts() -> list[str]:
    """检查关键产出物是否存在。"""
    errors = []
    for artifact in ARTIFACTS:
        if not artifact.exists():
            errors.append(f"产出物缺失: {artifact}")
    return errors


def main() -> int:
    print("=" * 60)
    print("端到端冒烟测试：七阶段 handoff 串联验证")
    print("=" * 60)

    all_errors = []

    print("\n[1/4] 检查 handoff 文件存在性...")
    errors = check_handoff_files_exist()
    if errors:
        print(f"  [FAIL] {len(errors)} 项失败:")
        for e in errors:
            print(f"    - {e}")
        all_errors.extend(errors)
    else:
        print("  [PASS] 七个 handoff 文件均存在")

    print("\n[2/4] 检查 handoff 串联...")
    errors = check_handoff_chain()
    if errors:
        print(f"  [FAIL] {len(errors)} 项失败:")
        for e in errors:
            print(f"    - {e}")
        all_errors.extend(errors)
    else:
        print("  [PASS] handoff 串联正确（每个阶段的 input 指向前序阶段）")

    print("\n[3/4] 检查 handoff 状态...")
    errors = check_handoff_status()
    if errors:
        print(f"  [FAIL] {len(errors)} 项失败:")
        for e in errors:
            print(f"    - {e}")
        all_errors.extend(errors)
    else:
        print("  [PASS] handoff 状态符合期望")

    print("\n[4/4] 检查关键产出物...")
    errors = check_artifacts()
    if errors:
        print(f"  [FAIL] {len(errors)} 项失败:")
        for e in errors:
            print(f"    - {e}")
        all_errors.extend(errors)
    else:
        print("  [PASS] 关键产出物均存在")

    print("\n" + "=" * 60)
    if all_errors:
        print(f"[FAIL] 测试失败：共 {len(all_errors)} 项问题")
        return 1
    else:
        print("[PASS] 测试通过：七阶段串联完整，关键产出物齐全")
        return 0


if __name__ == "__main__":
    sys.exit(main())
