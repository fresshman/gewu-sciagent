#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把本机真实课题（MIL+LIBS 煤热值）的运行结果导出为 Web 右栏可读的 case bundle。

设计原则（与格物「路径引用 + 本地优先」一致）：
  * 源数据/模型一律按路径读取，仓库内不复制任何未发表的实验数据；
  * 产物落到 ``web/.local/case.json``（已在 .gitignore 中），**不入库**；
  * 未配置项目根（环境变量或 .coal_project_root）时输出 ``available:false``，
    Web 端降级为占位提示，不会把占位数字当成真实结果。

用法：
    python scripts/export_case_bundle.py                 # 自动发现项目根
    python scripts/export_case_bundle.py --root <路径>    # 显式指定
    python scripts/export_case_bundle.py --out <文件路径> # 自定义产物位置
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics as st
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "web" / ".local" / "case.json"

# 已通过反幻觉校验（arXiv / CrossRef / S2 / OpenAlex 任一命中）的公开文献。
# 这些是已发表论文的 DOI，属公开信息，可以进仓库。
VERIFIED_PAPERS = [
    {
        "title": "A temporal and spatial dual-dimension fusion spectra mapping method "
                 "for rapid detection of coal quality in laser-induced breakdown spectroscopy",
        "venue": "Talanta",
        "year": 2025,
        "doi": "10.1016/j.talanta.2025.128106",
        "status": "verified",
        "method": "crossref_title_fallback_from_s2",
        "note": "时空双维融合光谱映射；特征表示层工作",
    },
    {
        "title": "Methods for optimization of the original signal in laser induced breakdown spectroscopy",
        "venue": "Spectrochimica Acta Part B",
        "year": 2024,
        "doi": "10.1016/j.sab.2024.106982",
        "status": "verified",
        "method": "crossref_doi",
        "note": "LIBS 原始信号优化综述；信号层工作",
    },
    {
        "title": "Improving small-sample performance in portable LIBS analysis with "
                 "transfer learning and synthetic data-driven CNN models",
        "venue": "J. Anal. At. Spectrom.",
        "year": 2025,
        "doi": "10.1039/D5JA00490J",
        "status": "verified",
        "method": "crossref_doi",
        "note": "合成数据 + 迁移学习；数据层工作",
    },
]


def resolve_root(explicit: str | None = None) -> Path | None:
    """与 coal_infer.py 一致的发现顺序：显式参数 > 环境变量 > .coal_project_root。"""
    if explicit:
        return Path(explicit)
    env = os.environ.get("COAL_PROJECT_ROOT")
    if env:
        return Path(env)
    marker = REPO_ROOT / ".coal_project_root"
    if marker.is_file():
        txt = marker.read_text(encoding="utf-8").strip()
        if txt:
            return Path(txt.splitlines()[0].strip())
    return None


def metrics(y_true: list[float], y_pred: list[float]) -> dict:
    n = len(y_true)
    if n == 0:
        return {"n": 0, "rmse": None, "mae": None, "r2": None}
    mse = sum((a - b) ** 2 for a, b in zip(y_true, y_pred)) / n
    mae = sum(abs(a - b) for a, b in zip(y_true, y_pred)) / n
    mean_t = sum(y_true) / n
    sst = sum((a - mean_t) ** 2 for a in y_true) / n
    return {
        "n": n,
        "rmse": round(math.sqrt(mse), 2),
        "mae": round(mae, 2),
        "r2": round(1 - mse / sst, 4) if sst > 0 else None,
    }


def load_folds(mil_root: Path) -> list[list[dict]]:
    folds = []
    for f in range(5):
        p = mil_root / "outputs" / "best_solution" / f"fold{f}" / "predictions.json"
        if not p.is_file():
            break
        folds.append(json.loads(p.read_text(encoding="utf-8")))
    return folds


def build_metrics_block(folds: list[list[dict]]) -> dict:
    def series(key: str) -> tuple[list[dict], dict, list[float], list[float]]:
        per_fold, yt_all, yp_all = [], [], []
        for i, fold in enumerate(folds):
            yt = [float(d["y_true"]) for d in fold]
            yp = [float(d[key]) for d in fold]
            m = metrics(yt, yp)
            m["fold"] = i
            per_fold.append(m)
            yt_all += yt
            yp_all += yp
        pooled = metrics(yt_all, yp_all)
        pooled["n"] = len(yt_all)
        return per_fold, pooled, yt_all, yp_all

    hyb_folds, hyb_pool, yt, yh = series("hybrid_pred")
    pls_folds, pls_pool, _, yp = series("plsr_pred")

    def agg(per_fold: list[dict], field: str) -> dict:
        vals = [m[field] for m in per_fold if m[field] is not None]
        return {
            "mean": round(st.mean(vals), 4),
            # ddof=0 总体标准差，与论文口径一致；summary.txt 里的 20.07 是 ddof=1
            "std": round(st.pstdev(vals), 4),
            "std_sample": round(st.stdev(vals), 4) if len(vals) > 1 else 0.0,
        }

    return {
        "convention": "5 折交叉验证；逐折指标为折内 bag 的 RMSE/MAE/R²，汇总为折均值 ± 总体标准差(ddof=0)",
        "hybrid": {
            "per_fold": hyb_folds,
            "summary": {k: agg(hyb_folds, k) for k in ("rmse", "mae", "r2")},
            "pooled": hyb_pool,
        },
        "plsr_baseline": {
            "per_fold": pls_folds,
            "summary": {k: agg(pls_folds, k) for k in ("rmse", "mae", "r2")},
            "pooled": pls_pool,
        },
        "improvement_pct": round(
            100 * (pls_pool["rmse"] - hyb_pool["rmse"]) / pls_pool["rmse"], 2
        ),
        "scatter": {
            "y_true": [round(v, 1) for v in yt],
            "hybrid": [round(v, 1) for v in yh],
            "plsr": [round(v, 1) for v in yp],
            "unit": "kcal/kg",
        },
    }


