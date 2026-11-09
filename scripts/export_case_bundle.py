#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把本机真实课题（MIL+LIBS 煤热值）的运行结果导出为 Web 右栏可读的 case bundle。

设计原则（与格物「路径引用 + 本地优先 + 单一真源」一致）：
  * 源数据/模型一律按路径读取，仓库内不复制任何未发表的实验数据；
  * 指标**不自己重新发明口径**：优先读 ``output/documents/coal_report/metrics_recomputed.json``
    （由 ``scripts/recompute_coal_metrics.py`` 从逐折 predictions.json 重算并与注册表交叉校验），
    该文件缺失时才回退到本地重算，且全程不在中间步骤舍入；
  * 同时给出两种口径并在 bundle 里写明——「逐折均值」（论文口径）与「合并 OOF」（池化口径），
    避免 UI 与论文出现同一指标的互相矛盾的数字；
  * 产物落到 ``web/.local/case.json``（已在 .gitignore 中），**不入库**；
  * 未配置项目根（环境变量或 .coal_project_root）时输出 ``available:false``，
    Web 端降级为占位提示，不会把占位数字当成真实结果。

用法：
    python scripts/export_case_bundle.py                 # 自动发现项目根
    python scripts/export_case_bundle.py --root <路径>    # 显式指定
    python scripts/export_case_bundle.py --out <文件路径> # 自定义产物位置
    python scripts/export_case_bundle.py --check         # 只做一致性校验，不写文件
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

REPORT_DIR = REPO_ROOT / "output" / "documents" / "coal_report"
TRUTH_FILE = REPORT_DIR / "metrics_recomputed.json"
# 本机存档按设计不入库（未发表数据）。若无存档但有入库副本，仍应能解析文献区，
# 否则评委 clone 后右栏文献是空的——这不是「降级」，是缺陷。
TEX_FALLBACK = REPO_ROOT / "docs" / "paper" / "coal_report" / "main.tex"
REFS_FALLBACK = REPO_ROOT / "docs" / "verification" / "refs_verified.json"
TEX_FILE = REPORT_DIR / "main.tex"
REFS_FILE = REPORT_DIR / "refs_verified.json"
REGISTRY_FILE = REPO_ROOT / "gewu" / "mcp" / "registry" / "coal_mil.json"


def _existing(*paths: Path) -> Path:
    """取第一个存在的路径；都不存在时返回第一个，由调用方按 ``is_file()`` 判定缺失。"""
    for p in paths:
        if p.is_file():
            return p
    return paths[0]

# 仓库内脱敏快照：只含**聚合指标**（与论文正文同口径的公开数字），
# 不含原始光谱、模型权重、逐样本预测。用于评委机没有外部课题时，
# 右栏仍能看到真实口径的数字与结构，且来源标注清楚（绝不冒充本机重算）。
REPO_SNAPSHOT = REPO_ROOT / "docs" / "verification" / "case_snapshot.json"

# 消融系列的口径警示：这些实验与最终配置**不同组**，数值不可直接相减。
ABLATION_CAVEAT = (
    "消融系列为「MSE loss、无 SupCon、无 FiLM」阶段的结果，与最终配置"
    "（huber + SupCon + FiLM，RMSE 214.57）不同组，两者数值不可相减。"
    "该系列只用于比较组内相对优劣。"
)

# 组件级消融（2026-11-09）是**第三组**：基准就是最终配置本身（本机 CPU 重训 215.75），
# 与上面那组（基准 347.55）和存档 214.57 都不同源，三组之间一律不可相减。
COMPONENT_ABLATION_CAVEAT = (
    "组件级消融的基准为最终配置本机 CPU 重训（215.75 ± 34.59），"
    "与存档 214.57 非同一进程产出，也与上面「MSE 阶段」那组（基准 347.55）不同源；"
    "三组数值互不可相减。三个组件均**未检出**（p=0.29/0.39/0.58，95% CI 全部跨 0，"
    "5 折方向不一致），故只报方向、不作有效性声明。"
)

# 仓库内需要登记为「阶段产出物」的文件（相对仓库根）。
ARTIFACT_GLOBS = [
    ("output/documents/coal_report", ("*.tex", "*.json")),
    ("output/verification", ("*.json",)),
    ("openclaw/workspace/agents/gewu-improver", ("handoff_4*.json",)),
    ("openclaw/workspace/agents/gewu-writer", ("handoff_5*.json",)),
    ("openclaw/workspace/agents/gewu-publication", ("handoff_6*.json",)),
    ("openclaw/workspace/agents/gewu-distillation", ("handoff_7*.json",)),
    ("openclaw/workspace/agents/gewu-distillation/skills/mil-libs-coal", ("SKILL.md",)),
    ("reports", ("*journal-match*.html", "*journal-match*.json")),
    ("scripts", ("recompute_coal_metrics.py", "e2e_smoke_test.py", "export_case_bundle.py")),
]


