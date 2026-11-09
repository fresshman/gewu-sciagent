"""七阶段最小课题编排（零外部数据依赖）。

这条链路的定位
--------------
真实课题（``output/documents/coal_report``）证明的是**方法有效**，但它依赖未发表的
私有数据与权重，评审无法自行执行。本模块补的是另一半：一条**任何人 clone 后都能
从零跑完**的最小链路，用来回答"你的系统真的能自己跑完七阶段吗"。

它跑什么
--------
    ① 定方向   从本地知识种子生成可检验假设（不联网）
    ② 读文献   检索 3 篇方法背景文献并做 D1 存在性核验（无网时诚实降级）
    ③ 复现     合成 70 个 bag → 袋均谱 PLSR 基线 5 折 CV
    ④ 改进     逐实例定标 + 池化 + 强度上尾残差 → 三臂消融 + 配对检验
    ⑤ 写论文   由结果字典生成 main.tex 与逐条可回溯的 claims.json
    ⑥ 投稿     候选期刊（等级来源显式标注；无凭据时不得称"已核验"）
    ⑦ 沉淀     SKILL.md / MEMORY.md / 注册表条目 / 复现说明

它不做什么（必须说清）
----------------------
* 不让大模型自由发挥：本链路由确定性脚本编排，**不是** OpenClaw 多智能体自主运行；
  它验证的是"工具链与数据契约"，不是"模型决策质量"。
* 不产生真实煤样结论：所有数值来自合成光谱。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from . import mil_lite, report, synth

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO / "output" / "min_case"
AGENT_DIRS = {
    1: "gewu-director",
    2: "gewu-ideation",
    3: "gewu-reproduction",
    4: "gewu-improver",
    5: "gewu-writer",
    6: "gewu-publication",
    7: "gewu-distillation",
}
HANDOFF_NAMES = {
    1: "handoff_1_direction.json",
    2: "handoff_2_litreview.json",
    3: "handoff_3_repro.json",
    4: "handoff_4_improver.json",
    5: "handoff_5_writer.json",
    6: "handoff_6_publication.json",
    7: "handoff_7_distillation.json",
}
STAGE_NAMES = {1: "定方向", 2: "读论文找 idea", 3: "复现", 4: "改进",
               5: "写论文", 6: "发表追踪", 7: "沉淀"}


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


def _handoff(stage: int, status: str, title: str, inputs: list[str],
             outputs: list[str], **blocks) -> dict:
    h = {
        "stage": stage,
        "stage_name": STAGE_NAMES[stage],
        "status": status,
        "title": title,
        "created_by": f"{AGENT_DIRS[stage]} (min-case harness)",
        "created_at": _now(),
        "inputs": inputs,
        "outputs": outputs,
        "run_mode": "deterministic_script",
        "data_kind": "synthetic",
    }
    h.update(blocks)
    if stage < 7:
        h["next"] = AGENT_DIRS[stage + 1]
        h["next_input"] = HANDOFF_NAMES[stage]
    return h


# --------------------------------------------------------------------------
# 各阶段
# --------------------------------------------------------------------------
def stage1_direction(out: Path) -> dict:
    """定方向：把"MIL 是否真的能补回被袋均抹掉的颗粒异质性"写成一个可证伪假设。

    这里不调用大模型，而是用**显式的可证伪形式**落盘——比一句自然语言假设更有用：
    它同时规定了检验方式与失败判据，后续阶段必须按此判定。
    """
    hypothesis = {
        "id": "H1",
        "statement": "对同一 bag 的多条实例光谱先逐实例定标再池化，"
                     "其热值预测误差低于先把光谱平均再回归。",
        "mechanism": "袋均使颗粒尺度因子 a_i 的均值趋近 1，异质性 h 被稀释；"
                     "实例级定标保留 a_i，其池化上尾统计量与 h 单调相关。",
        "falsifiable_by": "5 折 CV 上 MIL 臂 RMSE 不显著低于 PLSR 基线即证伪",
        "success_criterion": "配对 t 检验 p<0.05 且五折方向一致",
        "known_confound": "若增益全部来自残差模型而非池化，则假设的机制解释不成立",
    }
    path = out / "agents" / AGENT_DIRS[1] / "hypothesis.json"
    _dump(path, hypothesis)
    return _handoff(
        1, "completed", "最小课题：MIL 能否补回袋均抹掉的颗粒异质性",
        inputs=[], outputs=[_rel(path)],
        hypothesis=hypothesis,
        scope="合成数据 + 合成机制；不涉及外部私有数据",
        success_criteria=["链路七阶段全部产出非空", "假设按预注册判据判定（无论成立与否）"],
    )


def stage2_litreview(out: Path, offline: bool) -> dict:
    """读文献：先落盘待核验清单，再尝试 D1 核验；失败必须降级而非伪造。"""
    refs_dir = out / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    check = [
        {"id": r["key"], "arxiv_id": r["arxiv_id"] or None,
         "doi": r["doi"] or None, "title": r["title"]}
        for r in report.REFERENCES
    ]
    src = refs_dir / "refs_check.json"
    _dump(src, check)

    verdict_path = refs_dir / "refs_verified.json"
    d1 = {"status": "not_run", "reason": "未执行", "tool": "gewu/mcp/verify_papers.py"}
    if offline:
        d1["reason"] = "以 --offline 运行，跳过联网核验"
    else:
        proc = None
        try:
            proc = subprocess.run(
                [sys.executable, str(REPO / "gewu" / "mcp" / "verify_papers.py"),
                 "--input", str(src), "--output", str(verdict_path)],
                cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
                timeout=180, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                stdin=subprocess.DEVNULL,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            d1["reason"] = f"核验未完成：{type(e).__name__}"
        if proc is not None and proc.returncode == 0 and verdict_path.is_file():
            try:
                v = json.loads(verdict_path.read_text(encoding="utf-8"))
                # verify_papers 的条目字段名为 papers；兼容旧的 results
                items = v.get("results") or v.get("papers") or []
                n = len(items)
                ok = sum(1 for r in items
                         if str(r.get("status", "")).lower() in ("verified", "pass", "ok"))
                if n and ok == n:
                    d1.update({
                        "status": "verified",
                        "reason": "",
                        "verdict": v.get("verdict"),
                        "n_checked": n,
                        "n_verified": ok,
                        "hallucination_rate": v.get("hallucination_rate"),
                        "artifact": _rel(verdict_path),
                        "method_by_ref": {str(r.get("id")): r.get("method") for r in items},
                    })
                else:
                    d1.update({
                        "status": "partial" if ok else "not_verified",
                        "reason": f"{ok}/{n} 条通过核验",
                        "verdict": v.get("verdict"),
                        "n_checked": n,
                        "n_verified": ok,
                        "artifact": _rel(verdict_path),
                    })
            except json.JSONDecodeError:
                d1["reason"] = "核验输出非 JSON"
        elif proc is not None:
            d1["reason"] = (f"核验命令失败 rc={proc.returncode}："
                            f"{(proc.stderr or '')[-200:].strip()}")

    return _handoff(
        2, "completed" if d1["status"] == "verified" else "completed_with_caveat",
        "方法背景文献检索与 D1 存在性核验",
        inputs=[HANDOFF_NAMES[1]], outputs=[_rel(src)] + (
            [_rel(verdict_path)] if verdict_path.is_file() else []),
        references=[{"key": r["key"], "title": r["title"], "doi": r["doi"],
                     "arxiv": r["arxiv_id"], "role": "方法背景，不用于支持合成实验结论"}
                    for r in report.REFERENCES],
        d1_citation_verification=d1,
        note="仅检索方法背景文献；本课题为合成数据演示，不用文献结论支撑实验数值",
    )


def _write_predictions(out: Path, res: dict) -> list[str]:
    paths = []
    by_fold: dict[int, list[dict]] = {}
    for row in res["predictions"]:
        by_fold.setdefault(row["fold"], []).append(row)
    for f, rows in sorted(by_fold.items()):
        p = out / "model" / f"fold{f}" / "predictions.json"
        _dump(p, rows)
        paths.append(_rel(p))
    return paths


def _summary_block(res: dict, n_bags: int, n_inst: int) -> dict:
    return {
        "domain": "demo_synth",
        "dataset": {
            "n_bags": n_bags,
            "n_instances": n_inst,
            "n_folds": len(res["per_fold"]),
            "kind": "synthetic",
            "note": "合成光谱，不代表真实煤样精度",
        },
        "convention": res["convention"],
        "summary": res["summary"],
        "per_fold": res["per_fold"],
        "paired_tests": res["paired_tests"],
        "improvement_pct": res["improvement_pct"],
        "beta_selected": res["beta_selected"],
        "ridge_alphas": res["ridge_alphas"],
    }


def stage3_reproduce(out: Path, res: dict, n_bags: int, n_inst: int, seed: int) -> dict:
    s = res["summary"]["plsr"]
    pred_paths = _write_predictions(out, res)
    return _handoff(
        3, "completed", "袋均谱 PLSR 基线 5 折复现（合成数据）",
        inputs=[HANDOFF_NAMES[2]], outputs=pred_paths,
        baseline_metrics={
            "n_folds": len(res["per_fold"]),
            "n_per_fold": sorted({r["n"] for r in res["per_fold"]}),
            "n_bags": n_bags,
            "n_instances": n_inst,
            "mean_rmse": s["rmse_mean"],
            "std_rmse": s["rmse_std"],
            "mean_r2": s["r2_mean"],
            "unit": "kcal/kg",
            "per_fold_rmse": s["per_fold_rmse"],
        },
        repro_lock={
            "data": "gewu/demo/synth.py（确定性生成，种子固定）",
            "split": "5 折按 bag 切分，见 data/split.json",
            "model": "PLSR(n_components<=6) on 64-bin 袋均谱",
            "metric_caliber": "每折算 RMSE，对 5 折取均值/总体标准差(ddof=0)",
            "random_seed": seed,
        },
        note="该基线即「把 bag 拍平成一个样本」的经典做法，作为后续改进的参照",
    )


def stage4_improve(out: Path, res: dict) -> dict:
    s = res["summary"]
    t = res["paired_tests"]["hybrid_vs_plsr"]
    deltas = {
        "rmse_delta": round(s["plsr"]["rmse_mean"] - s["hybrid"]["rmse_mean"], 4),
        "rmse_delta_pct": res["improvement_pct"],
        "mil_only_delta_pct": round(
            (s["plsr"]["rmse_mean"] - s["mil"]["rmse_mean"]) / s["plsr"]["rmse_mean"] * 100, 4),
        "residual_delta_pct": round(
            (s["mil"]["rmse_mean"] - s["hybrid"]["rmse_mean"]) / s["plsr"]["rmse_mean"] * 100, 4),
    }
    per_fold_cmp = [
        {
            "fold": r["fold"],
            "n": r["n"],
            "plsr_rmse": r["plsr"]["rmse"],
            "mil_rmse": r["mil"]["rmse"],
            "hybrid_rmse": r["hybrid"]["rmse"],
            "delta_vs_baseline": round(r["plsr"]["rmse"] - r["hybrid"]["rmse"], 4),
            "beta": r["beta"],
            "ridge_alpha": r["ridge_alpha"],
        }
        for r in res["per_fold"]
    ]
    ablation = {
        "status": "completed",
        "arms": [
            {"id": arm, "label": s[arm]["label"],
             "rmse_mean": s[arm]["rmse_mean"], "rmse_std": s[arm]["rmse_std"],
             "r2_mean": s[arm]["r2_mean"]}
            for arm in ("plsr", "mil", "hybrid")
        ],
        "isolation": "三臂共享同一折划分与同一批特征，仅改变「定标方式/池化/残差」",
        "pooling_finding": {
            "betas": res["beta_selected"],
            "reading": "β=0 表示内层 CV 选中均值池化；此时增益来自逐实例定标与残差，"
                       "不应声称 LSE 高阶池化有贡献",
        },
        "not_covered": [
            "组件级消融（逐个去掉 max/p90/std 特征）未做，样本量 56 下易过拟合，故留作后续",
            "未做真实数据上的验证（需外部私有数据，非本课题范围）",
        ],
    }
    return _handoff(
        4, "completed", "改进：逐实例定标 + 池化 + 强度上尾残差（含三臂消融）",
        inputs=[HANDOFF_NAMES[3]], outputs=[_rel(out / "model" / "summary.json")],
        improvement_analysis={
            "baseline": {"arm": "plsr", **{k: s["plsr"][k] for k in ("rmse_mean", "rmse_std", "r2_mean")}},
            "proposed": {"arm": "hybrid", **{k: s["hybrid"][k] for k in ("rmse_mean", "rmse_std", "r2_mean")}},
            "delta": deltas,
            "per_fold_comparison": per_fold_cmp,
            "statistical_significance": t,
            "pooled_oof": {"plsr": s["plsr"]["pooled"], "hybrid": s["hybrid"]["pooled"]},
            "observation": f"五折方向{'一致' if t['all_same_direction'] else '不一致'}；"
                           f"逐折 Δ={t['deltas']}",
        },
        ablation_study=ablation,
        failure_audit={
            "verdict": "PASS_WITH_NOTES",
            "notes": [
                "本课题为合成数据，不可外推绝对精度",
                "β 由内层 CV 决定，若为 0 则不得宣称 LSE 有效",
                "假设 H1 按预注册判据判定，结论写入 handoff_4 与论文，不因结果不利而修改判据",
            ],
        },
        hypothesis_verdict={
            "id": "H1",
            "supported": bool(t.get("p") is not None and t["p"] < 0.05 and t["all_same_direction"]),
            "criterion": "p<0.05 且五折方向一致",
            "observed": {"p": t.get("p"), "all_same_direction": t["all_same_direction"]},
            "caveat": "增益中残差部分与池化部分未完全解耦，机制解释仅为「与之一致」，不作因果断言",
        },
    )


def _compile_pdf(tex_path: Path) -> dict:
    """真实调用 LaTeX 引擎编译 tex。

    找不到引擎时**如实标注未编译**（``pdf_compiled=False`` + 原因），不伪造成功；
    编译成功后把 TeX 日志里的 error / overfull 计数一并带出，供校验层核对。
    """
    from ..latex_build import build as build_pdf

    r = build_pdf(tex_path)
    status: dict = {
        "pdf_compiled": bool(r.get("ok")),
        "engine": r.get("engine"),
        "duration_s": r.get("duration_s"),
    }
    if r.get("ok"):
        status.update(
            {
                "pdf": _rel(Path(r["pdf"])),
                "pdf_bytes": r.get("pdf_bytes"),
                "log_errors": len(r["log"]["errors"]),
                "missing_glyphs": len(r["log"]["missing_glyphs"]),
                "overfull_hbox": r["log"]["overfull_hbox"],
                "note": "由 gewu.latex_build 真实编译；计数取自 TeX 日志",
            }
        )
        if r["log"]["overfull_hbox"]:
            status["note"] += "（存在 overfull：排版有溢出，内容未丢失）"
    else:
        status.update(
            {
                "code": r.get("status"),
                "reason": r.get("reason"),
                "log_errors": len(r.get("log", {}).get("errors", []) or []),
            }
        )
    return status


def stage5_write(out: Path, res: dict, n_bags: int, n_inst: int, refs_status: str) -> dict:
    tex = report.render_tex(res, n_bags, n_inst, time.strftime("%Y-%m-%d"))
    tex_path = out / "report" / "main.tex"
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    tex_path.write_text(tex, encoding="utf-8")

    claims = report.claim_list(res, n_bags, n_inst)
    claims_path = out / "report" / "claims.json"
    _dump(claims_path, claims)
    _dump(out / "report" / "refs.json", report.REFERENCES)

    # D3 引用 lint：cite 键必须都有 bibitem，反之亦然
    from . import lint_tex

    lint = lint_tex.lint(tex)
    compilation = _compile_pdf(tex_path)

    d1 = {
        "status": "verified" if refs_status == "verified" else "not_run",
        "detail": refs_status,
        "note": "D1 核验结果继承自阶段②，未重复调用网络",
    }
    pdf_outputs = [compilation["pdf"]] if compilation.get("pdf_compiled") else []
    return _handoff(
        5, "completed" if lint["ok"] else "completed_with_caveat",
        "由结果字典生成 LaTeX 成稿、逐条可回溯断言，并编译为 PDF",
        inputs=[HANDOFF_NAMES[4]],
        outputs=[_rel(tex_path), _rel(claims_path)] + pdf_outputs,
        manuscript={
            "canonical_source": _rel(tex_path),
            "format": "LaTeX (ctexart, 需 xelatex 或 tectonic)",
            "generated_from": _rel(out / "model" / "summary.json"),
            "sections": ["摘要", "引言", "方法", "实验设置", "结果", "消融与讨论", "结论"],
            "tables": 1,
            "citations": len(report.REFERENCES),
            "claims_count": len(claims),
            "synthetic_disclaimer": "摘要首句显式声明为合成数据演示",
        },
        anti_hallucination_compliance={
            "d1_citation_verification": d1,
            "d2_claim_provenance": {
                "status": "pass",
                "n_claims": len(claims),
                "scheme": "每条断言带 {file, JSON Pointer}，由校验器逐条回溯核对",
            },
            "d3_citation_lint": lint,
            "d4_grounding": {"status": "not_applicable",
                             "reason": "本课题无数值图表需从原页读取"},
        },
        compilation_status=compilation,
    )


def _journal_seed() -> list[dict]:
    """离线候选刊（等级来源标注为种子，非权威核验）。"""
    return [
        {"name": "Spectrochimica Acta Part B", "tier": "Tier1",
         "scope": "LIBS 方法学主阵地", "rank_source": "local_seed_unverified"},
        {"name": "Journal of Analytical Atomic Spectrometry", "tier": "Tier1",
         "scope": "原子光谱/LIBS", "rank_source": "local_seed_unverified"},
        {"name": "Analytical Methods", "tier": "Tier2",
         "scope": "分析方法", "rank_source": "local_seed_unverified"},
        {"name": "Chemometrics and Intelligent Laboratory Systems", "tier": "Tier2",
         "scope": "化学计量学（PLS/MIL 方法）", "rank_source": "local_seed_unverified"},
        {"name": "Applied Sciences", "tier": "Tier3",
         "scope": "应用光谱与机器学习", "rank_source": "local_seed_unverified"},
    ]


def stage6_publication(out: Path, offline: bool) -> dict:
    journals = _journal_seed()
    query = {"status": "not_run", "reason": "无 EasyScholar 凭据" if offline else "未配置凭据"}
    key = os.environ.get("EASYSCHOLAR_SECRET_KEY", "").strip()
    if key and not offline:
        try:
            sys.path.insert(0, str(REPO / "gewu" / "mcp"))
            import journal_rank  # type: ignore

            data = journal_rank.query_many([j["name"] for j in journals], key)
            query = {"status": "queried", "n": len(data.get("journals", data) or [])}
            ranks = data.get("journals") if isinstance(data, dict) else None
            if isinstance(ranks, list):
                by_name = {r.get("name"): r for r in ranks if isinstance(r, dict)}
                for j in journals:
                    if j["name"] in by_name:
                        j["easyscholar_rank"] = by_name[j["name"]].get("rank")
                        j["rank_source"] = "easyscholar"
        except Exception as e:  # 网络/凭据问题不得让链路失败
            query = {"status": "failed", "reason": f"{type(e).__name__}: {e}"}

    claimed = [j for j in journals if j["rank_source"] == "easyscholar"]
    return _handoff(
        6, "completed_with_caveat",
        "候选期刊匹配（等级来源显式标注）",
        inputs=[HANDOFF_NAMES[5]], outputs=[],
        journals=journals,
        rank_query=query,
        integrity_note=(
            f"仅 {len(claimed)}/{len(journals)} 条等级来自可核验接口；"
            "其余为本地种子，标记 local_seed_unverified，不得表述为已核验分区"
        ),
        recommendation={
            "primary": "Spectrochimica Acta Part B",
            "reason": "LIBS 方法学主阵地，且阶段②文献即发表于该刊；但本课题为合成数据演示，"
                      "不构成投稿成熟度判断",
            "not_ready": "本报告为链路验证稿，缺真实数据与组件级消融，尚不具备投稿条件",
        },
    )


def stage7_distill(out: Path, res: dict, registry_path: Path, commit_registry: bool) -> dict:
    skill_dir = out / "skills" / "min-case-libs"
    skill = f"""---
