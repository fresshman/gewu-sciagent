#!/usr/bin/env python
"""第二个真实领域：临床基线指标 → 疾病进展（UCI Diabetes，sklearn 内置离线数据）。

存在理由
--------
`sci-exp` 宣称「机制与学科彻底解耦」，但此前只有 coal（LIBS 光谱热值）一个**真实**领域，
外加一个 demo_synth 合成域。评审据此只能判定「领域泛化 1 例，不可信」。
本脚本提供第二个真实领域，用来证明**注册表 / 重算 / 溯源三件机制换学科后仍然成立**：

* 数据结构完全不同：这里是 442×10 的**表格基线指标**，不是 70×N 的光谱；
* 目标量纲完全不同：疾病进展指数（25–346），不是 kcal/kg；
* 方法族刻意只保留「与煤项目同族」的三个：PLSR / 线性 / 多项式+Ridge；
* **不改 gewu/ 下任何一行代码**（可用 `git diff --stat HEAD -- gewu/` 自证为空）。

数据来源与真实性
----------------
`sklearn.datasets.load_diabetes` 随 scikit-learn 分发包一起离线提供（原始来源 UCI / Efron 2004），
不需要联网、不需要申请。脚本会打印该 CSV 的 sha256 与 sklearn 版本，便于第三方核对是同一份数据。

诚实边界（写进结论前必须读）
--------------------------
1. 这只验证**机制**泛化，不验证**方法**泛化：本仓没有在第二个领域上跑过 7 阶段 LLM 链路，
   所以不能宣称「跨领域科研自动化已跑通」，只能说「同一套注册/重算/溯源，换领域零改动可用」。
2. 三个臂都是线性/多项式加正则的经典方法，不是深度模型；小样本（442）上深度模型没有优势，
   刻意不引入，避免为了「看起来高级」而加无收益的复杂度。
3. 结果只对本划分（KFold shuffle=True, seed=42）成立；`--repeat` 可换种子看稳定性，
   但台账只登记 seed=42 那一次，不做「挑最好种子」的动作。

用法
----
    python scripts/run_domain_diabetes.py --json          # 打印汇总 JSON（注册表重算用这个）
    python scripts/run_domain_diabetes.py --out DIR       # 同时落盘 summary.json 与逐折预测
    python scripts/run_domain_diabetes.py --json --repeat 10   # 换 10 个种子看稳定性
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np
import sklearn.datasets as skds
from sklearn import __version__ as SKLEARN_VERSION
from sklearn.cross_decomposition import PLSRegression
from sklearn.datasets import load_diabetes
from sklearn.linear_model import LinearRegression, RidgeCV
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

SEED = 42
N_FOLDS = 5
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from gewu.demo.truth_guard import assert_disjoint as _assert_disjoint  # noqa: E402


# --------------------------------------------------------------------------
# 指标
# --------------------------------------------------------------------------
def _rmse(y_true, y_pred) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float).ravel()
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def _mae(y_true, y_pred) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float).ravel()
    return float(np.mean(np.abs(y_true - y_pred)))


def _r2(y_true, y_pred) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float).ravel()
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


# --------------------------------------------------------------------------
# 数据
# --------------------------------------------------------------------------
def load_data():
    """返回 (X, y, provenance)。provenance 里带 CSV 的 sha256，供第三方核对。"""
    bunch = load_diabetes()
    X = np.asarray(bunch.data, dtype=float)
    y = np.asarray(bunch.target, dtype=float)

    csv_path = os.path.join(
        os.path.dirname(os.path.abspath(skds.__file__)), "data", "diabetes_data_raw.csv.gz",
    )
    digest = None
    if os.path.exists(csv_path):
        h = hashlib.sha256()
        with open(csv_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        digest = h.hexdigest()

    prov = {
        "dataset": "sklearn.datasets.load_diabetes (UCI Diabetes, Efron et al. 2004)",
        "n_samples": int(X.shape[0]),
        "n_features": int(X.shape[1]),
        "target_range": [float(y.min()), float(y.max())],
        "sklearn_version": SKLEARN_VERSION,
        "csv_sha256": digest,
        "network": "none (数据随 scikit-learn 分发包离线提供)",
    }
    return X, y, prov


# --------------------------------------------------------------------------
# 三个臂（全部与煤项目同族：线性 / 多项式+正则 / PLSR）
# --------------------------------------------------------------------------
def build_arms():
    return {
        # A. 线性基线：10 个基线指标直接回归
        "ols": lambda: make_pipeline(StandardScaler(), LinearRegression()),
        # B. 特征增广 + 强正则：二阶交互项后 RidgeCV（对应煤项目「增广 + 正则」的思路）
        "ridge_poly2": lambda: make_pipeline(
            StandardScaler(),
            PolynomialFeatures(degree=2, include_bias=False),
            StandardScaler(),
            RidgeCV(alphas=np.logspace(-3, 3, 25)),
        ),
        # C. PLSR：与煤项目 plsr_baseline 同一方法族，可直接对比「同族方法换领域后是否还成立」
        "pls": lambda: make_pipeline(StandardScaler(), PLSRegression(n_components=5, scale=False)),
    }


def cv_arm(build, X, y, folds):
    per_fold_rmse, per_fold_mae, per_fold_r2 = [], [], []
    preds = {}
    for k, (tr, te) in enumerate(folds):
        # 真值隔离硬检查：第二个领域同样跑同一套 guard，不是只在合成域演示一次。
        # KFold 本应天然不相交；这里断言的是「本应」不能替代「确实」。
        _assert_disjoint([str(i) for i in tr], [str(i) for i in te])
        model = build()
        model.fit(X[tr], y[tr])
        p = np.asarray(model.predict(X[te]), dtype=float).ravel()
        per_fold_rmse.append(_rmse(y[te], p))
        per_fold_mae.append(_mae(y[te], p))
        per_fold_r2.append(_r2(y[te], p))
        preds[str(k)] = {"y_true": y[te].round(6).tolist(), "y_pred": p.round(6).tolist()}
    return {
        "rmse_mean": float(np.mean(per_fold_rmse)),
        "rmse_std": float(np.std(per_fold_rmse, ddof=0)),
        "mae_mean": float(np.mean(per_fold_mae)),
        "mae_std": float(np.std(per_fold_mae, ddof=0)),
        "r2_mean": float(np.mean(per_fold_r2)),
        "r2_std": float(np.std(per_fold_r2, ddof=0)),
        "per_fold_rmse": [round(v, 4) for v in per_fold_rmse],
        "per_fold_r2": [round(v, 4) for v in per_fold_r2],
    }, preds


def run_once(seed: int = SEED, with_control: bool = True):
    X, y, prov = load_data()
    folds = list(KFold(n_splits=N_FOLDS, shuffle=True, random_state=seed).split(X))
    summary = {}
    predictions = {}
    for name, build in build_arms().items():
        m, p = cv_arm(build, X, y, folds)
        summary[name] = m
        predictions[name] = p

    # 负向对照：打乱目标后重跑最强臂。若流程有泄漏，R² 会明显 > 0。
    # 这不是「额外实验」，是给上面三个数字配一个「不该有信号时确实没有」的证伪。
    if with_control:
        rng = np.random.default_rng(seed)
        y_perm = y[rng.permutation(len(y))]
        m_perm, _ = cv_arm(build_arms()["ridge_poly2"], X, y_perm, folds)
        summary["negative_control_ridge_poly2_shuffled_y"] = {
            "rmse_mean": m_perm["rmse_mean"],
            "r2_mean": m_perm["r2_mean"],
            "note": "目标被打乱后 R² 应接近 0；明显为正说明流程有泄漏",
        }
    return {"seed": seed, "n_folds": N_FOLDS, "provenance": prov, "summary": summary,
            "predictions": predictions}


def _sha256_file(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit() -> str:
    import subprocess
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                             capture_output=True, text=True, timeout=10,
                             stdin=subprocess.DEVNULL)
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def main(argv=None):
    ap = argparse.ArgumentParser(description="第二个真实领域（临床表格回归）5 折复算")
    ap.add_argument("--json", action="store_true", help="只打印汇总 JSON（注册表重算读取这个）")
    ap.add_argument("--out", default="", help="落盘目录（写 summary.json 与 fold*/predictions.json）")
    ap.add_argument("--ledger", default="", help="把台账 JSON 写到该路径（含脚本/数据指纹与 commit）")
    ap.add_argument("--repeat", type=int, default=1, help="换 N 个种子看稳定性（不影响台账）")
    args = ap.parse_args(argv)

    t0 = time.time()
    runs = [run_once(seed=SEED + i) for i in range(max(1, args.repeat))]
    elapsed = time.time() - t0
    primary = runs[0]

    payload = {
        "schema_version": "1.0",
        "domain": "clinical-diabetes",
        "domain_label": "临床基线指标 → 疾病进展（UCI Diabetes, 表格回归）",
        "primary_seed": SEED,
        "n_folds": N_FOLDS,
        "wall_clock_s": round(elapsed, 2),
        "provenance": primary["provenance"],
        "summary": primary["summary"],
    }
    if args.repeat > 1:
        keys = ["ols", "ridge_poly2", "pls"]
        payload["seed_stability"] = {
            k: {
                "rmse_mean_over_seeds": round(float(np.mean([r["summary"][k]["rmse_mean"] for r in runs])), 4),
                "rmse_std_over_seeds": round(float(np.std([r["summary"][k]["rmse_mean"] for r in runs], ddof=0)), 4),
                "n_seeds": len(runs),
            }
            for k in keys
        }

    if args.ledger:
        ledger = dict(payload)
        ledger["evidence"] = {
            "script": os.path.relpath(os.path.abspath(__file__), REPO_ROOT).replace("\\", "/"),
            "script_sha256": _sha256_file(os.path.abspath(__file__)),
            "gewu_commit": _git_commit(),
            "generated_at_local": time.strftime("%Y-%m-%d %H:%M:%S"),
            "rerun": "python scripts/run_domain_diabetes.py --json",
            "caveat": "只验证机制泛化（注册/重算/溯源），不验证方法泛化；未在第二领域跑 7 阶段 LLM 链路",
        }
        os.makedirs(os.path.dirname(os.path.abspath(args.ledger)) or ".", exist_ok=True)
        with open(args.ledger, "w", encoding="utf-8") as f:
            json.dump(ledger, f, ensure_ascii=False, indent=2)

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        for arm, folds in primary["predictions"].items():
            d = os.path.join(args.out, arm)
            os.makedirs(d, exist_ok=True)
            for k, v in folds.items():
                with open(os.path.join(d, f"fold{k}.json"), "w", encoding="utf-8") as f:
                    json.dump(v, f, ensure_ascii=False)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    print(f"领域：{payload['domain_label']}")
    print(f"数据：{payload['provenance']['n_samples']} 样本 × "
          f"{payload['provenance']['n_features']} 特征，sklearn {payload['provenance']['sklearn_version']}")
    print(f"csv sha256：{payload['provenance']['csv_sha256']}")
    print(f"墙钟：{payload['wall_clock_s']} s（{N_FOLDS} 折 × 3 臂）\n")
    for name, m in payload["summary"].items():
        if name.startswith("negative_control"):
            continue
        print(f"  {name:<12} RMSE {m['rmse_mean']:.4f} ± {m['rmse_std']:.4f}   "
              f"MAE {m['mae_mean']:.4f}   R² {m['r2_mean']:.4f}   "
              f"折内 {[round(v, 2) for v in m['per_fold_rmse']]}")
    nc = payload["summary"].get("negative_control_ridge_poly2_shuffled_y")
    if nc:
        print(f"\n  负向对照（打乱目标）RMSE {nc['rmse_mean']:.4f}   R² {nc['r2_mean']:.4f}")
    if "seed_stability" in payload:
        print("\n  多种子稳定性：")
        for k, v in payload["seed_stability"].items():
            print(f"    {k:<12} RMSE {v['rmse_mean_over_seeds']:.4f} ± {v['rmse_std_over_seeds']:.4f}"
                  f"（{v['n_seeds']} 个种子）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