# --------------------------------------------------------------------------- #
# 项目根发现
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# 指标：全精度计算，只在写出时舍入
# --------------------------------------------------------------------------- #
def _raw_metrics(y_true: list[float], y_pred: list[float]) -> dict:
    """全精度计算，不做任何 round（避免「先舍入再平均」的链路误差）。"""
    n = len(y_true)
    if n == 0:
        return {"n": 0, "rmse": None, "mae": None, "r2": None}
    mse = sum((a - b) ** 2 for a, b in zip(y_true, y_pred)) / n
    mae = sum(abs(a - b) for a, b in zip(y_true, y_pred)) / n
    mean_t = sum(y_true) / n
    sst = sum((a - mean_t) ** 2 for a in y_true) / n
    return {
        "n": n,
        "rmse": math.sqrt(mse),
        "mae": mae,
        "r2": (1 - mse / sst) if sst > 0 else None,
    }


def load_folds(mil_root: Path) -> list[list[dict]]:
    folds = []
    for f in range(5):
        p = mil_root / "outputs" / "best_solution" / f"fold{f}" / "predictions.json"
        if not p.is_file():
            break
        folds.append(json.loads(p.read_text(encoding="utf-8")))
    return folds


def _t_sf(t: float, df: int) -> float | None:
    """t 分布上尾概率（无 scipy 时的兜底，不完全 beta 连分式）。"""
    if df <= 0 or not math.isfinite(t):
        return None
    x = df / (df + t * t)
    p = _betainc(df / 2.0, 0.5, x)  # 双尾 p
    return p