def parse_spectrum(csv_path: Path) -> tuple[list[float], list[float]]:
    """解析单条 LIBS 光谱 CSV（格式见 coal-mil/src/data/libs_parser.py）。"""
    wl, inten = [], []
    with csv_path.open("r", encoding="utf-8", errors="ignore") as fh:
        for i, line in enumerate(fh):
            if i < 5:
                continue
            parts = line.strip().split(",")
            if len(parts) < 2:
                continue
            try:
                wl.append(float(parts[0]))
                inten.append(float(parts[1]))
            except ValueError:
                continue
    return wl, inten


def find_bag_dir(data_root: Path, bag_id: str) -> Path | None:
    for split in ("训练集", "测试集"):
        base = data_root / split
        if not base.is_dir():
            continue
        for mine_dir in base.iterdir():
            if not mine_dir.is_dir():
                continue
            cand = mine_dir / bag_id
            if cand.is_dir():
                return cand
    return None


def build_spectrum(data_root: Path, bag_id: str, max_points: int = 360) -> dict | None:
    bag_dir = find_bag_dir(data_root, bag_id)
    if bag_dir is None:
        return None
    csvs = sorted([p for p in bag_dir.iterdir() if p.suffix.lower() in (".csv", ".txt")])
    if not csvs:
        return None
    wl, inten = parse_spectrum(csvs[0])
    if len(wl) < 10:
        return None
    step = max(1, len(wl) // max_points)
    wl_s = wl[::step]
    inten_s = inten[::step]
    return {
        "bag_id": bag_id,
        "shot": csvs[0].name,
        "n_shots": len(csvs),
        "n_raw": len(wl),
        "n_points": len(wl_s),
        "wl_range": [round(wl[0], 2), round(wl[-1], 2)],
        "wavelength": [round(v, 2) for v in wl_s],
        "intensity": [round(v, 1) for v in inten_s],
        "note": "单条击打原始光谱（未做 sg/als/mms 预处理），已等间隔抽样用于预览",
    }


def build_artifacts(root: Path) -> list[dict]:
    """列出阶段产出物（只登记相对路径与体积，不含任何实验数值）。"""
    out: list[dict] = []
    paper_dir = root / "gewu_paper"
    if paper_dir.is_dir():
        for p in sorted(paper_dir.rglob("*")):
            if p.is_file():
                out.append(
                    {
                        "name": p.name,
                        "rel": str(p.relative_to(root)).replace("\\", "/"),
                        "kind": "figure" if p.parent.name == "figures" else p.suffix.lstrip("."),
                        "size_kb": round(p.stat().st_size / 1024, 1),
                    }
                )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="导出格物 Web 右栏的真实案例数据")
    ap.add_argument("--root", default=None, help="外部课题根目录（不指定则自动发现）")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="产物路径")
    args = ap.parse_args()

    out_path = Path(args.out)
    root = resolve_root(args.root)
    if root is None or not root.is_dir():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {
                    "available": False,
                    "reason": "未发现外部课题根目录（设置 COAL_PROJECT_ROOT 或写入 .coal_project_root）",
                    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"[case-bundle] available=false -> {out_path}")
        return 0

    mil_root = root / "coal-mil"
    folds = load_folds(mil_root)
    if not folds:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {
                    "available": False,
                    "reason": f"未在 {mil_root} 下找到 best_solution/fold*/predictions.json",
                    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"[case-bundle] available=false -> {out_path}")
        return 0

    data_root = root / "data" / "赛题数据划分"
    first_bag = folds[0][0]["bag_id"] if folds and folds[0] else ""
    spectrum = build_spectrum(data_root, first_bag) if data_root.is_dir() else None

    bundle = {
        "available": True,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "topic": "LIBS 大颗粒原煤热值预测（PLSR-MIL 残差混合）",
        "metrics": build_metrics_block(folds),
        "spectrum": spectrum,
        "papers": VERIFIED_PAPERS,
        "artifacts": build_artifacts(root),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[case-bundle] available=true -> {out_path}")
    print(f"             folds={len(folds)} spectrum={'yes' if spectrum else 'no'} "
          f"papers={len(VERIFIED_PAPERS)} artifacts={len(bundle['artifacts'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
