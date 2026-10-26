"""格物 × 煤热值 MIL 真实推理胶水层。

设计原则（重要）：
    本文件**只含代码，不含任何模型权重、训练数据或实验结果**。
    用户未发表的 MIL+LIBS 论文项目（coal-calorific-value）通过
    ``COAL_PROJECT_ROOT`` 环境变量在**运行时**按路径引用读取，
    模型/数据始终留在用户本机原始目录，不复制、不入库、不上云。

推理链严格对齐 ``coal-mil/scripts/save_best_solution.py::run_single_fold``：
    hybrid_pred(kcal/kg) = PLSR(bag_mean_spectrum) + MIL_residual
    MIL_residual = model.predict(X, mask, plsr_scores) * res_std + res_mean
    MJ/kg = kcal/kg * 0.004184

CLI（输出 JSON 到 stdout）：
    python coal_infer.py list-bags   --fold 0
    python coal_infer.py predict-bag --bag-dir <bag目录> [--fold 0]
    python coal_infer.py predict-fold --fold 0
    python coal_infer.py cv-summary
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import pickle
import sys
import tempfile
from typing import Any

import numpy as np

# --------------------------------------------------------------------------
# 外部项目定位（运行时引用，不入库）
# --------------------------------------------------------------------------
# 仓库内不写死任何机器绝对路径。按以下优先级发现外部项目根目录：
#   1) 环境变量 COAL_PROJECT_ROOT
#   2) 格物项目根的 .coal_project_root 文本文件（已 gitignore，本机私有）
_ROOT_HINT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".coal_project_root",
)


def _resolve_project_root() -> str:
    env = os.environ.get("COAL_PROJECT_ROOT", "").strip()
    if env:
        return env.rstrip("/\\")
    if os.path.exists(_ROOT_HINT_FILE):
        with open(_ROOT_HINT_FILE, "r", encoding="utf-8") as f:
            v = f.read().strip()
        if v:
            return v.rstrip("/\\")
    return ""


PROJECT_ROOT = _resolve_project_root()
COAL_MIL = os.path.join(PROJECT_ROOT, "coal-mil")
SRC_DIR = os.path.join(COAL_MIL, "src")
SCRIPTS_DIR = os.path.join(COAL_MIL, "scripts")
DATA_SPLIT_DIR = os.path.join(PROJECT_ROOT, "data", "赛题数据划分")
TRAIN_DIR = os.path.join(DATA_SPLIT_DIR, "训练集")
LABEL_DIR = os.path.join(DATA_SPLIT_DIR, "训练集标签")
BEST_SOLUTION_DIR = os.path.join(COAL_MIL, "outputs", "best_solution")

# 与 save_best_solution.py 严格一致
STEPS = ["sg", "als", "mms"]
N_COMP = 7
N_FOLDS = 5
SEED = 42
KCAL_TO_MJ = 0.004184

# 模型重建超参（save_best_solution.build_mil_regressor 调用实参的镜像）
MODEL_BUILD_KW = dict(
    encoder_name="resnet1d",
    se=False,
    pool_name="transmil_attn",
    gated=False,
    dropout=0.3,
    base=16,
    lr=3e-4,
    weight_decay=0.02,
    loss_type="huber",
    huber_delta=1.0,
    lse_beta=0.5,
    plsr_dim=N_COMP,
    fusion_mode="film",
)


class ProjectNotFound(RuntimeError):
    pass


def _require_project() -> None:
    """确认外部项目存在且结构完整；缺失时给出可操作提示。"""
    if not PROJECT_ROOT:
        raise ProjectNotFound(
            "未配置煤热值项目根目录。请任选其一：\n"
            "  1) 设置环境变量 COAL_PROJECT_ROOT 指向 coal-calorific-value 项目根；\n"
            f"  2) 在格物项目根写入 {os.path.basename(_ROOT_HINT_FILE)} 文件，"
            "内容为该项目的绝对路径（此文件已 gitignore，不会入库）。\n"
            "注意：模型权重与未发表实验数据始终留在原项目，格物只按路径读取。"
        )
    missing = [p for p in (COAL_MIL, SRC_DIR, BEST_SOLUTION_DIR) if not os.path.isdir(p)]
    if missing:
        raise ProjectNotFound(
            f"煤热值项目不可用，缺失路径: {missing}\n"
            f"当前 COAL_PROJECT_ROOT={PROJECT_ROOT}\n"
            f"请设置环境变量 COAL_PROJECT_ROOT 指向 coal-calorific-value 项目根目录。"
        )


def _import_project_modules():
    """把用户项目的 src/ 临时加入 sys.path 并复用其真实实现。

    复用而非重写，保证与训练时的数据解析/预处理/模型结构完全一致。
    """
    _require_project()
    # `from src.data...` 要求 src 的**父目录**（coal-mil）在 sys.path 上
    for p in (COAL_MIL, SCRIPTS_DIR):
        if p not in sys.path:
            sys.path.insert(0, p)
    from src.data.libs_parser import scan_bags, parse_libs_csv, kfold_split_bags  # noqa: E402
    from src.data.preprocess import (  # noqa: E402
        build_preprocess_pipeline, apply_preprocess, is_valid_spectrum,
    )
    from src.models import build_mil_regressor  # noqa: E402

    return {
        "scan_bags": scan_bags,
        "parse_libs_csv": parse_libs_csv,
        "kfold_split_bags": kfold_split_bags,
        "build_preprocess_pipeline": build_preprocess_pipeline,
        "apply_preprocess": apply_preprocess,
        "is_valid_spectrum": is_valid_spectrum,
        "build_mil_regressor": build_mil_regressor,
    }


# --------------------------------------------------------------------------
# 数据准备（严格复刻 save_best_solution.FusionBagDataset / load_bag_mean）
# --------------------------------------------------------------------------
def load_bags_with_labels(mods) -> list:
    bags = mods["scan_bags"](TRAIN_DIR, LABEL_DIR)
    return [b for b in bags if b.label is not None]


def bag_to_arrays(mods, bag, spec_len: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """把一个 bag 解析为 (实例矩阵 (K,L), 袋均谱 (L,))。

    与训练时字节级一致：CSV 解析 → 有效性过滤 → sg/als/mms → 统一裁剪 → 袋均。
    """
    pipeline = mods["build_preprocess_pipeline"](STEPS)
    specs = []
    for p in bag.spec_paths:
        _, intensity, _ = mods["parse_libs_csv"](p)
        if not mods["is_valid_spectrum"](intensity):
            continue
        specs.append(intensity)
    if not specs:
        raise ValueError(f"bag {bag.bag_id} 无有效光谱")
    processed = [mods["apply_preprocess"](s.astype(np.float64), pipeline) for s in specs]
    sl = min(len(p) for p in processed)
    if spec_len is not None:
        sl = min(sl, spec_len)
    uniform = np.stack([p[:sl] for p in processed], axis=0).astype(np.float32)
    return uniform, uniform.mean(axis=0)


def _spec_len_cache_path(fold: int) -> str:
    key = hashlib.md5(f"{PROJECT_ROOT}|{fold}".encode("utf-8")).hexdigest()[:12]
    d = os.path.join(tempfile.gettempdir(), "gewu_coal_cache")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"spec_len_fold{fold}_{key}.json")


def train_spec_len(mods, fold: int) -> int:
    """复现训练集的 spec_len（训练时用它裁剪验证集），带磁盘缓存。"""
    cache = _spec_len_cache_path(fold)
    if os.path.exists(cache):
        with open(cache, "r", encoding="utf-8") as f:
            return int(json.load(f)["spec_len"])

    bags = load_bags_with_labels(mods)
    tr, _ = mods["kfold_split_bags"](bags, fold=fold, n_folds=N_FOLDS, seed=SEED)
    pipeline = mods["build_preprocess_pipeline"](STEPS)
    sl_all = []
    for bag in tr:
        specs = []
        for p in bag.spec_paths:
            _, intensity, _ = mods["parse_libs_csv"](p)
            if not mods["is_valid_spectrum"](intensity):
                continue
            specs.append(mods["apply_preprocess"](intensity.astype(np.float64), pipeline))
        if specs:
            sl_all.append(min(len(s) for s in specs))
    spec_len = int(min(sl_all))
    with open(cache, "w", encoding="utf-8") as f:
        json.dump({"spec_len": spec_len, "fold": fold}, f)
    return spec_len


# --------------------------------------------------------------------------
# 模型加载
# --------------------------------------------------------------------------
def load_fold_artifacts(mods, fold: int):
    """加载第 fold 折的 MIL 模型 + PLSR + 残差归一化统计量。"""
    import torch

    fold_dir = os.path.join(BEST_SOLUTION_DIR, f"fold{fold}")
    model_path = os.path.join(fold_dir, "model.pt")
    plsr_path = os.path.join(fold_dir, "plsr.pkl")
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"模型权重不存在: {model_path}")
    if not os.path.exists(plsr_path):
        raise FileNotFoundError(f"PLSR 模型不存在: {plsr_path}")

    try:
        ckpt = torch.load(model_path, map_location="cpu", weights_only=True)
    except Exception:
        # 兼容含非 tensor 自定义对象的旧 checkpoint
        ckpt = torch.load(model_path, map_location="cpu", weights_only=False)

    model, _ = mods["build_mil_regressor"](**MODEL_BUILD_KW)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()

    with open(plsr_path, "rb") as f:
        plsr = pickle.load(f)

    res_mean = float(ckpt["res_mean"])
    res_std = float(ckpt["res_std"])
    return model, plsr, res_mean, res_std, ckpt.get("config", {}), fold_dir


def _predict_one(model, plsr, res_mean, res_std, uniform: np.ndarray, bag_mean: np.ndarray):
    import torch

    X = torch.from_numpy(uniform[:, np.newaxis, :])            # (K,1,L)
    Xb = X.unsqueeze(0)                                        # (1,K,1,L)
    mask = torch.ones((1, uniform.shape[0]), dtype=torch.float32)
    scores = torch.from_numpy(plsr.transform(bag_mean[None, :]).astype(np.float32))
    with torch.no_grad():
        y_norm = model.predict(Xb, mask, plsr_scores=scores)
    mil_res = float((y_norm * res_std + res_mean).cpu().numpy().ravel()[0])
    plsr_pred = float(np.asarray(plsr.predict(bag_mean[None, :])).ravel()[0])
    hybrid = plsr_pred + mil_res
    return plsr_pred, mil_res, hybrid


# --------------------------------------------------------------------------
# 对外能力
# --------------------------------------------------------------------------
def list_bags(fold: int) -> dict:
    mods = _import_project_modules()
    bags = load_bags_with_labels(mods)
    _, va = mods["kfold_split_bags"](bags, fold=fold, n_folds=N_FOLDS, seed=SEED)
    return {
        "fold": fold,
        "n_total_bags": len(bags),
        "n_val_bags": len(va),
        "val_bags": [
            {
                "bag_id": b.bag_id,
                "mine": b.mine,
                # 可直接传给 predict-bag 的目录路径
                "bag_dir": os.path.dirname(b.spec_paths[0]),
                "n_spectra": len(b.spec_paths),
                "y_true_kcal_kg": float(b.label),
            }
            for b in va
        ],
        "project_root": PROJECT_ROOT,
    }


def predict_bag(bag_dir: str, fold: int = 0, spec_len: int | None = None) -> dict:
    """对单个 bag（一个目录下多张 LIBS 谱 CSV）预测热值。"""
    mods = _import_project_modules()
    if not os.path.isdir(bag_dir):
        raise FileNotFoundError(f"bag 目录不存在: {bag_dir}")

    csvs = sorted(glob.glob(os.path.join(bag_dir, "*.csv")))
    if not csvs:
        raise ValueError(f"目录下无 CSV 光谱: {bag_dir}")

    class _Bag:  # 复用 bag_to_arrays 所需的最小接口
        bag_id = os.path.basename(bag_dir.rstrip("/\\"))
        spec_paths = csvs

    if spec_len is None:
        try:
            spec_len = train_spec_len(mods, fold)
        except Exception:
            spec_len = None

    uniform, bag_mean = bag_to_arrays(mods, _Bag(), spec_len=spec_len)
    model, plsr, res_mean, res_std, cfg, fold_dir = load_fold_artifacts(mods, fold)
    plsr_pred, mil_res, hybrid = _predict_one(
        model, plsr, res_mean, res_std, uniform, bag_mean
    )
    return {
        "bag_id": _Bag.bag_id,
        "fold": fold,
        "n_instances": int(uniform.shape[0]),
        "spec_len": int(uniform.shape[1]),
        "plsr_pred_kcal_kg": round(plsr_pred, 4),
        "mil_residual_kcal_kg": round(mil_res, 4),
        "hybrid_pred_kcal_kg": round(hybrid, 4),
        "hybrid_pred_MJ_kg": round(hybrid * KCAL_TO_MJ, 4),
        "model_config": cfg,
        "fold_dir": fold_dir,
        "status": "real-inference",
    }


def predict_fold(fold: int) -> dict:
    """复现第 fold 折验证集全部预测（用于与 predictions.json 逐条对照校验）。"""
    mods = _import_project_modules()
    bags = load_bags_with_labels(mods)
    _, va = mods["kfold_split_bags"](bags, fold=fold, n_folds=N_FOLDS, seed=SEED)
    spec_len = train_spec_len(mods, fold)
    model, plsr, res_mean, res_std, cfg, fold_dir = load_fold_artifacts(mods, fold)

    preds = []
    for bag in va:
        try:
            uniform, bag_mean = bag_to_arrays(mods, bag, spec_len=spec_len)
        except ValueError:
            continue
        plsr_pred, mil_res, hybrid = _predict_one(
            model, plsr, res_mean, res_std, uniform, bag_mean
        )
        preds.append({
            "bag_id": bag.bag_id,
            "y_true": float(bag.label),
            "plsr_pred": plsr_pred,
            "mil_res_pred": mil_res,
            "hybrid_pred": hybrid,
        })

    y_true = np.array([p["y_true"] for p in preds])
    y_pred = np.array([p["hybrid_pred"] for p in preds])
    rmse = float(np.sqrt(np.mean((y_pred - y_true) ** 2)))
    mae = float(np.mean(np.abs(y_pred - y_true)))
    ss_res = float(np.sum((y_pred - y_true) ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else None

    return {
        "fold": fold,
        "n_val_bags": len(preds),
        "spec_len": spec_len,
        "rmse_kcal_kg": round(rmse, 4),
        "mae_kcal_kg": round(mae, 4),
        "r2": round(r2, 4) if r2 is not None else None,
        "model_config": cfg,
        "predictions": preds,
        "status": "real-inference",
    }


def cv_summary() -> dict:
    """汇总 5 折指标：从各折 predictions.json 复算，并与 summary.json 交叉校验。"""
    summary_path = os.path.join(BEST_SOLUTION_DIR, "summary.json")
    per_fold, recomputed = [], []
    for fold in range(N_FOLDS):
        p = os.path.join(BEST_SOLUTION_DIR, f"fold{fold}", "predictions.json")
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8") as f:
            recs = json.load(f)
        y = np.array([r["y_true"] for r in recs])
        h = np.array([r["hybrid_pred"] for r in recs])
        p_ = np.array([r["plsr_pred"] for r in recs])
        recomputed.append({
            "fold": fold,
            "n": len(recs),
            "hybrid_rmse": round(float(np.sqrt(np.mean((h - y) ** 2))), 4),
            "plsr_rmse": round(float(np.sqrt(np.mean((p_ - y) ** 2))), 4),
        })

    out: dict[str, Any] = {
        "project_root": PROJECT_ROOT,
        "n_folds": len(recomputed),
        "per_fold": recomputed,
    }
    if recomputed:
        vals = [r["hybrid_rmse"] for r in recomputed]
        out["mean_rmse_kcal_kg"] = round(float(np.mean(vals)), 4)
        out["std_rmse_kcal_kg"] = round(float(np.std(vals)), 4)
        out["mean_rmse_MJ_kg"] = round(float(np.mean(vals)) * KCAL_TO_MJ, 4)

    if os.path.exists(summary_path):
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
        out["official_summary"] = {
            "method": summary.get("method"),
            "encoder": summary.get("encoder"),
            "fusion": summary.get("fusion"),
            "mean_rmse": summary.get("mean_rmse"),
            "std_rmse": summary.get("std_rmse"),
            "mean_plsr_rmse": summary.get("mean_plsr_rmse"),
            "n_total_params": summary.get("n_total_params"),
        }
        if recomputed:
            off = summary.get("mean_rmse")
            out["cross_check"] = {
                "official_mean_rmse": round(float(off), 4) if off is not None else None,
                "recomputed_mean_rmse": out["mean_rmse_kcal_kg"],
                "abs_diff": round(abs(float(off) - out["mean_rmse_kcal_kg"]), 6)
                if off is not None else None,
            }
    return out



def main() -> None:
    ap = argparse.ArgumentParser(description="格物 × 煤热值 MIL 真实推理胶水层")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("list-bags", help="列出某折验证集 bag")
    p1.add_argument("--fold", type=int, default=0)

    p2 = sub.add_parser("predict-bag", help="预测单个 bag 热值")
    p2.add_argument("--bag-dir", required=True)
    p2.add_argument("--fold", type=int, default=0)

    p3 = sub.add_parser("predict-fold", help="复现某折验证集全部预测")
    p3.add_argument("--fold", type=int, default=0)

    sub.add_parser("cv-summary", help="5 折指标汇总与交叉校验")

    args = ap.parse_args()
    try:
        if args.cmd == "list-bags":
            res = list_bags(args.fold)
        elif args.cmd == "predict-bag":
            res = predict_bag(args.bag_dir, args.fold)
        elif args.cmd == "predict-fold":
            res = predict_fold(args.fold)
        elif args.cmd == "cv-summary":
            res = cv_summary()
    except (ProjectNotFound, FileNotFoundError, ValueError) as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(2)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
