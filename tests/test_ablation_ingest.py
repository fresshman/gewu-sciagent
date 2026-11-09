"""组件级消融入库脚本（scripts/ablation_ingest.py）的校验与负向测试。

为什么需要负向测试：这个脚本的作用是「把外部项目的聚合结果变成仓库内可核对的快照」。
如果它对缺臂、输入漂移、两处数字不一致都照单全收，那快照就只是又一份自述。
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import ablation_ingest as A  # noqa: E402

SNAPSHOT = REPO / "docs" / "verification" / "ablation_component.json"

# 外部未发表项目不在库内；依赖它的用例应跳过而不是失败
needs_coal = pytest.mark.skipif(
    not A.resolve_coal_root(),
    reason="外部煤项目不在本机（按设计不入库），该用例不适用",
)


@pytest.fixture
def snap() -> dict:
    if not SNAPSHOT.is_file():
        pytest.skip("docs/verification/ablation_component.json 尚未生成")
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_real_snapshot_passes(snap: dict) -> None:
    assert A.validate(snap) == []


def test_missing_arm_rejected(snap: dict) -> None:
    bad = copy.deepcopy(snap)
    bad["arms"].pop("no_huber")
    problems = A.validate(bad)
    assert any("no_huber" in p for p in problems)


def test_wrong_fold_count_rejected(snap: dict) -> None:
    bad = copy.deepcopy(snap)
    bad["arms"]["no_film"]["per_fold_rmse"] = bad["arms"]["no_film"]["per_fold_rmse"][:3]
    problems = A.validate(bad)
    assert any("折数" in p for p in problems)


def test_plsr_drift_rejected(snap: dict) -> None:
    """PLSR 不依赖被消融组件；若某臂的 PLSR 值变了，说明数据或折划分漂移。"""
    bad = copy.deepcopy(snap)
    bad["arms"]["no_supcon"]["per_fold_plsr_rmse"][0] += 1.0
    problems = A.validate(bad)
    assert any("PLSR" in p for p in problems)


def test_missing_vs_base_rejected(snap: dict) -> None:
    bad = copy.deepcopy(snap)
    bad["arms"]["no_film"].pop("vs_base")
    problems = A.validate(bad)
    assert any("vs_base" in p for p in problems)


def test_snapshot_matches_handoff(snap: dict) -> None:
    """快照与 handoff_4 的摘要必须一致，否则两处数字会各自漂移。"""
    if not Path(A.HANDOFF4).is_file():
        pytest.skip("handoff_4 不在本机")
    assert A.check_handoff(snap) == []


def test_handoff_drift_detected(tmp_path, monkeypatch, snap: dict) -> None:
    """篡改 handoff 里的均值，必须被抓出来。"""
    if not Path(A.HANDOFF4).is_file():
        pytest.skip("handoff_4 不在本机")
    doc = json.loads(Path(A.HANDOFF4).read_text(encoding="utf-8"))
    doc["ablation_study"]["component_ablation"]["arms"][1]["mean_rmse_kcal_kg"] += 5.0
    fake = tmp_path / "handoff_4.json"
    fake.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(A, "HANDOFF4", str(fake))

    problems = A.check_handoff(snap)
    assert any("不一致" in p for p in problems)


@needs_coal
def test_check_mode_exit_zero() -> None:
    """--check 在真实仓库上应返回 0（不写文件）。"""
    assert A.main(["--check"]) == 0


def test_snapshot_matches_registry(snap: dict) -> None:
    """快照与实验注册表的 4 条 abl_comp_* 必须一致（数字存在的第三处）。"""
    if not Path(A.REGISTRY).is_file():
        pytest.skip("注册表不在本机")
    assert A.check_registry(snap) == []


def test_registry_missing_entry_detected(tmp_path, monkeypatch, snap: dict) -> None:
    if not Path(A.REGISTRY).is_file():
        pytest.skip("注册表不在本机")
    reg = json.loads(Path(A.REGISTRY).read_text(encoding="utf-8"))
    reg["experiments"] = [e for e in reg["experiments"] if e["id"] != "abl_comp_no_huber"]
    fake = tmp_path / "coal_mil.json"
    fake.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(A, "REGISTRY", str(fake))
    problems = A.check_registry(snap)
    assert any("abl_comp_no_huber" in p for p in problems)


def test_registry_value_drift_detected(tmp_path, monkeypatch, snap: dict) -> None:
    if not Path(A.REGISTRY).is_file():
        pytest.skip("注册表不在本机")
    reg = json.loads(Path(A.REGISTRY).read_text(encoding="utf-8"))
    for e in reg["experiments"]:
        if e["id"] == "abl_comp_no_film":
            e["metrics"]["per_fold_rmse_kcal"][2] += 1.0
    fake = tmp_path / "coal_mil.json"
    fake.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(A, "REGISTRY", str(fake))
    problems = A.check_registry(snap)
    assert any("fold2" in p for p in problems)


@needs_coal
def test_check_mode_catches_handoff_drift(tmp_path, monkeypatch) -> None:
    if not Path(A.HANDOFF4).is_file() or not SNAPSHOT.is_file():
        pytest.skip("快照或 handoff_4 不在本机")
    doc = json.loads(Path(A.HANDOFF4).read_text(encoding="utf-8"))
    doc["ablation_study"]["component_ablation"]["arms"][2]["mean_rmse_kcal_kg"] += 3.0
    fake = tmp_path / "handoff_4.json"
    fake.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(A, "HANDOFF4", str(fake))
    assert A.main(["--check"]) == 1
