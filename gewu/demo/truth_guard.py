"""真值隔离的**强制实现**（研究生命周期 ⑥ 的可执行实体）。

为什么需要这个模块
------------------
research_lifecycle ⑥ 写着「真实标签仅来自实验测定或公开数据集；模型预测不得回填当真值。
交叉验证测试折严格隔离」。在补上本模块之前，这句话只是**文档里的一句话**：
`run_cv(feats, ys, folds)` 收一个裸 `dict`，谁都可以把上一轮的预测值当标签传进去，
代码不会反对，报告照样生成，评审也看不出来。

本模块把这句话变成三个**会让流程失败**的检查：

1. `TruthLabels` —— 标签必须由 `truth_from_measured()` 构造，并携带来源声明。
   裸 `dict` / 直接 `TruthLabels({...})` 都会抛错，所以「顺手拿预测结果当标签」这条路
   在类型层面就走不通，而不是靠自觉。
2. `validate_folds()` —— 折划分必须是**分区**：bag 不得重复、不得跨折出现。
   `tr = [b for b in all_ids if b not in va_set]` 这种写法在 fold 有重复时会把
   同一 bag 同时放进训练与验证，而且**不报错**，指标还很好看。
3. `assert_disjoint()` —— 训练/验证集合必须不相交（对上面那类重写逻辑的兜底）。

边界（必须诚实）
----------------
* 本模块保证「标签带来源 + 折不重叠」。它**不能**证明那个来源文件本身是真的测定值：
  如果 `labels.json` 被人手工改成预测值，`truth_from_measured` 无从得知。
  能做的只有一条：**来源路径命中预测产物特征（pred/prediction/infer/forecast）时直接拒绝**，
  把最容易被误用的那条路堵死，其余靠人工与 D2 溯源。
* 它也不管测试折是否被反复用来调参（那是选择偏差，不是隔离问题），后者由内层 CV 纪律负责。
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Iterable, Mapping

__all__ = [
    "LeakageError",
    "TruthLabels",
    "truth_from_measured",
    "validate_folds",
    "assert_disjoint",
    "require_provenance",
    "check_cv_inputs",
]

# 来源路径里出现这些片段，几乎一定是预测产物而不是测定值
_FORBIDDEN_SOURCE_HINTS = (
    "pred", "prediction", "preds", "forecast", "infer", "inference",
    "output_pred", "yhat", "y_hat", "smoothed",
)


class LeakageError(RuntimeError):
    """真值隔离被破坏。单独一个异常类型，便于上层区分「数据问题」与「代码缺陷」。"""


_TOKEN = object()


class TruthLabels(dict):
    """带来源声明的标签映射 ``{bag_id: value}``。

    只能由 :func:`truth_from_measured` 构造。直接实例化会抛 ``TypeError``，
    这是故意的：标签的**来源**是这条链上最容易被悄悄替换的东西，必须留痕。
    """

    __slots__ = ("source", "unit")

    def __init__(self, *args, _token=None, source: str = "", unit: str | None = None):
        if _token is not _TOKEN:
            raise TypeError(
                "TruthLabels 不能直接构造：请用 truth_from_measured(values, source=...)，"
                "让标签带上来源声明。裸字典当标签正是真值隔离要防的事。"
            )
        super().__init__(*args)
        self.source = source
        self.unit = unit

    @property
    def provenance(self) -> dict:
        return {"source": self.source, "unit": self.unit, "n": len(self)}


def truth_from_measured(
    values: Mapping[str, float],
    *,
    source: str,
    unit: str | None = None,
) -> TruthLabels:
    """声明「这些标签来自该来源的实测值」，返回可被 CV 接受的标签容器。

    Args:
        values: ``{bag_id: 数值}``。必须非空、全为有限浮点。
        source: 来源标识（数据集文件路径 / 数据集名 + 版本）。**必填**。
        unit:   单位（如 kcal/kg），可选但建议填。

    Raises:
        LeakageError: 来源为空、来源指向预测产物、标签为空、或含非有限值。
    """
    src = (source or "").strip()
    if not src:
        raise LeakageError(
            "标签必须声明来源（实验测定文件 / 公开数据集名+版本）。"
            "空来源等于无法证明它不是预测回填。"
        )
    low = src.lower().replace("\\", "/")
    for hint in _FORBIDDEN_SOURCE_HINTS:
        if hint in low:
            raise LeakageError(
                f"标签来源看起来是预测产物（命中 '{hint}'）：{src}。"
                "模型预测不得回填为真值——真值只能来自测定或公开数据集的标签字段。"
            )

    if not values:
        raise LeakageError("标签为空：无法证明这是测定值，也无法训练。")

    clean: dict[str, float] = {}
    for k, v in values.items():
        try:
            f = float(v)
        except (TypeError, ValueError) as e:
            raise LeakageError(f"标签 {k!r} 不是数值：{v!r}") from e
        if not math.isfinite(f):
            raise LeakageError(f"标签 {k!r} 非有限值：{f!r}（NaN/inf 常是预测失败的痕迹）")
        clean[str(k)] = f

    return TruthLabels(clean, _token=_TOKEN, source=src, unit=unit)


def require_provenance(ys) -> TruthLabels:
    """确认标签带了来源声明；裸 mapping 一律拒绝。"""
    if not isinstance(ys, TruthLabels):
        raise LeakageError(
            f"标签类型是 {type(ys).__name__}，没有来源声明。"
            "请用 truth_from_measured({...}, source='labels.json') 构造——"
            "裸 dict 无法区分「测定值」与「上一轮预测值」，这正是隔离要拦的东西。"
        )
    return ys


def validate_folds(folds: Iterable[Iterable[str]]) -> list[list[str]]:
    """校验折划分是**分区**：非空、无重复、无跨折重叠。返回规整后的列表。

    Raises:
        LeakageError: 空划分、空折、同一 bag 出现在多个折、或同一折内重复。
    """
    folds = [list(f) for f in folds]
    if not folds:
        raise LeakageError("折划分为空。")

    seen: dict[str, int] = {}
    for i, fold in enumerate(folds):
        if not fold:
            raise LeakageError(f"第 {i} 折为空，划分损坏。")
        local: set[str] = set()
        for bid in fold:
            b = str(bid)
            if b in local:
                raise LeakageError(
                    f"第 {i} 折内 {b!r} 出现两次：验证集重复计权，指标会被重复样本放大。"
                )
            local.add(b)
            if b in seen:
                raise LeakageError(
                    f"{b!r} 同时出现在第 {seen[b]} 折与第 {i} 折："
                    "训练集由「其余所有 bag」组成，此时它会同时进训练与验证——这就是泄漏。"
                )
            seen[b] = i
    return folds


def assert_disjoint(train: Iterable[str], test: Iterable[str]) -> None:
    """断言训练/验证集合不相交。"""
    tr = {str(x) for x in train}
    va = {str(x) for x in test}
    both = tr & va
    if both:
        sample = ", ".join(sorted(both)[:5])
        raise LeakageError(
            f"训练集与验证集有 {len(both)} 个重叠 bag（{sample}...）。"
            "任何指标都不能在重叠划分上报告。"
        )


def check_cv_inputs(ys: Mapping[str, float], folds: Iterable[Iterable[str]],
                    feats: Mapping[str, object] | None = None) -> list[list[str]]:
    """交叉验证入口的统一前置检查：标签来源 + 折分区 + 覆盖一致。

    Returns:
        规整后的 folds（供调用方继续使用）。

    Raises:
        LeakageError: 标签无来源 / 折重叠 / 折里的 bag 没有标签或特征 / 特征与标签键不一致。
    """
    require_provenance(ys)
    folds = validate_folds(folds)

    fold_ids = {str(b) for fold in folds for b in fold}
    missing_y = sorted(fold_ids - {str(k) for k in ys})
    if missing_y:
        raise LeakageError(
            f"{len(missing_y)} 个 bag 在折里但没有标签（如 {missing_y[:3]}）——"
            "这通常意味着标签与数据的键对不上，若静默跳过会得到偏乐观的指标。"
        )
    if feats is not None:
        missing_f = sorted(fold_ids - {str(k) for k in feats})
        if missing_f:
            raise LeakageError(f"{len(missing_f)} 个 bag 没有特征（如 {missing_f[:3]}）")
        extra = sorted({str(k) for k in feats} - fold_ids)
        if extra:
            raise LeakageError(
                f"特征里多出 {len(extra)} 个不在任何折中的 bag（如 {extra[:3]}）："
                "它们永远不会被评估，却会参与训练，属于静默数据泄漏面。"
            )
    return folds


def source_from_dir(root) -> str:
    """从数据目录推出标签来源字符串（`<root>/labels.json`），供调用方直接用。"""
    return str(Path(os.path.abspath(root)) / "labels.json")
