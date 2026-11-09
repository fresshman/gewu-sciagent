#!/usr/bin/env python3
"""从真实 per-fold 预测值重算煤热值指标，并与实验注册表交叉校验。

用途
----
handoff_3/4/5 中的所有量化声明都必须可溯源。本脚本是那份溯源链的执行体：
读 COAL_PROJECT_ROOT 下 best_solution/fold*/predictions.json（真实推理落盘产物），
独立重算 RMSE / MAE / R²，再与 gewu/mcp/registry/coal_mil.json 的登记值比对。

不复制、不上传任何原始光谱或模型权重；只读取本机文件并输出聚合指标。

用法
----
  python scripts/recompute_coal_metrics.py                 # 打印校验表
  python scripts/recompute_coal_metrics.py --json out.json  # 另存 JSON 结果
  python scripts/recompute_coal_metrics.py --strict         # 校验不过则非零退出

退出码
------
  0 = 重算值与注册表在容差内一致
  1 = 存在超容差的不一致（或数据不可读）
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "gewu" / "mcp" / "registry" / "coal_mil.json"
ROOT_FILE = REPO / ".coal_project_root"

# 注册表登记的是「总体标准差」(ddof=0)；重算时两种都给，比对用总体值
TOL_RMSE = 0.01     # kcal/kg
TOL_MAE = 0.05      # kcal/kg
TOL_R2 = 1e-3
TOL_STD = 0.01


def coal_root() -> Path:
    """解析外部煤项目根：环境变量优先，其次 .coal_project_root 文件。"""
    import os
    env = os.environ.get("COAL_PROJECT_ROOT", "").strip()
    if env and Path(env).is_dir():
        return Path(env)
    if ROOT_FILE.is_file():
        p = Path(ROOT_FILE.read_text(encoding="utf-8").strip())
        if p.is_dir():
            return p
    raise SystemExit(f"[error] 无法解析 COAL_PROJECT_ROOT（已试环境变量与 {ROOT_FILE.name}）")


def _metrics(y: list[float], p: list[float]) -> dict[str, float]:
    n = len(y)
    err = [pi - yi for yi, pi in zip(y, p)]
    rmse = math.sqrt(sum(e * e for e in err) / n)
    mae = sum(abs(e) for e in err) / n
    ybar = sum(y) / n
    ss_res = sum(e * e for e in err)
    ss_tot = sum((yi - ybar) ** 2 for yi in y)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {"rmse": rmse, "mae": mae, "r2": r2, "n": n}


def _std(xs: list[float], ddof: int) -> float:
    n = len(xs)
    if n - ddof <= 0:
        return float("nan")
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - ddof))


def _paired_t(diffs: list[float]) -> dict[str, float]:
    """配对 t 检验（手算，避免强制依赖 scipy）。返回 t、df、双侧 p 近似。"""
    n = len(diffs)
    m = sum(diffs) / n
    sd = _std(diffs, 1)
    if sd == 0 or n < 2:
        return {"t": float("nan"), "df": n - 1, "p": float("nan"), "mean_diff": m, "sd_diff": sd}
    se = sd / math.sqrt(n)
    t = m / se
    p = _t_two_sided_p(abs(t), n - 1)
    return {"t": t, "df": n - 1, "p": p, "mean_diff": m, "sd_diff": sd, "se": se}


def _t_two_sided_p(t: float, df: int) -> float:
    """用不完全 Beta 函数算 t 分布双侧 p（无 scipy 依赖）。"""
    x = df / (df + t * t)
    # 正则化不完全 Beta I_x(df/2, 1/2) = 2 * (1 - CDF_t(|t|))
    return _betainc_reg(df / 2.0, 0.5, x)


def _betainc_reg(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a
    # 连分式（Lentz 法）
    tiny = 1e-30
    f, c, d = 1.0, 1.0, 0.0
    for i in range(0, 300):
        m = i // 2
        if i == 0:
            num = 1.0
        elif i % 2 == 0:
            num = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
        else:
            num = -((a + m) * (a + b + m) * x) / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1.0 + num * d
        d = tiny if abs(d) < tiny else d
        d = 1.0 / d
        c = 1.0 + num / c
        c = tiny if abs(c) < tiny else c
        f *= c * d
        if abs(1.0 - c * d) < 1e-12:
            break
    val = front * (f - 1.0)
    if x < (a + 1) / (a + b + 2):
        return val
    return 1.0 - _betainc_reg(b, a, 1 - x)


def load_registry() -> dict[str, dict[str, Any]]:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {e["id"]: e for e in data["experiments"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="重算煤热值指标并与注册表交叉校验")
    ap.add_argument("--json", dest="json_out", default="", help="把结果另存为 JSON")
    ap.add_argument("--strict", action="store_true", help="任一项超容差则以退出码 1 结束")
    args = ap.parse_args(argv)

    root = coal_root()
    sol = root / "coal-mil" / "outputs" / "best_solution"
    if not sol.is_dir():
        print(f"[error] 找不到 best_solution 目录: {sol}")
        return 1

    folds: list[dict[str, Any]] = []
    for f in range(5):
        pj = sol / f"fold{f}" / "predictions.json"
        if not pj.is_file():
            print(f"[error] 缺少 {pj}")
            return 1
        rows = json.loads(pj.read_text(encoding="utf-8"))
        y = [float(r["y_true"]) for r in rows]
        hy = [float(r["hybrid_pred"]) for r in rows]
        pl = [float(r["plsr_pred"]) for r in rows]
        mh, mp = _metrics(y, hy), _metrics(y, pl)
        folds.append({
            "fold": f,
            "n": mh["n"],
            "hybrid": {"rmse": mh["rmse"], "mae": mh["mae"], "r2": mh["r2"]},
            "plsr": {"rmse": mp["rmse"], "mae": mp["mae"], "r2": mp["r2"]},
            "delta_rmse": mh["rmse"] - mp["rmse"],
            "predictions_file": str(pj.relative_to(root)).replace("\\", "/"),
        })

    hs = [f["hybrid"]["rmse"] for f in folds]
    ps = [f["plsr"]["rmse"] for f in folds]
    diffs = [f["delta_rmse"] for f in folds]

    pooled_y: list[float] = []
    pooled_h: list[float] = []
    pooled_p: list[float] = []
    for f in range(5):
        rows = json.loads((sol / f"fold{f}" / "predictions.json").read_text(encoding="utf-8"))
        pooled_y += [float(r["y_true"]) for r in rows]
        pooled_h += [float(r["hybrid_pred"]) for r in rows]
        pooled_p += [float(r["plsr_pred"]) for r in rows]
    pooled = {"hybrid": _metrics(pooled_y, pooled_h), "plsr": _metrics(pooled_y, pooled_p)}

    summary = {
        "hybrid": {
            "mean_rmse": sum(hs) / len(hs),
            "std_rmse_pop": _std(hs, 0),
            "std_rmse_sample": _std(hs, 1),
            "mean_mae": sum(f["hybrid"]["mae"] for f in folds) / len(folds),
            "mean_r2": sum(f["hybrid"]["r2"] for f in folds) / len(folds),
        },
        "plsr": {
            "mean_rmse": sum(ps) / len(ps),
            "std_rmse_pop": _std(ps, 0),
            "std_rmse_sample": _std(ps, 1),
            "mean_mae": sum(f["plsr"]["mae"] for f in folds) / len(folds),
            "mean_r2": sum(f["plsr"]["r2"] for f in folds) / len(folds),
        },
        "paired_test": _paired_t(diffs),
        "pooled_oof": {
            "hybrid_rmse": pooled["hybrid"]["rmse"],
            "hybrid_r2": pooled["hybrid"]["r2"],
            "plsr_rmse": pooled["plsr"]["rmse"],
            "plsr_r2": pooled["plsr"]["r2"],
            "n_total": pooled["hybrid"]["n"],
        },
        "per_fold": folds,
        "source_root": str(root),
    }

    # ---- 与注册表交叉校验 ----
    reg = load_registry()
    oh = reg.get("our_hybrid", {}).get("metrics", {})
    ob = reg.get("plsr_baseline", {}).get("metrics", {})
    checks: list[dict[str, Any]] = []

    def chk(name: str, got: float, want: Any, tol: float) -> None:
        if want is None:
            checks.append({"item": name, "status": "SKIP", "got": got, "want": None})
            return
        diff = abs(got - float(want))
        checks.append({
            "item": name, "status": "PASS" if diff <= tol else "FAIL",
            "got": round(got, 6), "want": float(want), "abs_diff": round(diff, 8), "tol": tol,
        })

    chk("our_hybrid.rmse_kcal_mean", summary["hybrid"]["mean_rmse"], oh.get("rmse_kcal_mean"), TOL_RMSE)
    chk("our_hybrid.rmse_kcal_std", summary["hybrid"]["std_rmse_pop"], oh.get("rmse_kcal_std"), TOL_STD)
    chk("our_hybrid.mae_kcal_mean", summary["hybrid"]["mean_mae"], oh.get("mae_kcal_mean"), TOL_MAE)
    chk("our_hybrid.r2_mean", summary["hybrid"]["mean_r2"], oh.get("r2_mean"), TOL_R2)
    chk("plsr_baseline.rmse_kcal_mean", summary["plsr"]["mean_rmse"], ob.get("rmse_kcal_mean"), TOL_RMSE)
    chk("plsr_baseline.rmse_kcal_std", summary["plsr"]["std_rmse_pop"], ob.get("rmse_kcal_std"), TOL_STD)
    chk("plsr_baseline.r2_mean", summary["plsr"]["mean_r2"], ob.get("r2_mean"), TOL_R2)

    reg_pf = oh.get("per_fold_rmse_kcal") or []
    for i, v in enumerate(reg_pf):
        chk(f"our_hybrid.per_fold[{i}]", hs[i], v, TOL_RMSE)

    # MJ 换算一致性（1 kcal = 0.004184 MJ）
    mj = summary["hybrid"]["mean_rmse"] * 0.004184
    chk("our_hybrid.rmse_mj_mean(derived)", mj, oh.get("rmse_mj_mean"), 1e-3)

    summary["registry_cross_check"] = {
        "checks": checks,
        "n_pass": sum(1 for c in checks if c["status"] == "PASS"),
        "n_fail": sum(1 for c in checks if c["status"] == "FAIL"),
        "n_skip": sum(1 for c in checks if c["status"] == "SKIP"),
    }

    # ---- 输出 ----
    print("=" * 74)
    print("煤热值指标重算（真实 per-fold 预测值 → 聚合 → 注册表交叉校验）")
    print("=" * 74)
    print(f"数据源: {sol}")
    print()
    print(f"{'fold':<6}{'n':>3}  {'hybrid RMSE':>12}{'MAE':>10}{'R2':>8}   {'PLSR RMSE':>11}{'ΔRMSE':>10}")
    for f in folds:
        print(f"{f['fold']:<6}{f['n']:>3}  {f['hybrid']['rmse']:>12.4f}{f['hybrid']['mae']:>10.4f}"
              f"{f['hybrid']['r2']:>8.4f}   {f['plsr']['rmse']:>11.4f}{f['delta_rmse']:>10.4f}")
    print("-" * 74)
    print(f"{'mean':<6}{'':>3}  {summary['hybrid']['mean_rmse']:>12.4f}{summary['hybrid']['mean_mae']:>10.4f}"
          f"{summary['hybrid']['mean_r2']:>8.4f}   {summary['plsr']['mean_rmse']:>11.4f}"
          f"{summary['paired_test']['mean_diff']:>10.4f}")
    print(f"{'std':<6}{'':>3}  {summary['hybrid']['std_rmse_pop']:>12.4f}{'':>10}{'':>8}   "
          f"{summary['plsr']['std_rmse_pop']:>11.4f}")
    print()
    pt = summary["paired_test"]
    print(f"配对 t 检验: t({pt['df']})={pt['t']:.4f}, p={pt['p']:.4f}, "
          f"mean Δ={pt['mean_diff']:.4f} (sd={pt['sd_diff']:.4f})")
    po = summary["pooled_oof"]
    print(f"合并 OOF (n={po['n_total']}): hybrid RMSE={po['hybrid_rmse']:.4f} R²={po['hybrid_r2']:.4f} | "
          f"PLSR RMSE={po['plsr_rmse']:.4f} R²={po['plsr_r2']:.4f}")
    print()
    print("注册表交叉校验:")
    for c in checks:
        if c["status"] == "SKIP":
            continue
        mark = "PASS" if c["status"] == "PASS" else "FAIL"
        diff = c.get("abs_diff")
        extra = f" (|Δ|={diff})" if diff is not None else ""
        print(f"  [{mark}] {c['item']:<34} got={c['got']:<14} want={c['want']}{extra}")
    cc = summary["registry_cross_check"]
    print(f"  → {cc['n_pass']} passed, {cc['n_fail']} failed, {cc['n_skip']} skipped")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写出: {out}")

    if cc["n_fail"]:
        print("\n[FAIL] 存在超容差的不一致")
        return 1 if args.strict else 0
    print("\n[PASS] 重算值与注册表一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