name: min-case-libs
description: 合成 LIBS 多示例回归最小课题的可复现做法与踩坑记录（由 run_min_case 自动生成）
version: 1.0.0
domain: demo_synth
---

# 最小课题：合成 LIBS + MIL 热值回归

## 何时用
- 需要向第三方证明「七阶段链路能从零跑通」而手上只有私有数据时；
- 需要快速验证某个 MIL 想法（定标方式 / 池化 / 残差）是否值得上真实数据前，先用它做冒烟。

## 怎么跑
```bash
python scripts/run_min_case.py            # 全链路，产出 output/min_case/
python scripts/run_min_case.py --offline  # 不联网（跳过 D1 核验，状态会诚实降级）
python scripts/run_min_case.py --json     # 只输出汇总 JSON（供 sci-exp rerun 使用）
```

## 关键结论（本机实测）
- 袋均谱 PLSR 基线 RMSE = {res['summary']['plsr']['rmse_mean']:.2f} kcal/kg，
  本方法 = {res['summary']['hybrid']['rmse_mean']:.2f} kcal/kg
  （{res['improvement_pct']:.2f}%），配对检验 p = {res['paired_tests']['hybrid_vs_plsr'].get('p')}。
- 内层 CV 选出的 β = {res['beta_selected']}，Ridge α = {res['ridge_alphas']}。

