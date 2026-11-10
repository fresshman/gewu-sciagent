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

metric 取值：
  * 标量 metric 直接比。
  * 列表型 metric（如 per_fold_rmse_kcal）**必须带下标** `per_fold_rmse_kcal[0]`。
    不写下标不会静默取第一项，而是返回 metric_not_scalar —— 因为"第一折"和"五折均值"
    是两件事，猜错就是把整批数字记到错的位置上。

历史来源写法（兼容但会标记）：
  真实 claims.json 里出现过 `registry:coal_mil#our_hybrid.metrics.rmse_kcal_mean`
  这种写法：`#` 前是 domain、`#` 后是 `<exp>.<path>`。引擎仍能解析（否则一份稿子的
  全部声明都会判成"不可溯源"，把语法错误伪装成数据错误），但会在返回里带
  `source_style="legacy-anchor"`，让上层能提示"写法非规范"。数值容忍度不放宽。

状态枚举：
    grounded               — 一致，可放心落稿
    drift                  — 与真相偏差超容忍度（疑似写错/抄错）
    metric_required        — registry 溯源但没给 metric
    metric_not_in_registry — 实验存在，但注册表未登记该 metric（无法溯源）
    metric_not_scalar      — 命中的是列表，没写下标（拒绝猜）
    metric_index_out_of_range — 下标越界
    metric_not_numeric     — 命中但值不是数字
    unknown_experiment     — source 指向的实验不在注册表
    paper_grounded         — 文献类溯源：paper_id 在 D1 已核验集合内（数值需人工/LLM 复核）
    paper_unverified       — 文献类溯源：paper_id 不在已核验集合（不可信）
    bad_value              — 声明的值无法解析为数字
    bad_source             — source 既不是 registry: 也不是 paper:
