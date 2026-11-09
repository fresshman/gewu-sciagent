"""把外部煤项目的组件级消融聚合结果落成**可入库**的仓库快照。

边界（重要）
------------
原始光谱、模型权重、逐样本预测都在用户本机的未发表项目里，**不复制、不入库**。
本脚本只读外部项目 ``outputs/abl_component/ablation_summary.json``（已是聚合量：
逐折 RMSE / 均值 / 配对检验），校验结构后写入
``docs/verification/ablation_component.json``，并记录 sha256 与来源。

为什么需要这一步
--------------
论文 §消融 此前只能写「组件级消融需重训，未覆盖」。重训完成后，若把结论直接手抄进
.tex，就没有任何可核对的链路。这里固定一条：**仓库内每个数字都必须能追到一个带指纹的
聚合文件**，且该文件由外部产出计算而来，不允许手改。

用法
----
    python scripts/ablation_ingest.py            # 落库 + 打印摘要
    python scripts/ablation_ingest.py --check    # 只校验，不写文件
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(REPO, "docs", "verification", "ablation_component.json")
HINT = os.path.join(REPO, ".coal_project_root")
EXPECTED_ARMS = ("base", "no_film", "no_supcon", "no_huber")
N_FOLDS = 5


def resolve_coal_root() -> str:
    env = os.environ.get("COAL_PROJECT_ROOT", "").strip()
    if env and os.path.isdir(env):
        return env.rstrip("/\\")
    if os.path.exists(HINT):
        v = open(HINT, encoding="utf-8").read().strip()
        if v and os.path.isdir(v):
            return v.rstrip("/\\")
    return ""


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def validate(doc: dict) -> list[str]:
    """返回问题列表；空列表表示通过。"""
    problems: list[str] = []
    arms = doc.get("arms") or {}
    for arm in EXPECTED_ARMS:
        if arm not in arms:
            problems.append(f"缺少臂 {arm}")
            continue
        pf = arms[arm].get("per_fold_rmse") or []
        if len(pf) != N_FOLDS:
            problems.append(f"{arm} 折数 {len(pf)} != {N_FOLDS}")
    if "base" in arms:
        plsr = arms["base"].get("per_fold_plsr_rmse") or []
        if len(plsr) != N_FOLDS:
            problems.append("base 的 per_fold_plsr_rmse 折数不足")
        for arm, a in arms.items():
            p = a.get("per_fold_plsr_rmse") or []
            if len(p) == len(plsr) and any(abs(x - y) > 1e-6 for x, y in zip(p, plsr)):
                problems.append(f"{arm} 的 PLSR 逐折值与 base 不一致（输入漂移）")
    for arm, a in arms.items():
        if arm == "base":
            continue
        if "vs_base" not in a:
            problems.append(f"{arm} 缺少 vs_base 配对结果")
    return problems


HANDOFF4 = os.path.join(
    REPO, "openclaw", "workspace", "agents", "gewu-improver", "handoff_4_improver.json"
)
REGISTRY = os.path.join(REPO, "gewu", "mcp", "registry", "coal_mil.json")


def check_handoff(doc: dict) -> list[str]:
    """快照与 handoff_4 的组件消融摘要必须一致（防两处数字漂移）。"""
    if not os.path.exists(HANDOFF4):
        return []
    with open(HANDOFF4, encoding="utf-8") as f:
        h = json.load(f)
    block = (h.get("ablation_study") or {}).get("component_ablation") or {}
    if not block:
        return ["handoff_4 缺少 ablation_study.component_ablation（快照已入库但未同步）"]
    problems: list[str] = []
    arms_h = {a["arm"]: a for a in block.get("arms", [])}
    for arm, a in doc["arms"].items():
        ha = arms_h.get(arm)
        if ha is None:
            problems.append(f"handoff_4 缺少臂 {arm}")
            continue
        if abs(float(ha["mean_rmse_kcal_kg"]) - float(a["mean_rmse"])) > 1e-4:
            problems.append(
                f"{arm} 均值不一致：快照 {a['mean_rmse']} vs handoff_4 {ha['mean_rmse_kcal_kg']}"
            )
        if "vs_base" in a:
            if abs(float(ha["delta_vs_base_kcal_kg"]) - float(a["vs_base"]["mean_delta"])) > 1e-4:
                problems.append(f"{arm} 差值不一致：快照 {a['vs_base']['mean_delta']} vs handoff_4 {ha['delta_vs_base_kcal_kg']}")
    return problems


def check_registry(doc: dict) -> list[str]:
    """快照与实验注册表必须一致（数字共三处：快照 / handoff_4 / 注册表）。"""
    if not os.path.exists(REGISTRY):
        return ["注册表 gewu/mcp/registry/coal_mil.json 不存在"]
    with open(REGISTRY, encoding="utf-8") as f:
        reg = json.load(f)
    entries = {e.get("id"): e for e in reg.get("experiments", [])}
    problems: list[str] = []
    for arm, a in doc["arms"].items():
        e = entries.get("abl_comp_" + arm)
        if e is None:
            problems.append(f"注册表缺少条目 abl_comp_{arm}")
            continue
        got = (e.get("metrics") or {}).get("rmse_kcal_mean")
        if got is None or abs(float(got) - float(a["mean_rmse"])) > 1e-4:
            problems.append(f"abl_comp_{arm} 均值不一致：快照 {a['mean_rmse']} vs 注册表 {got}")
        got_sd = (e.get("metrics") or {}).get("rmse_kcal_std")
        if got_sd is None or abs(float(got_sd) - float(a["std_rmse"])) > 1e-4:
            problems.append(f"abl_comp_{arm} 标准差不一致：快照 {a['std_rmse']} vs 注册表 {got_sd}")
        pf = (e.get("metrics") or {}).get("per_fold_rmse_kcal") or []
        if len(pf) != len(a["per_fold_rmse"]):
            problems.append(f"abl_comp_{arm} 折数不一致：快照 {len(a['per_fold_rmse'])} vs 注册表 {len(pf)}")
        else:
            for i, (x, y) in enumerate(zip(pf, a["per_fold_rmse"])):
                if abs(float(x) - float(y)) > 1e-4:
                    problems.append(f"abl_comp_{arm} fold{i} 不一致：快照 {y} vs 注册表 {x}")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="消融聚合结果入库")
    ap.add_argument("--check", action="store_true", help="只校验，不写入")
    ap.add_argument("--src", default="", help="外部 ablation_summary.json 路径（默认按 .coal_project_root 解析）")
    args = ap.parse_args(argv)

    src = args.src
    if not src:
        root = resolve_coal_root()
        if not root:
            print("找不到外部煤项目根目录（设 COAL_PROJECT_ROOT 或仓库根 .coal_project_root）", file=sys.stderr)
            return 2
        src = os.path.join(root, "coal-mil", "outputs", "abl_component", "ablation_summary.json")
    if not os.path.exists(src):
        print(f"聚合文件不存在：{src}\n先跑 aggregate_component_ablation.py", file=sys.stderr)
        return 2

    with open(src, encoding="utf-8") as f:
        doc = json.load(f)

    problems = validate(doc)
    if problems:
        print("校验失败：", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    digest = sha256_of(src)
    print(f"校验通过（{len(doc['arms'])} 臂 × {N_FOLDS} 折），源文件 sha256={digest[:16]}")
    for arm in EXPECTED_ARMS:
        a = doc["arms"][arm]
        vb = a.get("vs_base") or {}
        extra = ""
        if vb:
            extra = (f"  Δ={vb['mean_delta']:+.2f} ({vb['rel_pct']:+.2f}%)  "
                     f"方向一致={vb['all_same_direction']}  p={vb.get('p')}")
        print(f"  {arm:<10} {a['mean_rmse']:>8.2f} ± {a['std_rmse']:.2f}{extra}")

    if args.check:
        if os.path.exists(TARGET):
            with open(TARGET, encoding="utf-8") as f:
                snap = json.load(f)
            drift = check_handoff(snap)
            if drift:
                print("与 handoff_4 不一致：", file=sys.stderr)
                for p in drift:
                    print(f"  - {p}", file=sys.stderr)
                return 1
            print("与 handoff_4 的组件消融摘要一致")
            reg = check_registry(snap)
            if reg:
                print("与实验注册表不一致：", file=sys.stderr)
                for p in reg:
                    print(f"  - {p}", file=sys.stderr)
                return 1
            print("与实验注册表 coal_mil.json 一致（4 条 abl_comp_*）")
        return 0

    payload = {
        "schema": "gewu.ablation.component.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": {
            "produced_by": "coal-mil/scripts/run_component_ablation.py",
            "aggregated_by": "coal-mil/scripts/aggregate_component_ablation.py",
            "source_relpath": "coal-mil/outputs/abl_component/ablation_summary.json",
            "source_sha256": digest,
            "held_out": "原始光谱、模型权重、逐样本预测未入库（未发表资产，留在作者本机）",
        },
        **{k: doc[k] for k in ("convention", "folds", "plsr_check", "arms") if k in doc},
    }
    if "reference_archive" in doc:
        payload["reference_archive"] = doc["reference_archive"]

    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    with open(TARGET, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n已写入 {os.path.relpath(TARGET, REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