## 踩坑记录
1. **逐谱归一化会杀掉尺度信息**：若在特征阶段就除以每谱均值，颗粒异质性同时被除掉，
   MIL 臂会退化成普通回归。要保留尺度，必须先分箱再按实例定标，且把定标放在"生成模型特征"里显式记录。
2. **按 bag 切折，不能按实例切**：同一 bag 的实例跨折会让指标虚高，这是 MIL 里最常见的泄漏。
3. **口径陷阱**：`per-fold 均值` 与 `pooled OOF` 是两个数，混用会让论文与 UI 打架。
   本项目统一以 per-fold 均值为准，pooled 仅作补充并显式标注。
4. **β=0 不是失败**：内层 CV 选到 0 说明该数据上均值池化够用，应如实写；
   强行取 β>0 属于为了叙事而改模型。
5. **合成数据的绝对误差不可外推**：本链路证明机制与链路，真实精度以存档课题为准。
"""
    skill_path = skill_dir / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(skill, encoding="utf-8")

    memory = f"""# 最小课题记忆（自动生成）

## 已验证
- 七阶段链路在零外部数据依赖下跑通，产物见 `output/min_case/`。
- 基线 {res['summary']['plsr']['rmse_mean']:.2f} → 本方法 {res['summary']['hybrid']['rmse_mean']:.2f} kcal/kg，
  p={res['paired_tests']['hybrid_vs_plsr'].get('p')}，五折方向{'一致' if res['paired_tests']['hybrid_vs_plsr']['all_same_direction'] else '不一致'}。

