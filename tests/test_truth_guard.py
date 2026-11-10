"""真值隔离强制实现测试（研究生命周期 ⑥）。

判据：这些用例必须是**真的会失败**的路径，而不是演示「函数能返回 True」。
最关键的用例是 `test_run_cv_rejects_bare_dict` —— 它证明隔离检查长在**实际调用链**上，
不是躺在旁边等人自愿调用。
"""
import math
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gewu.demo import mil_lite, truth_guard as tg  # noqa: E402
from gewu.demo.truth_guard import LeakageError  # noqa: E402


def _ys(**kw):
    return tg.truth_from_measured(kw or {"b1": 200.0, "b2": 210.0},
                                  source="/data/labels.json", unit="kcal/kg")


# ---------------------------------------------------------------- 标签来源
def test_truth_labels_carry_provenance():
    ys = _ys(b1=200.0)
    assert ys.source == "/data/labels.json"
    assert ys.unit == "kcal/kg"
    assert ys.provenance == {"source": "/data/labels.json", "unit": "kcal/kg", "n": 1}
    assert ys["b1"] == 200.0


def test_bare_dict_is_rejected():
    with pytest.raises(LeakageError, match="没有来源声明"):
        tg.require_provenance({"b1": 200.0})


def test_truth_labels_cannot_be_constructed_directly():
    """直接实例化必须失败，否则「带来源」就成了可以随手绕过的形式。"""
    with pytest.raises(TypeError, match="不能直接构造"):
        tg.TruthLabels({"b1": 200.0})


def test_empty_source_is_rejected():
    with pytest.raises(LeakageError, match="必须声明来源"):
        tg.truth_from_measured({"b1": 1.0}, source="   ")


@pytest.mark.parametrize("src", [
    "/runs/predictions.csv",
    "/out/pred/y.csv",
    "/tmp/yhat.json",
    "D:/x/inference_out.json",
    "/data/forecast_2026.csv",
])
def test_prediction_source_is_rejected(src):
    """把预测产物当标签来源是这条链上最真实的作弊方式，必须直接拒绝。"""
    with pytest.raises(LeakageError, match="预测产物"):
        tg.truth_from_measured({"b1": 1.0}, source=src)


def test_nan_label_is_rejected():
    with pytest.raises(LeakageError, match="非有限值"):
        tg.truth_from_measured({"b1": float("nan")}, source="/d/labels.json")
    with pytest.raises(LeakageError, match="非有限值"):
        tg.truth_from_measured({"b1": math.inf}, source="/d/labels.json")


def test_non_numeric_label_is_rejected():
    with pytest.raises(LeakageError, match="不是数值"):
        tg.truth_from_measured({"b1": "pending"}, source="/d/labels.json")


def test_empty_labels_rejected():
    with pytest.raises(LeakageError, match="标签为空"):
        tg.truth_from_measured({}, source="/d/labels.json")


# ---------------------------------------------------------------- 折分区
def test_valid_partition_passes():
    folds = [["b1", "b2"], ["b3", "b4"]]
    assert tg.validate_folds(folds) == folds


def test_bag_in_two_folds_is_leakage():
    """训练集由「其余所有 bag」组成 → 跨折重复 = 同时进训练与验证。"""
    with pytest.raises(LeakageError, match="同时出现在第 0 折与第 1 折"):
        tg.validate_folds([["b1", "b2"], ["b2", "b3"]])


def test_duplicate_within_fold_is_leakage():
    with pytest.raises(LeakageError, match="出现两次"):
        tg.validate_folds([["b1", "b1", "b2"], ["b3"]])


def test_empty_fold_is_leakage():
    with pytest.raises(LeakageError, match="为空"):
        tg.validate_folds([["b1"], []])


def test_empty_folds_is_leakage():
    with pytest.raises(LeakageError, match="折划分为空"):
        tg.validate_folds([])


def test_assert_disjoint_detects_overlap():
    tg.assert_disjoint(["a", "b"], ["c"])          # 不抛
    with pytest.raises(LeakageError, match="重叠 bag"):
        tg.assert_disjoint(["a", "b"], ["b", "c"])


# ---------------------------------------------------------------- 覆盖一致性
def test_label_missing_for_bag_in_fold():
    ys = _ys(b1=200.0)
    with pytest.raises(LeakageError, match="没有标签"):
        tg.check_cv_inputs(ys, [["b1"], ["b2"]])


def test_extra_feature_bag_is_rejected():
    """永不被评估却参与训练的 bag 是静默泄漏面，必须拒绝而不是忽略。"""
    ys = _ys(b1=200.0, b2=210.0, b3=220.0)
    with pytest.raises(LeakageError, match="多出"):
        tg.check_cv_inputs(ys, [["b1"], ["b2"]], feats={"b1": 1, "b2": 2, "b9": 3})


def test_missing_feature_is_rejected():
    ys = _ys(b1=200.0, b2=210.0)
    with pytest.raises(LeakageError, match="没有特征"):
        tg.check_cv_inputs(ys, [["b1"], ["b2"]], feats={"b1": 1})


# ---------------------------------------------------------------- 长在实际链路上
def test_run_cv_rejects_bare_dict():
    """最关键的一条：拦截点在 run_cv 内部，不是靠调用方记得先调 guard。"""
    feats = {"b1": {"shape": None}, "b2": {"shape": None}}
    with pytest.raises(LeakageError, match="没有来源声明"):
        mil_lite.run_cv(feats, {"b1": 200.0, "b2": 210.0}, [["b1"], ["b2"]])


def test_run_cv_rejects_overlapping_folds_before_fitting():
    """折重叠必须在**拟合之前**就炸，不能先跑完再校验（那样报告已经产出了）。"""
    ys = _ys(b1=200.0, b2=210.0)
    feats = {"b1": {"shape": None}, "b2": {"shape": None}}
    with pytest.raises(LeakageError, match="同时出现在"):
        mil_lite.run_cv(feats, ys, [["b1", "b2"], ["b2"]])
