"""通用科研实验注册表引擎 (generic science experiment registry).

本模块**不认识任何具体学科**。它只理解一份「实验注册表」的通用结构，并提供
四个通用工具：list / get / rerun / audit。

设计目标（回应「格物是通用科研助手，coal 只是一个例子」）：
  * 机制与学科彻底解耦。coal（煤热值 MIL）只是「注册进来的一个领域包」：
    它提供 (a) 自己的计算脚本 ``coal_infer.py``，(b) 一份 registry JSON
    （``registry/coal_mil.json``）描述其实验与「如何重算」。
  * 接入新学科（蛋白质折叠、气候模型、基因组学…）只需：放一份新的
    ``registry/<domain>.json`` + 该领域的计算脚本，本引擎零改动即可驱动。

注册表通用 schema（每个 registry 文件）：
  {
    "domain": "coal-mil",                 # 领域包标识
    "domain_label": "人类可读的领域名",
    "schema_version": 1,
    "experiments": [
      {
        "id": "our_hybrid",
        "name": "...",
        "category": "ours|baseline|comparison|ablation",
        "config": {...},                  # 实验配置（自由结构，便于追溯）
        "metrics": {                      # 论文中引用的聚合指标（台账）
          "rmse_kcal_mean": 214.5699, ... # 允许 null（未记录/未复现）
        },
        "source": "summary_json | original_script:...",
        "source_of_truth": "相对领域项目根的真相路径",
        "reproducibility": "realizable_by_gewu | verifiable_via_summary | requires_original_script",
        "rerun": {                        # 通用重算规范（可选）
          "type": "cli",                  # 当前支持 cli；none 表示不可由格物重算
          "python": "coal-torch",         # 命名解释器（见 _resolve_python）
          "script": "gewu/mcp/coal_infer.py",  # 相对仓库根的脚本
          "args": ["cv-summary"],
          "metrics_path": "official_summary",  # 输出 JSON 中取指标的子路径（""=根）
          "key_map": {"rmse_kcal_mean": "mean_plsr_rmse"},  # 注册键 <- 输出键（支持点路径）
          "tolerance": {"rmse_kcal_mean": 1.0},             # 一致性阈值
          "timeout": 600
        }
      }, ...
    ]
  }

rerun 的两种语义：
  * realizable_by_gewu / verifiable_via_summary  → 必须配 type:"cli"，引擎真跑并交叉校验。
  * requires_original_script                     → type:"none"，引擎只登记+诚实标注复现路径。

所有指标交叉校验都以「领域脚本真实输出」为准，杜绝手抄漂移（兼 P0-2）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("sci-exp")

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))          # gewu-sciagent/
_REGISTRY_DIR = os.environ.get(
    "GEWU_REGISTRY_DIR", os.path.join(_HERE, "registry")
)


# --------------------------------------------------------------------------
# 加载
# --------------------------------------------------------------------------
def load_experiments() -> dict[str, dict]:
    """读取 registry/ 下所有 JSON，扁平化为 {id: {domain, ...entry}}。"""
    experiments: dict[str, dict] = {}
    if not os.path.isdir(_REGISTRY_DIR):
        return experiments
    for fn in sorted(os.listdir(_REGISTRY_DIR)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(_REGISTRY_DIR, fn)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        domain = data.get("domain", os.path.splitext(fn)[0])
        for e in data.get("experiments", []):
            rec = dict(e)
            rec["domain"] = domain
            rec["domain_label"] = data.get("domain_label", domain)
            experiments[rec["id"]] = rec
    return experiments


def gewu_commit() -> str:
    """读取格物仓库当前 commit，作为所有实验的代码锚点（通用，与学科无关）。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT,
            capture_output=True, text=True, timeout=10,
            stdin=subprocess.DEVNULL,  # 不继承 MCP 的 stdin 管道，否则子进程挂到 timeout
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