## 不要重复的错误
- 不要把本课题数字与真实课题（214.57 kcal/kg）并列比较：前者是合成数据，量级不可比。
- 不要用 β>0 来"证明"LSE 有效，除非内层 CV 真的选中它。

## 待办
- 组件级消融（逐特征去掉）需更大样本或正则化搜索，当前 n=56 易过拟合。
"""
    mem_path = out / "MEMORY.md"
    mem_path.write_text(memory, encoding="utf-8")

    reproduce = f"""# 复现说明（最小课题）

```bash
# 1) 依赖（工具层 venv 即可，不需要 torch）
pip install -r requirements.txt

# 2) 跑全链路（约数秒，零下载）
python scripts/run_min_case.py

# 3) 校验（十层；含确定性重跑比对与 PDF 成品比对）
python -m gewu.demo.verify output/min_case

# 4) 只取汇总（供 sci-exp 交叉校验）
python scripts/run_min_case.py --json
```

产物：
- `data/` 合成数据集（CSV 实体文件，非内存态）
- `model/fold{{0..4}}/predictions.json`、`model/summary.json`
- `report/main.tex`、`report/claims.json`
- `agents/handoff_1..7.json`
- `registry/demo_synth.json`（可直接被 `sci_exp.rerun_experiment` 重算）

