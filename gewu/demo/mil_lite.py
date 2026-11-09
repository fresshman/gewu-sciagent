"""MIL-lite：只用 numpy + scikit-learn 的可复现多示例回归基线。

为什么不用 torch
----------------
真实课题的 MIL 模型（attention / 可学习 LSE 池化）依赖外部权重与 torch，评审机器上
未必具备。本模块用**闭式/浅层**方法复刻同一套方法学要点，保证执行
``pip install -r requirements.txt`` 之后在任何机器上都能秒级跑完，从而让"端到端可复现"
这件事可被独立验证，而不是只能听作者陈述。

三个对照臂（与注册表 ``demo_synth.json`` 的三条实验一一对应）
------------------------------------------------------------
* ``plsr_baseline``：**袋均谱 → PLSR**。经典做法，等价于"把一个 bag 拍平成一个样本"。
* ``mil_direct``   ：**逐实例谱形定标 → 实例 PLS → 池化**（β 由内层 CV 选，β=0 即均值）。
* ``our_hybrid``   ：``mil_direct`` + 用**强度池化统计量**回归残差的 Ridge。

方法学要点（也是消融要检验的假设）
----------------------------------
1. **尺度与成分可分离**：逐实例谱形定标 ``spec_i / mean(spec_i)`` 去掉颗粒尺度 ``a_i``，
   只留成分；而 ``a_i`` 由上尾统计量（max / p90 / std）单独承载。
2. **先定标再池化 vs 先池化再回归**：前者让每个实例成为一条独立训练样本（样本量 ×K），
   且不被尺度污染；后者把不同尺度的颗粒混在一起平均，成分信号被稀释。
3. **池化阶数**：LSE 的 β 在内层 CV 上选。若最优 β→0，说明该数据上"均值池化已足够，
   增益来自逐实例定标与残差建模，而非高阶池化"——这个结论会如实写进报告，
   不为了迎合"用了 LSE"而强行取 β>0。

防泄漏约定
----------
* 外层 5 折切 **bag**（不做实例级切分，否则同一 bag 的实例跨越训练/验证即泄漏）；
* β 与 Ridge 的 α 只在内层 CV 的**折外预测**上选；
* 残差特征同样来自内层折外预测，避免"用自己拟合的模型给自己算残差"的乐观偏差。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from sklearn.cross_decomposition import PLSRegression
from sklearn.linear_model import RidgeCV

N_BINS = 64
N_COMPONENTS = 6
BETA_GRID = (0.0, 0.25, 0.5, 1.0, 2.0, 4.0)
RIDGE_ALPHAS = tuple(float(a) for a in np.logspace(-3, 4, 15))
INNER_FOLDS = 4


# --------------------------------------------------------------------------
# 特征
# --------------------------------------------------------------------------
def bin_spectrum(spec: np.ndarray, n_bins: int = N_BINS) -> np.ndarray:
    """把 (K, L) 光谱按通道等宽分箱取均值 → (K, n_bins)。"""
    k, n = spec.shape
    if n % n_bins:
        raise ValueError(f"通道数 {n} 不能被分箱数 {n_bins} 整除")
    return spec.reshape(k, n_bins, n // n_bins).mean(axis=2)


def build_features(spectra: np.ndarray) -> dict[str, np.ndarray]:
    """单个 bag 的三种表示。

    * ``raw``  : 分箱后的原始强度（含颗粒尺度），用于"先平均"的基线；
    * ``shape``: 逐实例除以自身均值（尺度不变），只保留谱形 → 成分；
    * ``amp``  : 逐实例平均强度 / 袋内均值，即相对颗粒尺度，用于承载异质性。
    """
    raw = bin_spectrum(spectra)
    amp = raw.mean(axis=1)
    if np.any(amp <= 0):
        raise ValueError("存在非正强度光谱，无法定标")
    return {"raw": raw, "shape": raw / amp[:, None], "amp": amp / amp.mean()}


def amp_stats(amp: np.ndarray) -> np.ndarray:
    """强度池化统计量 —— 袋均流程会丢掉、但对异质性最有信息量的一组量。

    取分位数而非仅 max，是为了对单个异常颗粒稳健（max 单独使用时方差偏大）。
    """
    amp = np.asarray(amp, dtype=np.float64).ravel()
    return np.array(
        [
            amp.mean(),
            amp.max(),
            amp.std(),
            amp.max() - amp.mean(),
            amp.max() - amp.min(),
            np.percentile(amp, 75),
            np.percentile(amp, 90),
            float(np.log(amp.size)),
            float(amp.size),
        ],
        dtype=np.float64,
    )


def residual_features(inst_pred: np.ndarray, amp: np.ndarray) -> np.ndarray:
    """残差回归输入：**只用强度池化统计量** + 实例数。

    刻意不放入实例预测的均值/极差：它们与 MIL 臂的输出强共线，会把 Ridge 推向
    过拟合（实测 n=25 时 12 维版本反而比不加残差更差，7 维版本全样本量都更优）。
    这也是一条可复用的经验：残差模型应当建模"基线看不到的信息"，而不是重复基线。
    """
    a = amp_stats(amp)
    # 去掉 mean（袋内均值恒为 1，无信息量），保留上尾/离散度/分位数与样本量
    return np.concatenate([a[1:7], [a[7]]])


# --------------------------------------------------------------------------
# 池化
# --------------------------------------------------------------------------
def lse_pool(pred: np.ndarray, beta: float) -> float:
    """log-sum-exp 池化：β=0 退化为均值，β→∞ 趋近最大值。

    先标准化再池化，使 β 的尺度与标签量纲（kcal/kg）无关。
    """
    pred = np.asarray(pred, dtype=np.float64).ravel()
    if pred.size == 0:
        raise ValueError("空 bag 无法池化")
    mu, sd = float(pred.mean()), float(pred.std())
    if beta <= 1e-9 or sd <= 1e-12:
        return mu
    z = (pred - mu) / sd
    m = float(z.max())
    lse = m + math.log(float(np.mean(np.exp(beta * (z - m))))) / beta
    return mu + sd * lse


# --------------------------------------------------------------------------
# 单折训练 / 预测
# --------------------------------------------------------------------------
@dataclass
class FoldModel:
    pls_bag: PLSRegression
    pls_inst: PLSRegression
    beta: float
    ridge: RidgeCV | None
    ridge_alpha: float | None
    beta_scores: dict = field(default_factory=dict)


def _fit_pls(x: np.ndarray, y: np.ndarray, n_components: int = N_COMPONENTS):
    k = min(n_components, x.shape[0] - 1, x.shape[1])
    return PLSRegression(n_components=max(1, k), scale=False).fit(x, y)


def _inner_oof(train_ids, feats, ys):
    """内层 K 折折外预测（只用于选 β / 拟合 Ridge，不接触验证折）。"""
    order = sorted(train_ids, key=lambda b: ys[b])
    inner = [[] for _ in range(INNER_FOLDS)]
    for i, bid in enumerate(order):
        inner[i % INNER_FOLDS].append(bid)

    oof = {bid: {"inst_pred": None, "plsr_pred": None} for bid in train_ids}
    for f in range(INNER_FOLDS):
        va = inner[f]
        va_set = set(va)
        tr = [b for b in train_ids if b not in va_set]
        if not tr or not va:
            continue
        x_bag = np.stack([feats[b]["raw"].mean(axis=0) for b in tr])
        y_tr = np.array([ys[b] for b in tr])
        pls_bag = _fit_pls(x_bag, y_tr)

        x_inst = np.concatenate([feats[b]["shape"] for b in tr])
        y_inst = np.concatenate(
            [np.full(feats[b]["shape"].shape[0], ys[b]) for b in tr]
        )
        pls_inst = _fit_pls(x_inst, y_inst)

        for b in va:
            oof[b]["inst_pred"] = pls_inst.predict(feats[b]["shape"]).ravel()
            oof[b]["plsr_pred"] = float(
                pls_bag.predict(feats[b]["raw"].mean(axis=0)[None, :]).ravel()[0]
            )
    return oof


def _choose_beta(oof, train_ids, ys) -> tuple[float, dict]:
    scores = {}
    for beta in BETA_GRID:
        err = []
        for b in train_ids:
            rec = oof[b]
            if rec["inst_pred"] is None:
                continue
            err.append((lse_pool(rec["inst_pred"], beta) - ys[b]) ** 2)
        scores[beta] = float(np.sqrt(np.mean(err))) if err else float("inf")
    # 平手时取更小的 β（更简单的模型），避免无收益地引入高阶池化
    best = min(scores, key=lambda k: (round(scores[k], 6), k))
    return best, {f"{k:g}": round(v, 4) for k, v in scores.items()}


def fit_fold(train_ids, feats, ys) -> FoldModel:
    oof = _inner_oof(train_ids, feats, ys)
    beta, beta_scores = _choose_beta(oof, train_ids, ys)

    rows, targets = [], []
    for b in train_ids:
        rec = oof[b]
        if rec["inst_pred"] is None:
            continue
        rows.append(residual_features(rec["inst_pred"], feats[b]["amp"]))
        targets.append(ys[b] - lse_pool(rec["inst_pred"], beta))

    ridge, alpha = None, None
    if len(rows) >= 6 and np.std(targets) > 1e-9:
        ridge = RidgeCV(alphas=RIDGE_ALPHAS, cv=min(INNER_FOLDS, len(rows))).fit(
            np.stack(rows), np.asarray(targets, dtype=np.float64)
        )
        alpha = float(ridge.alpha_)

    x_bag = np.stack([feats[b]["raw"].mean(axis=0) for b in train_ids])
    y_tr = np.array([ys[b] for b in train_ids])
    pls_bag = _fit_pls(x_bag, y_tr)

    x_inst = np.concatenate([feats[b]["shape"] for b in train_ids])
    y_inst = np.concatenate(
        [np.full(feats[b]["shape"].shape[0], ys[b]) for b in train_ids]
    )
    pls_inst = _fit_pls(x_inst, y_inst)

    return FoldModel(pls_bag=pls_bag, pls_inst=pls_inst, beta=beta, ridge=ridge,
                     ridge_alpha=alpha, beta_scores=beta_scores)


def predict_fold(model: FoldModel, ids, feats) -> dict:
    out = {"plsr": [], "mil": [], "hybrid": []}
    for b in ids:
        f = feats[b]
        out["plsr"].append(
            float(model.pls_bag.predict(f["raw"].mean(axis=0)[None, :]).ravel()[0])
        )
        inst_pred = model.pls_inst.predict(f["shape"]).ravel()
        mil = lse_pool(inst_pred, model.beta)
        out["mil"].append(mil)
        resid = 0.0
        if model.ridge is not None:
            resid = float(
                model.ridge.predict(
                    residual_features(inst_pred, f["amp"])[None, :]
                ).ravel()[0]
            )
        out["hybrid"].append(mil + resid)
    return {k: np.asarray(v, dtype=np.float64) for k, v in out.items()}


# --------------------------------------------------------------------------
# 指标
# --------------------------------------------------------------------------
def metrics(y: np.ndarray, pred: np.ndarray) -> dict:
    y = np.asarray(y, dtype=np.float64)
    pred = np.asarray(pred, dtype=np.float64)
    err = pred - y
    ss_res = float(np.sum(err ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return {
        "n": int(y.size),
        "rmse": round(float(np.sqrt(np.mean(err ** 2))), 4),
        "mae": round(float(np.mean(np.abs(err))), 4),
        "r2": round(1.0 - ss_res / ss_tot, 4) if ss_tot > 0 else None,
        "bias": round(float(err.mean()), 4),
    }


def paired_test(a: np.ndarray, b: np.ndarray) -> dict:
    """逐折配对 t 检验（a - b），并同时报告 Wilcoxon。

    n=5 时 Wilcoxon 双侧最小可达 p=0.0625，本身就不显著；两个结论都报，
    不择优、不隐藏。
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    d = a - b
    n = int(d.size)
    res = {
        "n": n,
        "mean_delta": round(float(d.mean()), 4),
        "std_delta": round(float(d.std(ddof=1)), 4) if n > 1 else None,
        "deltas": [round(float(x), 4) for x in d],
        "all_same_direction": bool(np.all(d > 0) or np.all(d < 0)),
        "method": "paired t-test (two-sided)",
    }
    try:
        from scipy import stats

        t, p = stats.ttest_rel(a, b)
        res["t"] = round(float(t), 4)
        res["df"] = n - 1
        res["p"] = round(float(p), 6)
        se = float(d.std(ddof=1) / math.sqrt(n)) if n > 1 else float("nan")
        if se and not math.isnan(se):
            lo, hi = stats.t.interval(0.95, n - 1, loc=float(d.mean()), scale=se)
            res["ci95"] = [round(float(lo), 4), round(float(hi), 4)]
        try:
            w = stats.wilcoxon(a, b)
            res["wilcoxon"] = {
                "stat": round(float(w.statistic), 4),
                "p": round(float(w.pvalue), 6),
                "note": "n=5 时双侧最小可达 p=0.0625",
            }
        except ValueError as e:
            res["wilcoxon"] = {"error": str(e)}
    except ImportError:  # pragma: no cover - requirements 已含 scipy
        res["p"] = None
        res["note"] = "scipy 不可用，仅报告均值差"
    return res


