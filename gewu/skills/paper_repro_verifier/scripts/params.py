"""Three-source parameter reconciliation -> an executable parameter table.

Sources: paper text (incl. supplement), config files, code defaults.
Every resolved value carries its evidence locator and a source_class:
  paper_explicit | code_inferred | self_set | unresolved
Conflicts are surfaced, never silently resolved.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from common import now_iso, rel

ALIASES = {
    "learning rate": "lr", "learning_rate": "lr", "lr": "lr", "eta": "lr",
    "batch size": "batch_size", "batch-size": "batch_size", "batch": "batch_size",
    "epoch": "epochs", "epochs": "epochs", "num epochs": "epochs", "n_epochs": "epochs",
    "seed": "seed", "random seed": "seed", "random_seed": "seed",
    "folds": "n_folds", "k": "n_folds", "n_folds": "n_folds", "k_folds": "n_folds",
    "num_folds": "n_folds", "fold": "n_folds", "5-fold": "n_folds",
    "dropout": "dropout", "weight decay": "weight_decay", "weight_decay": "weight_decay",
    "hidden dim": "hidden_dim", "hidden_dim": "hidden_dim", "hidden": "hidden_dim",
    "n components": "n_components", "n_components": "n_components",
    "components": "n_components", "latent dim": "latent_dim", "latent_dim": "latent_dim",
    "temperature": "temperature", "tau": "temperature",
    "alpha": "alpha", "beta": "beta", "gamma": "gamma", "lambda": "lambda",
    "window": "window", "window_size": "window", "sg_window": "window",
    "polyorder": "polyorder", "tolerance": "tolerance", "tol": "tolerance",
    "threshold": "threshold", "epsilon": "epsilon", "eps": "epsilon",
    "n estimators": "n_estimators", "n_estimators": "n_estimators",
    "max depth": "max_depth", "max_depth": "max_depth",
    "patience": "patience", "warmup": "warmup", "layers": "n_layers",
    "n_layers": "n_layers", "num_layers": "n_layers",
    "train ratio": "train_ratio", "test_size": "test_ratio", "test ratio": "test_ratio",
}
KEYS = sorted(set(ALIASES.values()))
_NUM = r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|none|null)"
_PAPER_RX = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(ALIASES, key=len, reverse=True)) + r")\b"
    r"\s*(?:=|:|is|of|to|set to|been set at|with|using|:=)\s*" + _NUM, re.I)
_TABLE_RX = re.compile(r"^\s*[|]?\s*([A-Za-z_ \-]{2,32})\s*[|:]\s*" + _NUM + r"\s*[|]?\s*$")
_ASSIGN_RX = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_ \-]{0,30})\s*(?:=|:)\s*" + _NUM + r"\s*(?:,|#.*)?$")
_ARGPARSE_RX = re.compile(r"add_argument\(\s*[\"']--?([A-Za-z0-9_\-]+)[\"'][^)]*?default\s*=\s*" + _NUM, re.I)
_DICT_RX = re.compile(r"[\"']([A-Za-z0-9_\-]+)[\"']\s*:\s*" + _NUM)


def canon(name: str) -> str | None:
    n = name.strip().lower().replace("-", "_")
    if n in ALIASES:
        return ALIASES[n]
    n2 = n.replace("_", " ")
    return ALIASES.get(n2)


def _num(v: str):
    s = v.strip().lower()
    if s in ("true",): return True
    if s in ("false",): return False
    if s in ("none", "null"): return None
    try:
        f = float(s)
        return int(f) if f.is_integer() and "e" not in s else f
    except ValueError:
        return v.strip()


def from_paper(index: dict) -> dict:
    """Collect (parameter -> list of {value, evidence}) from PAPER text only."""
    from common import PAPER_ROLES
    out: dict[str, list] = {}
    for doc in index.get("documents", []):
        if doc.get("role") not in PAPER_ROLES:
            continue
        for pg in doc.get("pages", []):
            for ln, line in enumerate(pg.get("lines", []), 1):
                pairs = [(m.group(1), m.group(2)) for m in _PAPER_RX.finditer(line)]
                for m in _TABLE_RX.finditer(line):
                    pairs.append((m.group(1), m.group(2)))
                for name, value in pairs:
                    key = canon(name)
                    if not key:
                        continue
                    out.setdefault(key, []).append({
                        "value": _num(value),
                        "evidence": {"source": doc["path"], "page": pg["page"],
                                     "line": ln, "quote": line.strip()[:240]}})
    return out


def from_files(base: Path, items: list[dict]) -> tuple[dict, dict]:
    """Collect code/config defaults. Returns (code_values, config_values)."""
    code: dict[str, list] = {}
    conf: dict[str, list] = {}
    for it in items:
        if it.get("role") not in ("code", "notebook", "config", "parameter_source",
                                  "data_or_config", "script"):
            continue
        p = base / it["path"]
        if not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        is_conf = p.suffix.lower() in (".json", ".yaml", ".yml", ".toml", ".ini", ".cfg")
        target = conf if is_conf else code
        for ln, line in enumerate(lines, 1):
            pairs = []
            for m in _ARGPARSE_RX.finditer(line):
                pairs.append((m.group(1), m.group(2)))
            for m in _ASSIGN_RX.finditer(line):
                pairs.append((m.group(1), m.group(2)))
            for m in _DICT_RX.finditer(line):
                pairs.append((m.group(1), m.group(2)))
            for name, value in pairs:
                key = canon(name)
                if not key:
                    continue
                target.setdefault(key, []).append({
                    "value": _num(value),
                    "evidence": {"source": it["path"], "line": ln,
                                 "quote": line.strip()[:240]}})
    return code, conf


def _distinct(entries: list[dict]) -> list:
    seen, vals = set(), []
    for e in entries:
        v = e["value"]
        k = json.dumps(v, sort_keys=True)
        if k not in seen:
            seen.add(k)
            vals.append(v)
    return vals


def build(index: dict, base: Path, ledger_items: list[dict]) -> dict:
    paper = from_paper(index)
    code, conf = from_files(base, ledger_items)
    all_keys = sorted(set(paper) | set(code) | set(conf))
    rows = []
    for key in all_keys:
        p_e, c_e, f_e = paper.get(key, []), code.get(key, []), conf.get(key, [])
        p_vals, c_vals, f_vals = _distinct(p_e), _distinct(c_e), _distinct(f_e)
        external = list(dict.fromkeys([json.dumps(v) for v in p_vals + f_vals]))
        conflict = bool(
            len(external) > 1
            or (p_vals and c_vals and json.dumps(p_vals[0]) != json.dumps(c_vals[0]))
            or (f_vals and c_vals and json.dumps(f_vals[0]) != json.dumps(c_vals[0]))
        )
        if conflict:
            resolved, sclass, policy = None, "unresolved", "conflict: agent must adjudicate with evidence"
        elif p_vals:
            resolved, sclass, policy = p_vals[0], "paper_explicit", "paper value wins"
        elif f_vals:
            resolved, sclass, policy = f_vals[0], "code_inferred", "config/supplement value; cite file:line"
        elif c_vals:
            resolved, sclass, policy = c_vals[0], "code_inferred", "code default; NOT a paper claim"
        else:
            resolved, sclass, policy = None, "self_set", "choose deliberately and record why"
        rows.append({
            "name": key,
            "paper_values": p_vals, "config_values": f_vals, "code_defaults": c_vals,
            "paper_evidence": p_e[:3], "config_evidence": f_e[:3], "code_evidence": c_e[:3],
            "resolved": resolved, "source_class": sclass, "conflict": conflict,
            "resolution_policy": policy,
            "agent_action": "confirm source_class and set resolved; add change_records entry",
        })
    resolved_params = {r["name"]: r["resolved"] for r in rows if r["resolved"] is not None}
    return {
        "generated_at": now_iso(),
        "policy": "paper_explicit > supplement/config > code default > self_set. "
                  "Conflicts are NEVER auto-resolved. Tolerance must be declared before comparison.",
        "n_parameters": len(rows),
        "n_conflicts": sum(1 for r in rows if r["conflict"]),
        "executable_parameter_table": rows,
        "resolved_params": resolved_params,
        "note": "Values come from regex over ACTUAL files; review each evidence locator before use.",
    }