# --------------------------------------------------------------------------
# 通用解释器解析（领域包可用命名 venv，无需硬编码绝对路径）
# --------------------------------------------------------------------------
def _resolve_python(name: str | None) -> str:
    name = (name or "").strip()
    if name in ("", "system"):
        return sys.executable
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".workbuddy", "binaries", "python", "envs", name, "Scripts", "python.exe"),
        os.path.join(home, ".workbuddy", "binaries", "python", "envs", name, "bin", "python"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    envk = f"GEWU_PYTHON_{name.upper()}"
    if os.environ.get(envk):
        return os.environ[envk]
    return sys.executable


def _extract(obj: Any, dotted: str) -> Any:
    if not dotted:
        return obj
    cur: Any = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


# --------------------------------------------------------------------------
# 通用重算（cli 类型）：运行领域脚本 → 解析 JSON → key_map → 一致性校验
# --------------------------------------------------------------------------
def _run_cli(spec: dict, timeout_default: int = 1800) -> dict:
    py = _resolve_python(spec.get("python"))
    script = spec.get("script")
    if not script:
        return {"error": "rerun.spec 缺少 script"}
    script_path = script if os.path.isabs(script) else os.path.join(_REPO_ROOT, script)
    if not os.path.exists(script_path):
        return {"error": f"rerun 脚本不存在: {script_path}"}
    argv = [py, script_path, *(spec.get("args", []))]
    cwd = spec.get("cwd")
    cwd = os.path.join(_REPO_ROOT, cwd) if cwd else _REPO_ROOT
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8",
            cwd=cwd, timeout=spec.get("timeout", timeout_default), env=env,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"rerun 超时(>{spec.get('timeout', timeout_default)}s)"}
    except FileNotFoundError as e:
        return {"error": f"解释器/脚本不可用: {e}"}
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        return {"error": "rerun 命令非零退出或空输出",
                "returncode": proc.returncode, "stderr": (proc.stderr or "")[-1500:]}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"error": "rerun 输出非 JSON", "raw": out[-800:]}


def _cross_check(entry: dict, parsed: dict) -> dict:
    spec = entry.get("rerun", {}) or {}
    metrics_path = spec.get("metrics_path", "")
    key_map = spec.get("key_map", {})
    tol = spec.get("tolerance", {})
    metrics_block = _extract(parsed, metrics_path) or {}
    recorded = entry.get("metrics", {})

    diffs: dict[str, dict] = {}
    all_ok = True
    extra: dict[str, Any] = {}
    for mkey, rval in recorded.items():
        if rval is None:
            continue
        out_key = key_map.get(mkey)
        if out_key is None:
            continue  # 该指标不由 rerun 产出，跳过交叉校验
        aval = _extract(parsed, out_key) if "." in out_key else metrics_block.get(out_key)
        if aval is None:
            diffs[mkey] = {"recorded": rval, "actual": None, "ok": False}
            all_ok = False
            continue
        t = float(tol.get(mkey, 0.0))
        ok = abs(float(aval) - float(rval)) <= t
        diffs[mkey] = {
            "recorded": rval, "actual": aval,
            "abs_diff": round(abs(float(aval) - float(rval)), 6), "ok": ok,
        }
        all_ok = all_ok and ok
    # 输出中、但不参与校验的「标量」额外指标（透明展示，便于人工核对；
    # 剔除列表/字典/字符串等非标量噪音，如 per_fold / official_summary）
    for k, v in metrics_block.items():
        if k in key_map.values():
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            extra[k] = v
    return {"diffs": diffs, "all_consistent": all_ok, "extra_metrics": extra}


# --------------------------------------------------------------------------
# 通用工具实现
# --------------------------------------------------------------------------
def list_experiments(domain: str | None = None) -> dict:
    exps = load_experiments()
    items = list(exps.values())
    if domain:
        items = [e for e in items if e.get("domain") == domain]
    out = []
    for e in items:
        m = e.get("metrics", {})
        out.append({
            "id": e["id"], "domain": e.get("domain"), "name": e["name"],
            "category": e.get("category"), "reproducibility": e.get("reproducibility"),
            "rmse_kcal_mean": m.get("rmse_kcal_mean"),
            "rmse_kcal_std": m.get("rmse_kcal_std"),
            "r2_mean": m.get("r2_mean"),
        })
    return {
        "schema_version": 1, "gewu_commit": gewu_commit(),
        "registry_dir": _REGISTRY_DIR, "n_experiments": len(out), "experiments": out,
    }


def get_experiment(experiment_id: str) -> dict:
    exps = load_experiments()
    e = exps.get(experiment_id)
    if e is None:
        return {"status": "not_found", "experiment_id": experiment_id}
    rep = e.get("reproducibility")
    live_available = rep in ("realizable_by_gewu", "verifiable_via_summary")
    merged = dict(e)
    merged["gewu_commit"] = gewu_commit()
    merged["live_metrics_available"] = live_available
    merged["status"] = "ok"
    return merged