论文编译：第 5 阶段自动探测 TeX 引擎（tectonic > xelatex > lualatex > latexmk > pdflatex），
真实编译 `report/main.tex` → `report/main.pdf`，并把 log 里的 error / 缺字 / overfull 计数
写进 `agents/handoff_5_writer.json` 的 `compilation_status`。本机无引擎时**不失败**，
而是写 `pdf_compiled: false` 与原因（校验第 10 层据此确认「未编译时不得残留旧 PDF」）。

单独重编译或指定引擎：
```bash
python -m gewu.latex_build report/main.tex
GEWU_LATEX_ENGINE=/path/to/tectonic python -m gewu.latex_build report/main.tex
```
首次用 tectonic 需从 CTAN 拉 TeX bundle（实测约 6 分钟、约 300MB，之后编译不足 2 秒）。
"""
    rep_path = out / "REPRODUCE.md"
    rep_path.write_text(reproduce, encoding="utf-8")

    entry = build_registry(res)
    _dump(registry_path, entry["file"])
    if commit_registry:
        target = REPO / "gewu" / "mcp" / "registry" / "demo_synth.json"
        target.write_text(json.dumps(entry["file"], ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")

    return _handoff(
        7, "completed", "沉淀：技能、记忆、注册表条目与复现说明",
        inputs=[HANDOFF_NAMES[6]],
        outputs=[_rel(skill_path), _rel(mem_path), _rel(rep_path), _rel(registry_path)],
        artifacts={
            "skill": _rel(skill_path),
            "memory": _rel(mem_path),
            "reproduce": _rel(rep_path),
            "registry": _rel(registry_path),
            "registry_committed": commit_registry,
        },
        reproducibility_statement={
            "from_scratch": True,
            "external_data_required": False,
            "rerun_command": "python scripts/run_min_case.py --json",
            "deterministic": True,
            "verified_by": "python -m gewu.demo.verify",
        },
        lessons=[
            "逐谱归一化会连颗粒尺度一起抹掉，定标顺序决定 MIL 是否还有意义",
            "按 bag 切折是 MIL 的底线，按实例切会泄漏",
            "per-fold 均值与 pooled OOF 必须分开报，混用会让文档互相矛盾",
            "β=0 是有效结论，不是失败；不得为叙事强行取 β>0",
        ],
    )


def build_registry(res: dict) -> dict:
    """生成注册表条目：三条实验，rerun 指向本脚本，可由 sci-exp 真实重算。"""
    s = res["summary"]
    rerun_base = {
        "type": "cli",
        "python": "system",
        "script": "scripts/run_min_case.py",
        "args": ["--json"],
        "timeout": 600,
    }
    arms = []
    for arm_id, arm_name, category in (
        ("plsr_baseline", "plsr", "baseline"),
        ("mil_direct", "mil", "ablation"),
        ("our_hybrid", "hybrid", "ours"),
    ):
        arms.append({
            "id": f"demo_synth_{arm_id}",
            "name": f"[合成演示] {s[arm_name]['label']}",
            "category": category,
            "config": {
                "dataset": "gewu/demo/synth.py (synthetic, seed 20261109)",
                "n_bags": res.get("n_bags"),
                "folds": 5,
                "features": "64-bin 分箱；逐实例谱形定标（mil/hybrid 臂）",
                "model": {
                    "plsr": "PLSRegression(n_components<=6) on bag-mean",
                    "mil": "instance PLS + LSE pooling (beta by inner CV)",
                    "hybrid": "mil + RidgeCV on amplitude/pooling stats",
                }[arm_name],
            },
            "metrics": {
                "rmse_mean": s[arm_name]["rmse_mean"],
                "rmse_std": s[arm_name]["rmse_std"],
                "r2_mean": s[arm_name]["r2_mean"],
                "per_fold_rmse": s[arm_name]["per_fold_rmse"],
            },
            "source": "output/min_case/model/summary.json",
            "source_of_truth": "output/min_case/model/fold{0..4}/predictions.json（可独立重算）",
            "reproducibility": "realizable_by_gewu",
            "rerun": {
                **rerun_base,
                "metrics_path": f"summary.{arm_id}",
                "key_map": {
                    "rmse_mean": "rmse_mean",
                    "rmse_std": "rmse_std",
                    "r2_mean": "r2_mean",
                },
                "tolerance": {"rmse_mean": 0.01, "rmse_std": 0.01, "r2_mean": 0.0005},
                "note": "重跑最小课题并取对应臂的 5 折汇总，与登记值交叉校验",
            },
            "rerun_hint": f"python scripts/run_min_case.py --json → 取 summary.{arm_id}",
            "domain": "demo_synth",
        })
    return {
        "file": {
            "schema_version": "1.0",
            "domain": "demo_synth",
            "domain_label": "合成演示 · LIBS MIL 热值回归（零外部依赖）",
            "registered_by": "gewu min-case harness",
            "note": "本域为端到端链路自证用合成课题；数值不代表真实煤样精度，禁止与 coal_mil 域混比",
            "experiments": arms,
        }
    }


def write_snapshot(result: dict, validation: dict | None, target: Path) -> Path:
    """把最小课题的**聚合结果**写入仓库（``output/`` 被 gitignore，评审看不到）。

    只写聚合指标与阶段状态，不含光谱数据、不含逐样本预测，因此可以安全入库；
    它让评审在 clone 之后、**还没运行脚本之前**就能看到"确实跑过、数值是多少"，
    同时保留 ``from_scratch`` 标志，说明这些数字可被一条命令重新生成。
    """
    snap = {
        "kind": "min_case_snapshot",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "from_scratch": True,
        "regenerate": "python scripts/run_min_case.py",
        "data_kind": "synthetic",
        "disclaimer": "合成光谱上的链路验证结果，不代表真实煤样精度；不得与 coal_mil 域数值并列比较",
        "case_dir": result["case_dir"],
        "n_bags": result["n_bags"],
        "n_instances": result["n_instances"],
        "elapsed_s": result["elapsed_s"],
        "refs_status": result["refs_status"],
        "metrics": {
            arm: {k: v for k, v in result["summary"][arm].items() if k != "pooled"}
            for arm in ("plsr_baseline", "mil_direct", "our_hybrid")
        },
        "improvement_pct": result["improvement_pct"],
        "paired_tests": result["paired_tests"],
        "beta_selected": result["beta_selected"],
        "handoffs": result["handoffs"],
        "validation": None if validation is None else {
            "ok": validation["ok"],
            "n_checks": validation["n_checks"],
            "n_failed": validation["n_failed"],
            "layers": validation["layers"],
        },
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def run(
    out: Path = DEFAULT_OUT,
    *,
    n_bags: int = 70,
    seed: int = 20261109,
    offline: bool = False,
    commit_registry: bool = False,
    log=lambda *_: None,
) -> dict:
    out = Path(out)
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)

    log("[0/7] 生成合成数据 ...")
    ds = synth.make_dataset(n_bags=n_bags, seed=seed)
    info = synth.materialise(ds, out / "data")
    mats, ys_arr, ids, card = synth.load_bags(out / "data")   # 真实读盘，验证 I/O
    folds = synth.split_folds(out / "data")
    ys = {bid: float(v) for bid, v in zip(ids, ys_arr)}
    feats = {bid: mil_lite.build_features(m) for bid, m in zip(ids, mats)}
    n_inst = sum(f["shape"].shape[0] for f in feats.values())
    log(f"    bag={info['n_bags']} 实例={n_inst} 文件={info['n_files']}")

    log("[1/7] 定方向 ...")
    h1 = stage1_direction(out)

    log("[2/7] 文献检索与核验 ...")
    h2 = stage2_litreview(out, offline)
    refs_status = h2["d1_citation_verification"]["status"]

    log("[3/7] 5 折复现（基线） ...")
    res = mil_lite.run_cv(feats, ys, folds)
    res["n_bags"] = n_bags
    h3 = stage3_reproduce(out, res, n_bags, n_inst, seed)

    log("[4/7] 改进 + 消融 ...")
    _dump(out / "model" / "summary.json", _summary_block(res, n_bags, n_inst))
    h4 = stage4_improve(out, res)

    log("[5/7] 生成成稿 ...")
    h5 = stage5_write(out, res, n_bags, n_inst, refs_status)

    log("[6/7] 期刊匹配 ...")
    h6 = stage6_publication(out, offline)

    log("[7/7] 沉淀 ...")
    registry_path = out / "registry" / "demo_synth.json"
    h7 = stage7_distill(out, res, registry_path, commit_registry)

    handoffs = []
    for st, h in ((1, h1), (2, h2), (3, h3), (4, h4), (5, h5), (6, h6), (7, h7)):
        p = out / "agents" / AGENT_DIRS[st] / HANDOFF_NAMES[st]
        _dump(p, h)
        handoffs.append(_rel(p))

    return {
        "case_dir": _rel(out),
        "n_bags": n_bags,
        "n_instances": n_inst,
        "elapsed_s": round(time.time() - t0, 2),
        "handoffs": handoffs,
        "summary": {
            "plsr_baseline": res["summary"]["plsr"],
            "mil_direct": res["summary"]["mil"],
            "our_hybrid": res["summary"]["hybrid"],
        },
        "improvement_pct": res["improvement_pct"],
        "paired_tests": res["paired_tests"],
        "beta_selected": res["beta_selected"],
        "refs_status": refs_status,
        "registry": _rel(registry_path),
        "registry_committed": commit_registry,
    }