"""
from __future__ import annotations

import re
from typing import Any

import sci_exp as _sci_exp  # 复用其注册表加载与重算（同目录，无重依赖）

# D2 溯源容忍度：紧于 sci-exp 的 rerun 容忍度，专治"写出来的数字"漂移。
_DEFAULT_REL_TOL = 0.01     # 1% 相对
_DEFAULT_ABS_FLOOR = 0.01   # 绝对值下限，避免小量（如 R²）被过松放过

# 科学计数法也要认：1.1e-05 早先会被截成 1.1，判出个假的 drift。
_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
_IDX_RE = re.compile(r"^(?P<base>[^\[\]]+)\[(?P<idx>\d+)\]$")
# 写手习惯在 source 后面加解释，如 `(源: summary.json)`、`(由 214.57 × 0.004184 派生)`。
_NOTE_TAIL_RE = re.compile(r"[（(].*$", re.S)


def _strip_note(s: str) -> str:
    """剥掉 source 尾部的括注。

    这不是美化：`registry:<domain>:<exp>` 按第一个冒号切分，而括注里一旦有冒号
    （`(源: summary.json)`），切出来的 exp_id 就成了 ` summary.json)`，
    于是一条数字完全正确的声明被判成"注册表无此实验"。语法脏数据被当成数据错。
    """
    return _NOTE_TAIL_RE.sub("", s or "").strip()


def _parse_source(source: str) -> tuple[str, str | None, str]:
    """返回 (kind, domain_or_None, id)。支持 registry:<id> / registry:<domain>:<id> / paper:<id>。"""
    s = _strip_note(source)
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
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = _NUM_RE.search(value.replace(",", ""))
        if not m:
            return None
        try:
            return float(m.group(0))
        except ValueError:
            return None
    return None


def _default_tol(truth: float) -> float:
    return max(abs(truth) * _DEFAULT_REL_TOL, _DEFAULT_ABS_FLOOR)


def _metric_from_path(path: str) -> str:
    """`metrics.rmse_kcal_mean` → `rmse_kcal_mean`；非 metrics 段一律返回空。"""
    p = (path or "").strip().strip(".")
    if not p or not p.startswith("metrics."):
        return ""
    return p[len("metrics."):]


def _resolve_registry_target(exps: dict, raw_id: str) -> tuple[str | None, str, str]:
    """把 registry: 后面的串解析成 (exp_id, 锚点 metric, style)。

    style: canonical      —— `registry:<exp>` 或 `registry:<domain>:<exp>`
           legacy-anchor  —— `registry:<exp>#<path>` / `registry:<domain>#<exp>.<path>`
           unknown        —— 锚点两侧都不在注册表里
    """
    raw_id = (raw_id or "").strip()
    if "#" not in raw_id:
        return raw_id, "", "canonical"

    left, anchor = raw_id.split("#", 1)
    left = left.strip()
    anchor = anchor.strip().strip(".")

    # 1) <exp>#<path>
    if left in exps:
        return left, _metric_from_path(anchor), "legacy-anchor"
    # 2) <domain>#<exp>.<path>
    head = anchor.split(".", 1)[0].strip()
    if head in exps:
        rest = anchor[len(head):].lstrip(".")
        return head, _metric_from_path(rest), "legacy-anchor"
    return None, "", "unknown"


def _lookup_metric(entry: dict, metric: str) -> tuple[str, float | None, Any]:
    """在实验的 metrics 段取一个标量。返回 (kind, value, extra)。

    kind: ok / missing / list_needs_index / not_list / index_oob / not_a_number
    """
    metrics = entry.get("metrics") or {}
    m = _IDX_RE.match(metric or "")
    if m:
        base, idx = m.group("base"), int(m.group("idx"))
        seq = metrics.get(base)
        if seq is None:
            return "missing", None, base
        if not isinstance(seq, (list, tuple)):
            return "not_list", None, base
        if idx >= len(seq):
            return "index_oob", None, len(seq)
        try:
            return "ok", float(seq[idx]), base
        except (TypeError, ValueError):
            return "not_a_number", None, base

    v = metrics.get(metric)
    if v is None:
        return "missing", None, None
    if isinstance(v, (list, tuple)):
        return "list_needs_index", None, len(v)
    if isinstance(v, bool):
        return "not_a_number", None, None
    try:
        return "ok", float(v), None
    except (TypeError, ValueError):
        return "not_a_number", None, None


def _metric_failure(entry: dict, metric: str, kind: str, extra: Any) -> dict:
    """把"取不到标量"的几种情况翻成明确的返回体，理由要能直接指导改法。"""
    have = sorted((entry.get("metrics") or {}).keys())
    if kind == "missing":
        return {"status": "metric_not_in_registry",
                "reason": "注册表未登记该 metric，无法溯源",
                "metric": metric, "available_metrics": have[:12]}
    if kind == "list_needs_index":
        return {"status": "metric_not_scalar",
                "reason": f"注册表登记的是 {extra} 项列表，须写成 {metric}[0] 这样才能比到具体某一折",
                "metric": metric, "length": extra}
    if kind == "not_list":
        return {"status": "metric_not_list",
                "reason": f"下标用在了标量 metric `{extra}` 上",
                "metric": metric}
    if kind == "index_oob":
        return {"status": "metric_index_out_of_range",
                "reason": f"下标越界：`{metric}` 只有 {extra} 项",
                "metric": metric, "length": extra}
    return {"status": "metric_not_numeric",
            "reason": "命中的值不是数字，无法比对",
            "metric": metric}


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

    kind, _domain, raw_id = _parse_source(source)
    if kind == "unknown":
        return {"status": "bad_source", "text": text, "source": source,
                "value": value, "reason": "source 须为 registry:<id> 或 paper:<id>"}

    if kind == "paper":
        vset = verified_papers or set()
        if raw_id in vset:
            return {"status": "paper_grounded", "text": text, "source": source,
                    "metric": metric, "value": value,
                    "note": "文献在 D1 已核验集合内；其具体数值需人工/LLM 复核原文"}
        return {"status": "paper_unverified", "text": text, "source": source,
                "metric": metric, "value": value,
                "note": "文献不在 D1 已核验集合，不可信"}

    # kind == "registry"
    exps = _sci_exp.load_experiments()
    exp_id, anchor_metric, style = _resolve_registry_target(exps, raw_id)
    if style == "unknown" or exp_id is None:
        return {"status": "unknown_experiment", "text": text, "source": source,
                "value": value, "experiment_id": raw_id,
                "reason": "注册表无此实验（`#` 前后都不是已登记的实验 id）",
                "available_experiments": sorted(exps.keys())[:12]}

    entry = exps.get(exp_id)
    if entry is None:
        return {"status": "unknown_experiment", "text": text, "source": source,
                "value": value, "experiment_id": exp_id,
                "reason": "注册表无此实验",
                "available_experiments": sorted(exps.keys())[:12]}
    if not metric and not anchor_metric:
        return {"status": "metric_required", "text": text, "source": source,
                "value": value, "experiment_id": exp_id,
                "reason": "registry 溯源须指定 metric"}

    # claim 自己写的 metric 优先；写错了才回退到 source 锚点里的路径。
    # 两条都试，是为了让「source 指对了、metric 名写错」这种也能被救回来，
    # 而不是一律判不可溯源。
    chosen_metric = None
    truth = None
    metric_origin = None
    failures = []
    for cand, origin in ((metric, "claim"), (anchor_metric, "source")):
        if not cand:
            continue
        st, val, extra = _lookup_metric(entry, cand)
        if st == "ok":
            chosen_metric, truth, metric_origin = cand, val, origin
            break
        failures.append((cand, st, extra))

    if chosen_metric is None:
        cand, st, extra = failures[0]
        out = _metric_failure(entry, cand, st, extra)
        out.update({"text": text, "source": source, "value": value,
                    "experiment_id": exp_id, "domain": entry.get("domain"),
                    "source_style": style})
        if len(failures) > 1:
            out["tried"] = [f"{c}({s})" for c, s, _ in failures]
        return out

    note_parts = []
    # 不把「用了 # 锚点写法」拼进 note：那是结构化信息，已由 source_style 字段表达。
    # 拼进 note 会和上层的提示文案撞车，同一句话在一张卡片里出现两遍。
    if metric_origin == "source":
        note_parts.append(f"claim.metric 未命中，改用 source 锚点里的 `{chosen_metric}`")

    if strict:
        rep = entry.get("reproducibility")
        if rep in ("realizable_by_gewu", "verifiable_via_summary"):
            rr = _sci_exp.rerun_experiment(exp_id)
            if rr.get("status") == "reproduced":
                rec = (rr.get("recomputed") or {}).get(chosen_metric)
                if rec and rec.get("actual") is not None:
                    truth = float(rec["actual"])
                    note_parts.append("strict: 已用实时重算真值比对")
                else:
                    note_parts.append("strict: 重算未含该 metric，回退注册表记录值")
            else:
                note_parts.append(f"strict: 重算失败({rr.get('status')})，回退注册表记录值")

    tol = claim.get("tolerance")
    if tol is None:
        tol = _default_tol(truth)
    else:
        tol = float(tol)
    abs_diff = abs(value - truth)
    ok = abs_diff <= tol
    out = {
        "status": "grounded" if ok else "drift",
        "text": text, "source": source, "metric": chosen_metric,
        "experiment_id": exp_id, "domain": entry.get("domain"),
        "value": value, "truth": truth,
        "abs_diff": round(abs_diff, 6), "tolerance": tol,
        "reproducibility": entry.get("reproducibility"),
        "source_style": style,
        "note": "；".join(note_parts),
    }
    if metric_origin == "source":
        out["claim_metric"] = metric
    return out


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
    # 语法层单独计数：这些不是"数字错了"，而是"指针写错了"，改法不同。
    n_legacy = sum(1 for r in rows if r.get("source_style") == "legacy-anchor")
    return {
        "all_grounded": (n_drift == 0) and (n_unverifiable == 0) and (n_grounded > 0),
        "n_claims": n,
        "n_grounded": n_grounded,
        "n_drift": n_drift,
        "n_unverifiable": n_unverifiable,
        "n_legacy_source": n_legacy,
        "counts": counts,
        "strict": strict,
        "claims": rows,
    }