def rerun_experiment(experiment_id: str) -> dict:
    exps = load_experiments()
    e = exps.get(experiment_id)
    if e is None:
        return {"status": "not_found", "experiment_id": experiment_id}
    rep = e.get("reproducibility")
    base = {
        "experiment_id": experiment_id, "name": e["name"], "domain": e.get("domain"),
        "reproducibility": rep, "gewu_commit": gewu_commit(),
    }
    if rep in ("realizable_by_gewu", "verifiable_via_summary"):
        spec = e.get("rerun") or {}
        if spec.get("type") != "cli":
            return {**base, "status": "error", "detail": "缺少 cli 重算规范"}
        parsed = _run_cli(spec)
        if "error" in parsed:
            return {**base, "status": "error", "detail": parsed["error"],
                    "stderr": parsed.get("stderr"), "raw": parsed.get("raw")}
        cc = _cross_check(e, parsed)
        return {**base, "status": "reproduced",
                "recomputed": cc["diffs"], "extra_metrics": cc["extra_metrics"],
                "all_consistent": cc["all_consistent"]}
    # requires_original_script：格物不复制数据，仅登记+诚实标注
    return {
        **base, "status": "needs_original_script",
        "detail": "该实验由领域原始项目脚本产出，格物不复制数据/权重，仅登记追溯与复现路径",
        "source_of_truth": e.get("source_of_truth"),
        "rerun_hint": e.get("rerun_hint"),
        "registered_metrics": e.get("metrics"),
        "notes": e.get("notes"),
    }


def audit_experiments(domain: str | None = None) -> dict:
    """校验所有可复现实验的指标漂移（兼 P0-2，与学科无关）。"""
    exps = load_experiments()
    commit = gewu_commit()
    rows = []
    for e in exps.values():
        if domain and e.get("domain") != domain:
            continue
        rep = e.get("reproducibility")
        if rep in ("realizable_by_gewu", "verifiable_via_summary"):
            r = rerun_experiment(e["id"])
            rows.append({
                "id": e["id"], "domain": e.get("domain"), "reproducibility": rep,
                "status": r.get("status"), "all_consistent": r.get("all_consistent"),
                "recomputed": r.get("recomputed"),
            })
        else:
            rows.append({
                "id": e["id"], "domain": e.get("domain"), "reproducibility": rep,
                "status": "registered_only", "all_consistent": None,
                "note": "需领域原始项目脚本复现，格物仅登记",
            })
    n_drift = sum(1 for x in rows if x.get("all_consistent") is False)
    return {
        "gewu_commit": commit, "n_experiments": len(rows),
        "n_drift": n_drift, "all_consistent": n_drift == 0, "rows": rows,
    }


# --------------------------------------------------------------------------
# MCP 工具（通用，无任何学科关键字）
# --------------------------------------------------------------------------
@mcp.tool()
def list_experiments_tool(domain: str = "") -> dict:
    """列出实验注册表中的所有实验（通用）。

    返回每条实验的 id / 所属领域 domain / 名称 / 类别 / 可复现性 / 关键指标，
    并锚定当前格物仓库 commit。domain 可过滤（如 'coal-mil'）；留空列出全部领域。
    这是所有被引用实验数字的「台账」——每条都可追溯到 source of truth 与复现路径。
    """
    return list_experiments(domain.strip() or None)


@mcp.tool()
def get_experiment_tool(experiment_id: str) -> dict:
    """查看某个实验的完整元数据（通用）：配置、指标、来源、复现路径、当前 commit。

    对可复现实验会标注 live_metrics_available=true，调用 rerun_experiment 可取得实时指标。
    用于回答「论文里这个 X±Y 是怎么来的、能否复现」。
    """
    if not experiment_id or not str(experiment_id).strip():
        return {"status": "error", "detail": "experiment_id 不能为空"}
    return get_experiment(str(experiment_id).strip())


@mcp.tool()
def rerun_experiment_tool(experiment_id: str) -> dict:
    """按配置重跑/校验某个实验（通用核心）。

    - realizable_by_gewu / verifiable_via_summary：真跑领域计算脚本，与注册台账交叉校验，
      返回重算值/记录值/绝对差/是否一致——这是「论文核心数字可复现」的通用证明机制。
    - requires_original_script：不复制数据，返回复现命令与已登记指标，诚实标注。
    计算量取决于领域脚本（如 5 折真推理），请耐心等待。
    """
    if not experiment_id or not str(experiment_id).strip():
        return {"status": "error", "detail": "experiment_id 不能为空"}
    return rerun_experiment(str(experiment_id).strip())


@mcp.tool()
def audit_experiments_tool(domain: str = "") -> dict:
    """审计所有可复现实验的指标漂移（通用，兼 P0-2）。

    对所有 realizable/verifiable 实验实际重跑或读源码，报告每条是否与注册表一致、
    是否存在指标漂移。返回 all_consistent 与 n_drift。运行较重（含领域计算），请耐心等待。
    """
    return audit_experiments(domain.strip() or None)


if __name__ == "__main__":
    mcp.run()
