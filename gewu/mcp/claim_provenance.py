#!/usr/bin/env python3
"""D2 — 数值声明溯源引擎（领域无关，反幻觉横向防线之二）。

把论文成稿里每条"对外断言的数字"绑定到一个可核验的溯源目标，并校验其一致性：

    source = registry:<exp_id>          → 比对 sci-exp 注册表的 source_of_truth
           | registry:<domain>:<exp_id> → 同上（domain 可选，id 全局唯一）
           | paper:<paper_id>           → 要求该文献在 D1 已核验集合内（verified_papers）

设计要点（与 P0-1 / sci-exp 的关系）：
  * 本引擎**不认识任何学科**，只消费 sci-exp 注册表（通过 sci_exp.load_experiments）。
  * D2 的语义与 sci-exp 的 rerun 交叉校验**不同**：
      - sci-exp rerun：代码跑出的真值 vs 注册表记录值（容忍度较大，如 rmse 1.0），
        保证"代码↔记录"一致（P0-2）。
      - D2 verify_claim：成稿里**写出来的数字** vs 注册表 source_of_truth（容忍度很紧，
        默认 1% 相对 + 0.01 绝对值下限），保证"写出来的数字↔真相"一致——
        专治写手凭记忆写错、抄错实验、数字漂移。
  * strict=True 时额外真跑 rerun_experiment，用实时重算真值再比一次（最强，但耗时）。

状态枚举：
    grounded               — 一致，可放心落稿
    drift                  — 与真相偏差超容忍度（疑似写错/抄错）
    unknown_experiment     — source 指向的实验不在注册表
    metric_not_in_registry — 实验存在，但注册表未登记该 metric（无法溯源）
    paper_grounded         — 文献类溯源：paper_id 在 D1 已核验集合内（数值需人工/LLM 复核）
    paper_unverified       — 文献类溯源：paper_id 不在已核验集合（不可信）
    bad_value              — 声明的值无法解析为数字
"""
from __future__ import annotations

import re
from typing import Any

import sci_exp as _sci_exp  # 复用其注册表加载与重算（同目录，无重依赖）

# D2 溯源容忍度：紧于 sci-exp 的 rerun 容忍度，专治"写出来的数字"漂移。
_DEFAULT_REL_TOL = 0.01     # 1% 相对
_DEFAULT_ABS_FLOOR = 0.01   # 绝对值下限，避免小量（如 R²）被过松放过


def _parse_source(source: str) -> tuple[str, str | None, str]:
    """返回 (kind, domain_or_None, id)。支持 registry:<id> / registry:<domain>:<id> / paper:<id>。"""
    s = (source or "").strip()
    if s.startswith("registry:"):
        rest = s[len("registry:"):]
        parts = rest.split(":", 1)
        if len(parts) == 2:
            return "registry", parts[0], parts[1]
        return "registry", None, parts[0]
    if s.startswith("paper:"):
        return "paper", None, s[len("paper:"):].strip()
    return "unknown", None, s


def _parse_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        return float(m.group(0)) if m else None
    return None


def _default_tol(truth: float) -> float:
    return max(abs(truth) * _DEFAULT_REL_TOL, _DEFAULT_ABS_FLOOR)


def ground_claim(claim: dict, verified_papers: set[str] | None = None, strict: bool = False) -> dict:
    """校验单条声明，返回带状态的 dict。"""
    text = claim.get("text", "")
    metric = claim.get("metric")
    source = claim.get("source", "")
    raw_value = claim.get("value")
    value = _parse_value(raw_value)
    if value is None:
        return {"status": "bad_value", "text": text, "source": source,
                "value": raw_value, "reason": "值无法解析为数字"}

    kind, domain, exp_id = _parse_source(source)
    if kind == "unknown":
        return {"status": "bad_source", "text": text, "source": source,
                "value": value, "reason": "source 须为 registry:<id> 或 paper:<id>"}

    if kind == "paper":
        vset = verified_papers or set()
        if exp_id in vset:
            return {"status": "paper_grounded", "text": text, "source": source,
                    "metric": metric, "value": value,
                    "note": "文献在 D1 已核验集合内；其具体数值需人工/LLM 复核原文"}
        return {"status": "paper_unverified", "text": text, "source": source,
                "metric": metric, "value": value,
                "note": "文献不在 D1 已核验集合，不可信"}

    # kind == registry
    exps = _sci_exp.load_experiments()
    entry = exps.get(exp_id)
    if entry is None:
        return {"status": "unknown_experiment", "text": text, "source": source,
                "value": value, "experiment_id": exp_id,
                "reason": "注册表无此实验"}
    if not metric:
        return {"status": "metric_required", "text": text, "source": source,
                "value": value, "experiment_id": exp_id,
                "reason": "registry 溯源须指定 metric"}
    recorded = (entry.get("metrics") or {}).get(metric)
    if recorded is None:
        return {"status": "metric_not_in_registry", "text": text, "source": source,
                "value": value, "experiment_id": exp_id, "metric": metric,
                "reason": "注册表未登记该 metric，无法溯源"}

    truth = float(recorded)
    note = ""
    if strict:
        rep = entry.get("reproducibility")
        if rep in ("realizable_by_gewu", "verifiable_via_summary"):
            rr = _sci_exp.rerun_experiment(exp_id)
            if rr.get("status") == "reproduced":
                rec = (rr.get("recomputed") or {}).get(metric)
                if rec and rec.get("actual") is not None:
                    truth = float(rec["actual"])
                    note = "strict: 已用实时重算真值比对"
                else:
                    note = "strict: 重算未含该 metric，回退注册表记录值"
            else:
                note = f"strict: 重算失败({rr.get('status')})，回退注册表记录值"

    tol = claim.get("tolerance")
    if tol is None:
        tol = _default_tol(truth)
    else:
        tol = float(tol)
    abs_diff = abs(value - truth)
    ok = abs_diff <= tol
    return {
        "status": "grounded" if ok else "drift",
        "text": text, "source": source, "metric": metric,
        "experiment_id": exp_id, "domain": entry.get("domain"),
        "value": value, "truth": truth,
        "abs_diff": round(abs_diff, 6), "tolerance": tol,
        "reproducibility": entry.get("reproducibility"),
        "note": note,
    }


def verify_claims(claims: list[dict], verified_papers: list[str] | None = None,
                  strict: bool = False) -> dict:
    """批量校验声明，返回汇总 + 逐条结果。"""
    vset = set(verified_papers or [])
    rows = [ground_claim(c, verified_papers=vset, strict=strict) for c in claims]
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    n = len(rows)
    n_grounded = counts.get("grounded", 0) + counts.get("paper_grounded", 0)
    n_drift = counts.get("drift", 0)
    n_unverifiable = n - n_grounded - n_drift
    return {
        "all_grounded": (n_drift == 0) and (n_unverifiable == 0) and (n_grounded > 0),
        "n_claims": n,
        "n_grounded": n_grounded,
        "n_drift": n_drift,
        "n_unverifiable": n_unverifiable,
        "counts": counts,
        "strict": strict,
        "claims": rows,
    }