def _betainc(a: float, b: float, x: float) -> float | None:
    """正则化不完全 beta I_x(a,b)，Lentz 连分式（数值稳定版）。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1 - x) / b


def _betacf(a: float, b: float, x: float, itmax: int = 200, eps: float = 3e-12) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < eps:
            break
    return h


def _paired_test(hyb: list[float], pls: list[float]) -> dict:
    """逐折配对 t 检验 + 95% CI（df=4 用 t 临界值，避免强依赖 scipy）。"""
    n = len(hyb)
    if n < 2:
        return {"available": False, "reason": "折数不足"}
    d = [a - b for a, b in zip(hyb, pls)]
    mean_d = sum(d) / n
    sd = st.stdev(d)
    se = sd / math.sqrt(n)
    t = mean_d / se if se else None
    df = n - 1
    p = None
    if t is not None:
        try:  # 优先用 scipy（若环境有），与重算脚本口径保持完全一致
            from scipy import stats  # type: ignore

            p = float(stats.ttest_rel(hyb, pls).pvalue)
            tcrit = float(stats.t.ppf(0.975, df))
            try:
                wil = float(stats.wilcoxon(hyb, pls).pvalue)
            except ValueError:
                wil = None
        except Exception:
            p = _t_sf(t, df)
            tcrit = 2.776 if df == 4 else 2.0
            wil = None
    else:
        tcrit, wil = 2.0, None
    return {
        "available": t is not None and p is not None,
        "test": "paired t-test（逐折 RMSE，双侧）",
        "t": round(t, 4) if t is not None else None,
        "df": df,
        "p": round(p, 4) if p is not None else None,
        "mean_diff": round(mean_d, 4),
        "ci95": [round(mean_d - tcrit * se, 2), round(mean_d + tcrit * se, 2)],
        "wilcoxon_p": round(wil, 4) if wil is not None else None,
        "note": (
            f"n={n} 折；配对 t 检验在 α=0.05 下显著，但 Wilcoxon 在 n=5 时最小可达 p≈0.0625，"
            "无法达到 0.05，故符号检验不显著——两个结论应同时报告，不能只取其一。"
        ),
    }


def metrics_from_predictions(folds: list[list[dict]]) -> dict:
    """从逐折 predictions.json 全精度重算（真源缺失时的回退路径）。

    输出结构与 ``_normalise_truth`` 一致，便于下游统一消费。
    """
    per_fold = []
    yt_all, yh_all, yp_all = [], [], []
    for i, fold in enumerate(folds):
        yt = [float(d["y_true"]) for d in fold]
        yh = [float(d["hybrid_pred"]) for d in fold]
        yp = [float(d["plsr_pred"]) for d in fold]
        mh, mp = _raw_metrics(yt, yh), _raw_metrics(yt, yp)
        per_fold.append(
            {
                "fold": i,
                "n": len(yt),
                "hybrid": mh,
                "plsr": mp,
                "delta_rmse": (mh["rmse"] - mp["rmse"]) if mh["rmse"] and mp["rmse"] else None,
            }
        )
        yt_all += yt
        yh_all += yh
        yp_all += yp

    pooled_h = _raw_metrics(yt_all, yh_all)
    pooled_p = _raw_metrics(yt_all, yp_all)
    return {
        "hybrid": {"per_fold": per_fold, "pooled": pooled_h},
        "plsr": {"per_fold": per_fold, "pooled": pooled_p},
        "scatter": {"y_true": yt_all, "hybrid": yh_all, "plsr": yp_all, "unit": "kcal/kg"},
        "_source": "recomputed_from_predictions",
    }


def _load_json_truth(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not {"hybrid", "plsr", "per_fold"} <= set(raw):
        return None
    return raw


def load_truth(mil_root: Path | None, require_truth: bool = False) -> tuple[dict, str, str]:
    """按「本机真源 → 本机重算 → 仓库快照」三级取数。

    返回 ``(truth, 来源路径, mode)``；mode ∈ {local_recompute, repo_snapshot}，
    前端据 mode 决定是否标注「非本机重算」。
    """
    raw = _load_json_truth(TRUTH_FILE)
    if raw is not None:
        return (
            _normalise_truth(raw),
            TRUTH_FILE.relative_to(REPO_ROOT).as_posix(),
            "local_recompute",
        )

    folds = load_folds(mil_root) if mil_root is not None else []
    if folds:
        return metrics_from_predictions(folds), "recomputed_from_predictions", "local_recompute"

    if require_truth:
        raise FileNotFoundError(
            f"缺少指标真源：{TRUTH_FILE}，或外部项目下的 best_solution/fold*/predictions.json"
        )

    snap = _load_json_truth(REPO_SNAPSHOT)
    if snap is not None:
        return (
            _normalise_truth(snap),
            REPO_SNAPSHOT.relative_to(REPO_ROOT).as_posix(),
            "repo_snapshot",
        )

    return {"hybrid": {"per_fold": [], "pooled": {}}, "plsr": {"per_fold": [], "pooled": {}}}, "", "none"


def _normalise_truth(raw: dict) -> dict:
    """把 metrics_recomputed.json 转成 bundle 需要的统一内部结构。"""
    per_fold = []
    for row in raw["per_fold"]:
        h, p = row["hybrid"], row["plsr"]
        per_fold.append(
            {
                "fold": row["fold"],
                "n": row["n"],
                "hybrid": {"rmse": h["rmse"], "mae": h["mae"], "r2": h["r2"]},
                "plsr": {"rmse": p["rmse"], "mae": p["mae"], "r2": p["r2"]},
                "delta_rmse": h["rmse"] - p["rmse"],
            }
        )
    hyb = raw["hybrid"]
    pls = raw["plsr"]
    pooled = raw.get("pooled_oof") or {}
    return {
        "hybrid": {
            "per_fold": per_fold,
            "pooled": {
                "n": pooled.get("n_total"),
                "rmse": pooled.get("hybrid_rmse"),
                "mae": None,
                "r2": pooled.get("hybrid_r2"),
            },
            "headline": {
                "mean_rmse": hyb.get("mean_rmse"),
                "std_rmse_pop": hyb.get("std_rmse_pop"),
                "std_rmse_sample": hyb.get("std_rmse_sample"),
                "mean_mae": hyb.get("mean_mae"),
                "mean_r2": hyb.get("mean_r2"),
            },
        },
        "plsr": {
            "per_fold": per_fold,
            "pooled": {
                "n": pooled.get("n_total"),
                "rmse": pooled.get("plsr_rmse"),
                "mae": None,
                "r2": pooled.get("plsr_r2"),
            },
            "headline": {
                "mean_rmse": pls.get("mean_rmse"),
                "std_rmse_pop": pls.get("std_rmse_pop"),
                "std_rmse_sample": pls.get("std_rmse_sample"),
                "mean_mae": pls.get("mean_mae"),
                "mean_r2": pls.get("mean_r2"),
            },
        },
        "paired_test_raw": raw.get("paired_test"),
        "_source": "metrics_recomputed.json",
    }


def build_metrics_block(truth: dict) -> dict:
    """组装右栏指标块：双口径 + 配对检验。"""
    hyb_rows = truth["hybrid"]["per_fold"]
    hyb_rmse = [r["hybrid"]["rmse"] for r in hyb_rows]
    pls_rmse = [r["plsr"]["rmse"] for r in hyb_rows]

    def agg(vals: list[float]) -> dict:
        vals = [v for v in vals if v is not None]
        return {
            "mean": round(st.mean(vals), 4),
            # ddof=0 总体标准差，与论文口径一致
            "std": round(st.pstdev(vals), 4),
            "std_sample": round(st.stdev(vals), 4) if len(vals) > 1 else 0.0,
        }

    hyb_mean, pls_mean = st.mean(hyb_rmse), st.mean(pls_rmse)
    improvement_per_fold = 100 * (pls_mean - hyb_mean) / pls_mean

    hyb_pool = truth["hybrid"]["pooled"] or {}
    pls_pool = truth["plsr"]["pooled"] or {}
    improvement_pooled = None
    if hyb_pool.get("rmse") and pls_pool.get("rmse"):
        improvement_pooled = 100 * (pls_pool["rmse"] - hyb_pool["rmse"]) / pls_pool["rmse"]

    pt = _paired_test(hyb_rmse, pls_rmse)
    raw_pt = truth.get("paired_test_raw") or {}
    if raw_pt.get("t") is not None:
        # 与重算脚本保持完全一致（它用的是 scipy.ttest_rel）
        pt["t"] = round(raw_pt["t"], 4)
        pt["df"] = raw_pt.get("df", pt["df"])
        pt["p"] = round(raw_pt["p"], 4) if raw_pt.get("p") is not None else pt["p"]
        pt["mean_diff"] = round(raw_pt["mean_diff"], 4) if raw_pt.get("mean_diff") else pt["mean_diff"]
    scatter = truth.get("scatter") or {}
    if not scatter:
        # 真源里没存散点：从逐折 per_fold 拿不到样本级预测，只能标记缺省
        scatter = {"y_true": [], "hybrid": [], "plsr": [], "unit": "kcal/kg"}

    def arm(which: str, pooled: dict) -> dict:
        """which = 'hybrid' | 'plsr'；per_fold 从**全精度值**舍入，避免舍入链误差。"""
        rows = [(r["fold"], r["n"], r[which]) for r in hyb_rows]
        return {
            "per_fold": [
                {
                    "fold": fold,
                    "n": n,
                    "rmse": round(v["rmse"], 2),
                    "mae": round(v["mae"], 2),
                    "r2": round(v["r2"], 4),
                }
                for fold, n, v in rows
            ],
            "summary": {
                "rmse": agg([v["rmse"] for _, _, v in rows]),
                "mae": agg([v["mae"] for _, _, v in rows]),
                "r2": agg([v["r2"] for _, _, v in rows]),
            },
            "pooled": {
                "n": pooled.get("n"),
                "rmse": round(pooled["rmse"], 2) if pooled.get("rmse") is not None else None,
                "r2": round(pooled["r2"], 4) if pooled.get("r2") is not None else None,
            },
        }

    return {
        "convention": (
            "5 折交叉验证（n=70）。口径 A「逐折均值」：每折内算指标后取 5 折平均，"
            "为论文正文口径；口径 B「合并 OOF」：把 5 折 out-of-fold 预测合并后统一算指标。"
            "两者不可混用（本课题 A 为 214.57、B 为 216.10）。标准差为总体标准差 ddof=0。"
        ),
        "primary_convention": "per_fold_mean",
        "hybrid": arm("hybrid", hyb_pool),
        "plsr_baseline": arm("plsr", pls_pool),
        "improvement_pct": round(improvement_per_fold, 2),
        "improvement_pct_pooled": round(improvement_pooled, 2) if improvement_pooled is not None else None,
        "improvement_basis": "improvement_pct 用逐折均值口径（与论文一致）；pooled 口径单列，避免两口径混用",
        "paired_test": pt,
        "scatter": scatter,
    }


# --------------------------------------------------------------------------- #
# 消融（读注册表，不复制数值）
# --------------------------------------------------------------------------- #
def build_ablation() -> dict | None:
    if not REGISTRY_FILE.is_file():
        return None
    try:
        reg = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    pool_seq, path_seq, comp_seq = [], [], []
    for e in reg.get("experiments", []):
        if e.get("category") != "ablation":
            continue
        rmse = (e.get("metrics") or {}).get("rmse_kcal_mean")
        if rmse is None:
            continue
        label = re.sub(
            r"^(消融-(?:池化策略|优化路径):\s*|组件级消融-)", "", e.get("name") or e["id"]
        )
        item = {
            "id": e["id"],
            "label": label,
            "rmse": round(float(rmse), 2),
            "config": e.get("config") or {},
        }
        # 三组分开放：任何跨组拼接都会把不同基准的数字放进同一条排序里
        if e["id"].startswith("abl_pool_"):
            pool_seq.append(item)
        elif e["id"].startswith("abl_comp_"):
            comp_seq.append(item)
        else:
            path_seq.append(item)

    if not pool_seq and not path_seq and not comp_seq:
        return None
    for seq in (pool_seq, path_seq, comp_seq):
        seq.sort(key=lambda x: x["rmse"])
    return {
        "status": "available",
        "caveat": ABLATION_CAVEAT,
        "pooling": pool_seq,
        "path": path_seq,
        "component": comp_seq,
        "component_caveat": COMPONENT_ABLATION_CAVEAT,
        "source": "gewu/mcp/registry/coal_mil.json#category=ablation",
    }


# --------------------------------------------------------------------------- #
# 文献：论文 bibitem × D1 核验结果
# --------------------------------------------------------------------------- #
def build_papers() -> list[dict]:
    bib = _parse_bibitems()
    status = _load_refs_status()
    out = []
    for key, body in bib:
        item = _split_bibitem(body)
        st_info = status.get(key) or {}
        item.update(
            {
                "key": key,
                "status": st_info.get("status", "unknown"),
                "method": st_info.get("method", ""),
            }
        )
        out.append(item)
    return out


def _parse_bibitems() -> list[tuple[str, str]]:
    tex_path = _existing(TEX_FILE, TEX_FALLBACK)
    if not tex_path.is_file():
        return []
    tex = tex_path.read_text(encoding="utf-8")
    m = re.search(
        r"\\begin\{thebibliography\}\{[^}]*\}(.*?)\\end\{thebibliography\}", tex, re.S
    )
    if not m:
        return []
    block = m.group(1)
    chunks = re.split(r"\\bibitem\{([^}]+)\}", block)
    out = []
    for i in range(1, len(chunks) - 1, 2):
        out.append((chunks[i].strip(), chunks[i + 1].strip()))
    return out


def _split_bibitem(body: str) -> dict:
    venue_m = re.search(r"\\textit\{([^}]+)\}", body)
    venue = venue_m.group(1).strip() if venue_m else ""

    # 年份必须在「去掉 arXiv/DOI 标识符之后」再匹配，否则 1402.2060 会被当成 2060 年
    body_ids_stripped = re.sub(r"arXiv:\s*[\d.]+", "", body)
    body_ids_stripped = re.sub(r"DOI:\s*10\.\d{4,}/[^\s;,\]}]+", "", body_ids_stripped)
    year_m = re.search(r"\b(19|20)\d{2}\b", body_ids_stripped)
    year = int(year_m.group(0)) if year_m else None

    doi_m = re.search(r"(10\.\d{4,}/[^\s;,\]}]+)", body)
    arx_m = re.search(r"arXiv:\s*(\d{4}\.\d{4,5})", body)

    head = body
    if venue_m:
        head = body[: venue_m.start()]
    head = re.split(r"arXiv:|DOI:", head)[0]
    # 取最长的一句作为标题（可跳过 p6 那种「作者. 标题.」句式里的作者段）
    parts = [p.strip(" .") for p in re.split(r"\.\s+", head) if p.strip(" .")]
    title = max(parts, key=len) if parts else head.strip(" .")
    title = re.sub(r"\s+", " ", title)

    # 无 \textit 时（如「... Spectroscopy. Wiley, 2021.」）从标题之后的残留里取出版方
    if not venue and title and title in head:
        tail = head[head.find(title) + len(title):]
        tail = re.sub(r"\b(19|20)\d{2}\b", "", tail).strip(" \t\r\n.,;")
        if 0 < len(tail) < 40 and not re.search(r"\d", tail):
            venue = tail
    return {
        "title": title,
        "venue": venue,
        "year": year,
        "doi": doi_m.group(1).rstrip(".") if doi_m else "",
        "arxiv": arx_m.group(1) if arx_m else "",
    }


def _load_refs_status() -> dict[str, dict]:
    refs_path = _existing(REFS_FILE, REFS_FALLBACK)
    if not refs_path.is_file():
        return {}
    try:
        refs = json.loads(refs_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {p["id"]: p for p in refs.get("papers", []) if p.get("id")}


def refs_summary() -> dict | None:
    refs_path = _existing(REFS_FILE, REFS_FALLBACK)
    if not refs_path.is_file():
        return None
    try:
        refs = json.loads(refs_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return {
        "verdict": refs.get("verdict"),
        "hallucination_rate": refs.get("hallucination_rate"),
        "n_papers": len(refs.get("papers", [])),
        "checked_at": (refs.get("_meta") or {}).get("checked_at"),
        "tool": (refs.get("_meta") or {}).get("tool"),
    }


# --------------------------------------------------------------------------- #
# 光谱与产出物
# --------------------------------------------------------------------------- #
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


def build_artifacts(root: Path | None) -> list[dict]:
    """登记阶段产出物：仓库内交付件 + 外部课题的图目录（只记路径与体积）。"""
    out: list[dict] = []
    seen: set[str] = set()

    for rel_dir, patterns in ARTIFACT_GLOBS:
        base = REPO_ROOT / rel_dir
        if not base.is_dir():
            continue
        for pat in patterns:
            for p in sorted(base.glob(pat)):
                if not p.is_file():
                    continue
                rel = p.relative_to(REPO_ROOT).as_posix()
                if rel in seen:
                    continue
                seen.add(rel)
                out.append(
                    {
                        "name": p.name,
                        "rel": rel,
                        "kind": _kind_of(p),
                        "size_kb": round(p.stat().st_size / 1024, 1),
                        "scope": "repo",
                    }
                )

    if root is not None and root.is_dir():
        paper_dir = root / "gewu_paper"
        if paper_dir.is_dir():
            for p in sorted(paper_dir.rglob("*")):
                if not p.is_file():
                    continue
                rel = str(p.relative_to(root)).replace("\\", "/")
                if rel in seen:
                    continue
                seen.add(rel)
                out.append(
                    {
                        "name": p.name,
                        "rel": rel,
                        "kind": "figure" if p.parent.name == "figures" else p.suffix.lstrip("."),
                        "size_kb": round(p.stat().st_size / 1024, 1),
                        "scope": "external",
                    }
                )
    return out


def _kind_of(p: Path) -> str:
    suf = p.suffix.lower().lstrip(".")
    if p.name.startswith("handoff_"):
        return "handoff"
    if suf in ("tex", "json", "py", "md", "html"):
        return suf
    return suf or "file"


# --------------------------------------------------------------------------- #
# 一致性校验（供 --check 与测试复用）
# --------------------------------------------------------------------------- #
def validate_bundle(bundle: dict, *, tol: float = 0.02) -> list[str]:
    """bundle 内部与真源之间的一致性检查；返回错误列表（空 = 通过）。"""
    errs: list[str] = []
    if not bundle.get("available"):
        errs.append("bundle 不可用（available=false）")
        return errs

    m = bundle.get("metrics") or {}
    hyb, pls = m.get("hybrid"), m.get("plsr_baseline")
    if not hyb or not pls:
        errs.append("缺少 hybrid 或 plsr_baseline 指标块")
        return errs

    # 1) 逐折均值 == 逐折列表的均值（不允许「先舍入再平均」的偏差超容差）
    for arm_name, arm in (("hybrid", hyb), ("plsr_baseline", pls)):
        for field in ("rmse", "mae", "r2"):
            vals = [row[field] for row in arm["per_fold"] if row.get(field) is not None]
            if not vals:
                continue
            mean_vals = st.mean(vals)
            declared = arm["summary"][field]["mean"]
            if abs(mean_vals - declared) > tol:
                errs.append(
                    f"{arm_name}.{field} 汇总均值 {declared} 与逐折均值 {mean_vals:.4f} 不符"
                )

    # 2) 两种口径必须都声明且方向一致（hybrid 都优于 PLSR）
    imp_a = m.get("improvement_pct")
    imp_b = m.get("improvement_pct_pooled")
    if imp_a is None:
        errs.append("缺少 improvement_pct（逐折口径）")
    if imp_b is None:
        errs.append("缺少 improvement_pct_pooled（合并 OOF 口径）")
    if imp_a is not None and imp_b is not None and (imp_a <= 0 or imp_b <= 0):
        errs.append(f"两种口径的改进幅度应同时为正，实际 {imp_a} / {imp_b}")

    # 3) 与真源交叉核对（本机重算产物优先，其次仓库快照）
    truth_path = TRUTH_FILE if TRUTH_FILE.is_file() else (
        REPO_SNAPSHOT if REPO_SNAPSHOT.is_file() else None
    )
    if truth_path is not None:
        try:
            truth = json.loads(truth_path.read_text(encoding="utf-8"))
            pairs = [
                ("hybrid.mean_rmse", hyb["summary"]["rmse"]["mean"], truth["hybrid"]["mean_rmse"]),
                ("plsr.mean_rmse", pls["summary"]["rmse"]["mean"], truth["plsr"]["mean_rmse"]),
                ("hybrid.mean_r2", hyb["summary"]["r2"]["mean"], truth["hybrid"]["mean_r2"]),
                ("plsr.mean_r2", pls["summary"]["r2"]["mean"], truth["plsr"]["mean_r2"]),
            ]
            for name, got, want in pairs:
                if abs(got - want) > tol:
                    errs.append(f"{name}: bundle {got} vs 真源 {want}（差 {abs(got-want):.4f}）")
        except (json.JSONDecodeError, OSError, KeyError) as e:  # pragma: no cover
            errs.append(f"读取真源失败: {e}")

    # 4) 检验结论必须自洽（p 显著则 mean_diff 应为负）
    pt = m.get("paired_test") or {}
    if pt.get("available"):
        if pt.get("p") is None:
            errs.append("paired_test 标记 available 但缺少 p 值")
        elif pt["p"] < 0.05 and (pt.get("mean_diff") or 0) >= 0:
            errs.append("p<0.05 但 mean_diff 非负，结论与数据方向矛盾")

    # 5) 文献：论文里有几条 bibitem，papers 就应有多少条，且全部 verified
    bib = _parse_bibitems()
    papers = bundle.get("papers") or []
    if bib and len(papers) != len(bib):
        errs.append(f"papers 数 {len(papers)} 与论文 bibitem 数 {len(bib)} 不一致")
    bad = [p.get("key") for p in papers if p.get("status") != "verified"]
    if bad:
        errs.append(f"存在未核验文献: {bad}")

    # 6) 消融必须带口径警示（防止跨配置直接相减）
    abl = bundle.get("ablation")
    if abl and not (abl.get("caveat") or "").strip():
        errs.append("ablation 缺少 caveat，跨配置数值会被误读")
    if abl and abl.get("component") and not (abl.get("component_caveat") or "").strip():
        errs.append("组件级消融缺少 component_caveat，三组基准不同会被混算")
    # 三组不许混：组件臂一旦落进 pooling/path，就会与 347.55 那组排进同一张表
    if abl:
        for key in ("pooling", "path"):
            bad_ids = [x["id"] for x in (abl.get(key) or []) if x["id"].startswith("abl_comp_")]
            if bad_ids:
                errs.append(f"组件臂误入 ablation.{key}: {bad_ids}")

    # 7) 来源必须可辨识：快照模式要显式标注「非本机重算」，不能冒充实测
    mode = bundle.get("mode")
    if mode not in ("local_recompute", "repo_snapshot"):
        errs.append(f"mode 非法或缺失: {mode!r}")
    if mode == "repo_snapshot" and not (bundle.get("mode_label") or "").strip():
        errs.append("repo_snapshot 模式缺少 mode_label，会被误认为本机重算结果")

    return errs


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def build_bundle(root: Path | None, *, require_truth: bool = False) -> dict:
    mil_root = (root / "coal-mil") if (root is not None and root.is_dir()) else None

    try:
        truth, truth_src, mode = load_truth(mil_root, require_truth=require_truth)
    except FileNotFoundError as e:
        return {
            "available": False,
            "reason": str(e),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    if not truth["hybrid"]["per_fold"]:
        where = str(mil_root) if mil_root else "本机外部课题与仓库快照"
        return {
            "available": False,
            "reason": f"未在 {where} 找到可用指标（best_solution/fold*/predictions.json 或仓库快照）",
            "hint": "python scripts/export_case_bundle.py --root <课题根>",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    # 散点/光谱需要样本级数据，只有本机有外部项目时才能补；快照模式下留空，UI 自动隐藏
    folds = load_folds(mil_root) if mil_root is not None else []
    if not (truth.get("scatter") or {}).get("y_true") and folds:
        truth["scatter"] = metrics_from_predictions(folds)["scatter"]

    spectrum = None
    if mil_root is not None and folds and folds[0]:
        data_root = mil_root.parent / "data" / "赛题数据划分"
        first_bag = folds[0][0].get("bag_id", "")
        if data_root.is_dir() and first_bag:
            spectrum = build_spectrum(data_root, first_bag)

    tex_used = _existing(TEX_FILE, TEX_FALLBACK)
    refs_used = _existing(REFS_FILE, REFS_FALLBACK)

    return {
        "available": True,
        "mode": mode,
        "mode_label": {
            "local_recompute": "本机重算（逐折 predictions 已交叉校验）",
            "repo_snapshot": "仓库内脱敏快照（非本机重算，仅供无外部课题时查看口径与结构）",
        }.get(mode, mode),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "topic": "LIBS 大颗粒原煤热值预测（PLSR-MIL 残差混合）",
        "provenance": {
            "metrics": truth_src or None,
            "registry": REGISTRY_FILE.relative_to(REPO_ROOT).as_posix()
            if REGISTRY_FILE.is_file() else None,
            # 指向实际读取的那一份（存档不在时是 docs/ 下的入库副本），不谎报来源
            "references": refs_used.relative_to(REPO_ROOT).as_posix()
            if refs_used.is_file() else None,
            "paper": tex_used.relative_to(REPO_ROOT).as_posix() if tex_used.is_file() else None,
            "predictions_root": str(mil_root / "outputs" / "best_solution") if mil_root else None,
            "note": "所有数值均来自上述文件，右栏不自行计算新指标；仓库内不复制实验数据。",
        },
        "metrics": build_metrics_block(truth),
        "ablation": build_ablation(),
        "references_summary": refs_summary(),
        "spectrum": spectrum,
        "papers": build_papers(),
        "artifacts": build_artifacts(root),
    }


def emit_snapshot(src: Path, dst: Path) -> int:
    """把本机重算产物脱敏后写入仓库快照（去掉外部绝对路径，仅保留聚合指标）。"""
    raw = _load_json_truth(src)
    if raw is None:
        print(f"[snapshot] 源不可用或结构不符: {src}")
        return 1
    snap = {
        "schema_version": 1,
        "note": (
            "脱敏快照：仅含聚合指标与逐折指标，不含原始光谱、模型权重、逐样本预测。"
            "由 scripts/export_case_bundle.py --emit-snapshot 生成。"
        ),
        "source_root": "<external-coal-project>",
        "hybrid": raw.get("hybrid"),
        "plsr": raw.get("plsr"),
        "paired_test": raw.get("paired_test"),
        "pooled_oof": raw.get("pooled_oof"),
        "per_fold": raw.get("per_fold"),
        "registry_cross_check": raw.get("registry_cross_check"),
    }
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[snapshot] wrote {dst.relative_to(REPO_ROOT).as_posix()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="导出格物 Web 右栏的真实案例数据")
    ap.add_argument("--root", default=None, help="外部课题根目录（不指定则自动发现）")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="产物路径")
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    ap.add_argument(
        "--emit-snapshot",
        nargs="?",
        const=str(REPO_SNAPSHOT),
        default=None,
        metavar="PATH",
        help="把本机重算产物脱敏写入仓库快照（默认 docs/verification/case_snapshot.json）",
    )
    args = ap.parse_args(argv)

    if args.emit_snapshot:
        return emit_snapshot(TRUTH_FILE, Path(args.emit_snapshot))

    root = resolve_root(args.root)
    bundle = build_bundle(root, require_truth=False)
    errs = validate_bundle(bundle)

    if args.check:
        print(f"[case-bundle] available={bundle.get('available')} errors={len(errs)}")
        for e in errs:
            print(f"  - {e}")
        return 0 if not errs else 1

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")

    if not bundle.get("available"):
        print(f"[case-bundle] available=false -> {out_path}")
        print(f"             reason: {bundle.get('reason')}")
        return 0

    m = bundle["metrics"]
    print(f"[case-bundle] available=true -> {out_path}")
    print(
        f"             source={bundle['provenance']['metrics']} "
        f"papers={len(bundle['papers'])} artifacts={len(bundle['artifacts'])}"
    )
    print(
        f"             per-fold: hybrid {m['hybrid']['summary']['rmse']['mean']:.4f} "
        f"vs plsr {m['plsr_baseline']['summary']['rmse']['mean']:.4f} "
        f"(-{m['improvement_pct']}%)"
    )
    print(
        f"             pooled  : hybrid {m['hybrid']['pooled']['rmse']} "
        f"vs plsr {m['plsr_baseline']['pooled']['rmse']} "
        f"(-{m['improvement_pct_pooled']}%)"
    )
    pt = m["paired_test"]
    if pt.get("available"):
        print(f"             paired t({pt['df']})={pt['t']} p={pt['p']} CI95={pt['ci95']}")
    if errs:
        print(f"             [WARN] {len(errs)} 项一致性检查未通过：")
        for e in errs:
            print(f"               - {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