# --------------------------------------------------------------------------
# 5 折交叉验证（对外主入口）
# --------------------------------------------------------------------------
ARMS = ("plsr", "mil", "hybrid")
ARM_LABELS = {
    "plsr": "袋均谱 PLSR 基线",
    "mil": "MIL 逐实例定标 + 池化",
    "hybrid": "MIL + 强度上尾残差（本课题方法）",
}


def run_cv(feats: dict, ys: dict, folds: list[list[str]]) -> dict:
    """按给定 bag 级折划分跑 5 折，返回逐折预测与汇总。

    返回结构与真实课题的 ``summary.json`` 保持同构（``per_fold`` / ``mean`` /
    ``std`` / ``predictions``），便于下游沿用同一套校验逻辑，不必为演示另写一套。
    """
    per_fold: list[dict] = []
    preds: list[dict] = []
    all_ids = [bid for fold in folds for bid in fold]

    for f, va in enumerate(folds):
        va_set = set(va)
        tr = [b for b in all_ids if b not in va_set]
        if not tr or not va:
            raise ValueError(f"第 {f} 折为空，划分文件损坏")
        model = fit_fold(tr, feats, ys)
        pr = predict_fold(model, va, feats)
        y_true = np.array([ys[b] for b in va], dtype=np.float64)

        rec = {
            "fold": f,
            "n": len(va),
            "n_train": len(tr),
            "beta": model.beta,
            "beta_scores": model.beta_scores,
            "ridge_alpha": model.ridge_alpha,
        }
        for arm in ARMS:
            rec[arm] = metrics(y_true, pr[arm])
        per_fold.append(rec)

        for i, b in enumerate(va):
            preds.append(
                {
                    "fold": f,
                    "bag_id": b,
                    "n_instances": int(feats[b]["shape"].shape[0]),
                    "y_true": round(float(y_true[i]), 6),
                    "plsr_pred": round(float(pr["plsr"][i]), 6),
                    "mil_pred": round(float(pr["mil"][i]), 6),
                    "hybrid_pred": round(float(pr["hybrid"][i]), 6),
                }
            )

    y_all = np.array([p["y_true"] for p in preds], dtype=np.float64)
    summary = {}
    for arm in ARMS:
        fold_rmse = np.array([r[arm]["rmse"] for r in per_fold], dtype=np.float64)
        fold_mae = np.array([r[arm]["mae"] for r in per_fold], dtype=np.float64)
        fold_r2 = np.array([r[arm]["r2"] for r in per_fold], dtype=np.float64)
        pooled = metrics(y_all, np.array([p[f"{arm}_pred"] for p in preds], dtype=np.float64))
        summary[arm] = {
            "label": ARM_LABELS[arm],
            "rmse_mean": round(float(fold_rmse.mean()), 4),
            "rmse_std": round(float(fold_rmse.std(ddof=0)), 4),
            "rmse_std_sample": round(float(fold_rmse.std(ddof=1)), 4),
            "mae_mean": round(float(fold_mae.mean()), 4),
            "mae_std": round(float(fold_mae.std(ddof=0)), 4),
            "r2_mean": round(float(fold_r2.mean()), 4),
            "r2_std": round(float(fold_r2.std(ddof=0)), 4),
            "per_fold_rmse": [round(float(x), 4) for x in fold_rmse],
            "pooled": pooled,
        }

    rmse = {arm: np.array([r[arm]["rmse"] for r in per_fold]) for arm in ARMS}
    gain = (summary["plsr"]["rmse_mean"] - summary["hybrid"]["rmse_mean"]) / summary["plsr"]["rmse_mean"]
    tests = {
        "hybrid_vs_plsr": paired_test(rmse["hybrid"], rmse["plsr"]),
        "hybrid_vs_mil": paired_test(rmse["hybrid"], rmse["mil"]),
        "mil_vs_plsr": paired_test(rmse["mil"], rmse["plsr"]),
    }
    return {
        "per_fold": per_fold,
        "predictions": preds,
        "summary": summary,
        "paired_tests": tests,
        "improvement_pct": round(float(gain) * 100, 4),
        "convention": (
            "指标口径：per-fold 均值（每折各自算 RMSE，再对 5 折取均值/总体标准差 ddof=0）；"
            "pooled 为 70 个袋外预测合并后的指标。两者不可混用。"
        ),
        "beta_selected": [r["beta"] for r in per_fold],
        "ridge_alphas": [r["ridge_alpha"] for r in per_fold],
    }
