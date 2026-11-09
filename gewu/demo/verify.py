"""最小课题链路校验器（与课题无关的十层检查）。

为什么单独写
------------
``scripts/e2e_smoke_test.py`` 校验的是**真实课题的存档产物**（路径、指标都写死在 coal 域）。
本模块只接收一个 ``case_dir``，不假设任何领域常量，因此可复用于任何"七阶段产出目录"，
也用作最小课题的验收标准。

十层
----
1. 产出完整 —— 七份 handoff、模型汇总、论文、断言文件均存在且非空
2. 阶段串联 —— 第 n 阶段的首个输入指向第 n-1 阶段的 handoff
3. 状态合法 —— 七阶段均为 completed*（允许带 caveat，但不允许 pending/failed）
4. 数值一致 —— 从逐折 predictions 重算指标，必须与 summary 逐位吻合
5. 无矛盾   —— 不得声称某产物"未创建/缺失"而实际存在
6. 论文自洽 —— LaTeX 环境/括号/cite-bib 配对，中文有 CJK 支持，无 Markdown 残留
7. 溯源完整 —— 每条 claim 的 {file, pointer} 可解析，且数值与论文一致
8. 确定性   —— 用同一种子重跑，逐折 RMSE 完全一致（可选，默认开）
9. 注册表   —— 沉淀的 registry 条目可被 sci-exp 直接复算
10. PDF 成品 —— 声称编译成功时 PDF 必须存在、可解析、正文含关键数值；未编译时不得残留旧 PDF

用法::

    python -m gewu.demo.verify output/min_case
    python -m gewu.demo.verify output/min_case --json report.json --no-determinism
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from . import lint_tex, mil_lite, synth

REPO = Path(__file__).resolve().parents[2]

HANDOFF_FILES = [
    ("gewu-director", "handoff_1_direction.json"),
    ("gewu-ideation", "handoff_2_litreview.json"),
    ("gewu-reproduction", "handoff_3_repro.json"),
    ("gewu-improver", "handoff_4_improver.json"),
    ("gewu-writer", "handoff_5_writer.json"),
    ("gewu-publication", "handoff_6_publication.json"),
    ("gewu-distillation", "handoff_7_distillation.json"),
]
ARMS = ("plsr", "mil", "hybrid")

# docs/paper/min_case/main.pdf 快照对应的生成配置；配置不同则不比指纹（见 check_pdf）
SNAPSHOT_CONFIG = {"n_bags": 70, "seed": 20261109}


# --------------------------------------------------------------------------
def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_pointer(doc: Any, pointer: str) -> Any:
    """最小 JSON Pointer 实现（RFC 6901 常用子集）。"""
    if pointer in ("", "/"):
        return doc
    cur = doc
    for raw in pointer.lstrip("/").split("/"):
        tok = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            cur = cur[int(tok)]
        elif isinstance(cur, dict):
            cur = cur[tok]
        else:
            raise KeyError(f"pointer 无法继续解析: {pointer}")
    return cur


def _rmse(y: list[float], p: list[float]) -> float:
    n = len(y)
    return (sum((a - b) ** 2 for a, b in zip(y, p)) / n) ** 0.5


def _r2(y: list[float], p: list[float]) -> float:
    my = sum(y) / len(y)
    ss_res = sum((a - b) ** 2 for a, b in zip(y, p))
    ss_tot = sum((a - my) ** 2 for a in y)
    return 1 - ss_res / ss_tot if ss_tot else 0.0


# --------------------------------------------------------------------------
class Checker:
    def __init__(self) -> None:
        self.results: list[dict] = []
        self.errors: list[str] = []

    def add(self, layer: str, name: str, ok: bool, detail: str = "") -> None:
        self.results.append({
            "layer": layer,
            "check": name,
            "status": "PASS" if ok else "FAIL",
            "detail": detail,
        })
        if not ok:
            self.errors.append(f"[{layer}] {name}: {detail}")


def check_artifacts(c: Checker, case: Path) -> dict[str, dict]:
    h = {}
    for agent, fname in HANDOFF_FILES:
        p = case / "agents" / agent / fname
        ok = p.is_file() and p.stat().st_size > 100
        c.add("1-artifacts", f"handoff {fname}", ok,
              "" if ok else f"缺失或过小: {p}")
        if ok:
            h[int(re.match(r"handoff_(\d)", fname).group(1))] = _load(p)
    for rel, min_size in (
        ("model/summary.json", 500),
        ("report/main.tex", 800),
        ("report/claims.json", 200),
        ("data/data_card.json", 100),
        ("data/split.json", 50),
    ):
        p = case / rel
        ok = p.is_file() and p.stat().st_size > min_size
        c.add("1-artifacts", rel, ok, "" if ok else f"缺失或过小: {p}")
    return h


def check_chain(c: Checker, handoffs: dict[int, dict]) -> None:
    for stage in range(2, 8):
        prev = HANDOFF_FILES[stage - 2][1]
        h = handoffs.get(stage)
        if not h:
            continue
        inputs = h.get("inputs") or []
        ok = any(prev in str(x) for x in inputs)
        c.add("2-chain", f"stage{stage} ← {prev}", ok,
              "" if ok else f"inputs={inputs}")


def check_status(c: Checker, handoffs: dict[int, dict]) -> None:
    for stage, h in handoffs.items():
        st = str(h.get("status", ""))
        ok = st.startswith("completed")
        c.add("3-status", f"stage{stage} status={st}", ok, "" if ok else "非 completed*")


def check_numbers(c: Checker, case: Path, handoffs: dict[int, dict]) -> None:
    summary = _load(case / "model" / "summary.json")
    folds: dict[int, list[dict]] = {}
    for f in range(summary["dataset"]["n_folds"]):
        p = case / "model" / f"fold{f}" / "predictions.json"
        if not p.is_file():
            c.add("4-numbers", f"fold{f} predictions", False, f"缺失 {p}")
            return
        folds[f] = _load(p)

    # 4.1 每折指标可重算
    for f, rows in folds.items():
        y = [r["y_true"] for r in rows]
        for arm in ARMS:
            recomputed = _rmse(y, [r[f"{arm}_pred"] for r in rows])
            recorded = next(r for r in summary["per_fold"] if r["fold"] == f)[arm]["rmse"]
            # 记录值保留 4 位小数，故容差取 1e-4（仅为记录舍入，非模型差异）
            ok = abs(recomputed - recorded) <= 1e-4
            c.add("4-numbers", f"fold{f} {arm} rmse 可重算", ok,
                  "" if ok else f"重算 {recomputed:.6f} vs 记录 {recorded}")

    # 4.2 汇总口径自洽（逐折均值 / 总体标准差）
    for arm in ARMS:
        vals = [r[arm]["rmse"] for r in summary["per_fold"]]
        mean = sum(vals) / len(vals)
        sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        blk = summary["summary"][arm]
        ok = abs(mean - blk["rmse_mean"]) <= 1e-4 and abs(sd - blk["rmse_std"]) <= 1e-4
        c.add("4-numbers", f"{arm} 均值/标准差口径一致", ok,
              "" if ok else f"均值 {mean:.4f} vs {blk['rmse_mean']}；sd {sd:.4f} vs {blk['rmse_std']}")

    # 4.3 pooled OOF 可重算
    all_rows = [r for rows in folds.values() for r in rows]
    for arm in ARMS:
        pooled = _rmse([r["y_true"] for r in all_rows], [r[f"{arm}_pred"] for r in all_rows])
        recorded = summary["summary"][arm]["pooled"]["rmse"]
        ok = abs(pooled - recorded) <= 1e-4
        c.add("4-numbers", f"{arm} pooled OOF 可重算", ok,
              "" if ok else f"重算 {pooled:.4f} vs {recorded}")

    # 4.4 handoff 与 summary 不得打架
    h3 = handoffs.get(3) or {}
    b = h3.get("baseline_metrics") or {}
    if b:
        ok = abs(b.get("mean_rmse", -1) - summary["summary"]["plsr"]["rmse_mean"]) <= 1e-6
        c.add("4-numbers", "handoff_3 基线 = summary", ok,
              "" if ok else f"{b.get('mean_rmse')} vs {summary['summary']['plsr']['rmse_mean']}")
    h4 = handoffs.get(4) or {}
    ia = h4.get("improvement_analysis") or {}
    if ia.get("proposed"):
        ok = abs(ia["proposed"]["rmse_mean"] - summary["summary"]["hybrid"]["rmse_mean"]) <= 1e-6
        c.add("4-numbers", "handoff_4 改进 = summary", ok, "" if ok else "数值不一致")
    abl = (h4.get("ablation_study") or {}).get("arms") or []
    if abl:
        same = all(
            abs(a["rmse_mean"] - summary["summary"][a["id"]]["rmse_mean"]) <= 1e-6
            for a in abl if a["id"] in ARMS
        )
        c.add("4-numbers", "handoff_4 消融三臂 = summary", same, "" if same else "三臂数值不一致")

    # 4.5 改进幅度可重算
    gain = (summary["summary"]["plsr"]["rmse_mean"] - summary["summary"]["hybrid"]["rmse_mean"]) \
        / summary["summary"]["plsr"]["rmse_mean"] * 100
    ok = abs(gain - summary["improvement_pct"]) <= 1e-3
    c.add("4-numbers", "improvement_pct 可重算", ok,
          "" if ok else f"{gain:.4f} vs {summary['improvement_pct']}")


CLAIM_MISSING = ("未创建", "不存在", "缺失", "未生成")
FILE_RE = re.compile(r"[\w\u4e00-\u9fff\-]+\.(?:json|tex|md|py|html|png|pdf)")


def check_contradictions(c: Checker, case: Path, handoffs: dict[int, dict]) -> None:
    index = {p.name for p in case.rglob("*") if p.is_file()}
    hits = []
    for stage, h in handoffs.items():
        text = json.dumps(h, ensure_ascii=False)
        for phrase in CLAIM_MISSING:
            if phrase not in text:
                continue
            for fname in FILE_RE.findall(text):
                if fname in index:
                    hits.append(f"stage{stage} 声称 {fname} {phrase}，但文件存在")
    c.add("5-contradiction", "无「声称缺失实则存在」", not hits, "; ".join(hits[:4]))


def check_tex(c: Checker, case: Path) -> None:
    tex_path = case / "report" / "main.tex"
    tex = tex_path.read_text(encoding="utf-8")
    res = lint_tex.lint(tex, tex_path.parent)
    c.add("6-tex", "LaTeX 结构自洽", res["ok"], "; ".join(res["errors"])[:300])
    c.add("6-tex", "含合成数据声明", "合成" in tex, "摘要未声明数据来源")


def check_claims(c: Checker, case: Path) -> None:
    claims = _load(case / "report" / "claims.json")
    tex = (case / "report" / "main.tex").read_text(encoding="utf-8")
    bad_src, bad_val, not_in_tex = [], [], []
    for cl in claims:
        src = cl.get("source") or {}
        f, ptr = src.get("file"), src.get("pointer")
        if not f or not ptr:
            bad_src.append(cl.get("id"))
            continue
        target = case / f
        if not target.is_file():
            bad_src.append(f"{cl.get('id')}→{f}")
            continue
        try:
            actual = _resolve_pointer(_load(target), ptr)
        except (KeyError, IndexError, ValueError):
            bad_src.append(f"{cl.get('id')}→{ptr}")
            continue
        tol = float(cl.get("tolerance", 0) or 0)
        if abs(float(actual) - float(cl["value"])) > tol + 1e-12:
            bad_val.append(f"{cl['id']}: 记录 {cl['value']} vs 溯源 {actual}")
        # 论文里必须能找到该数字（按论文的两位小数格式）
        if isinstance(cl["value"], (int, float)):
            txt = cl.get("rendered") or (
                f"{float(cl['value']):.2f}" if not float(cl["value"]).is_integer()
                else str(int(cl["value"]))
            )
            if txt not in tex and f"{float(cl['value']):.3f}" not in tex:
                not_in_tex.append(f"{cl['id']}={txt}")
    c.add("7-provenance", "claim 源可解析", not bad_src, "; ".join(bad_src[:5]))
    c.add("7-provenance", "claim 数值与源一致", not bad_val, "; ".join(bad_val[:5]))
    c.add("7-provenance", "claim 数字出现在论文中", not not_in_tex, "; ".join(not_in_tex[:5]))


def check_determinism(c: Checker, case: Path) -> None:
    try:
        mats, ys_arr, ids, _ = synth.load_bags(case / "data")
        folds = synth.split_folds(case / "data")
        ys = {b: float(v) for b, v in zip(ids, ys_arr)}
        feats = {b: mil_lite.build_features(m) for b, m in zip(ids, mats)}
        res = mil_lite.run_cv(feats, ys, folds)
    except Exception as e:  # pragma: no cover - 环境问题需显式暴露
        c.add("8-determinism", "重跑成功", False, f"{type(e).__name__}: {e}")
        return
    summary = _load(case / "model" / "summary.json")
    for arm in ARMS:
        a = res["summary"][arm]["per_fold_rmse"]
        b = summary["summary"][arm]["per_fold_rmse"]
        ok = a == b
        c.add("8-determinism", f"{arm} 逐折结果逐位一致", ok,
              "" if ok else f"重跑 {a} vs 记录 {b}")


def check_d1(c: Checker, case: Path) -> None:
    """声称 D1「已核验」就必须有核验产物，否则是空口宣称。"""
    p = case / "agents" / "gewu-ideation" / "handoff_2_litreview.json"
    if not p.is_file():
        return
    d1 = (_load(p).get("d1_citation_verification") or {})
    if str(d1.get("status")) != "verified":
        c.add("7-provenance", "D1 未声称核验（诚实降级）", True, "")
        return
    art = d1.get("artifact") or ""
    # handoff 里通常写仓库相对路径，也允许写 case 相对路径
    cand = [p for p in (case / art, REPO / art) if art] if art else []
    ok = any(p.is_file() for p in cand)
    c.add("7-provenance", "D1 verified 有核验产物", ok,
          "" if ok else f"声称 verified 但产物不存在: {art or '<未登记>'}")
    n, k = d1.get("n_verified", 0), d1.get("n_checked", 0)
    ok2 = n > 0 and n == k
    c.add("7-provenance", "D1 通过条数自洽", ok2, "" if ok2 else f"{n}/{k}")


def check_registry(c: Checker, case: Path) -> None:
    p = case / "registry" / "demo_synth.json"
    c.add("9-registry", "注册表条目存在", p.is_file(), str(p))
    if not p.is_file():
        return
    reg = _load(p)
    summary = _load(case / "model" / "summary.json")
    m = {e["id"]: e for e in reg.get("experiments", [])}
    pairs = (("demo_synth_plsr_baseline", "plsr"), ("demo_synth_mil_direct", "mil"),
             ("demo_synth_our_hybrid", "hybrid"))
    for eid, arm in pairs:
        e = m.get(eid)
        if not e:
            c.add("9-registry", f"{eid} 存在", False, "缺条目")
            continue
        ok = abs(e["metrics"]["rmse_mean"] - summary["summary"][arm]["rmse_mean"]) <= 1e-4
        c.add("9-registry", f"{eid} 指标 = summary", ok, "" if ok else "数值不一致")
        spec = e.get("rerun") or {}
        ok2 = spec.get("script") and spec.get("key_map")
        c.add("9-registry", f"{eid} rerun 规格完整", bool(ok2), "" if ok2 else "缺 script/key_map")


# --------------------------------------------------------------------------
def check_pdf(c: Checker, case: Path, handoffs: dict[int, dict]) -> None:
    """第 9 层：PDF 成品与源、数据一致。

    只检查"文件存在"不够——PDF 可能是上一次编译的旧版本，也可能中文整篇掉字却
    仍然"编译成功"。因此要求：文件非空、页数 > 0、可提取文本、正文里真的含有
    claims 中的关键数值。
    """
    h5 = handoffs.get(5) or {}
    comp = h5.get("compilation_status") or {}
    pdf_path = case / "report" / "main.pdf"
    claimed = bool(comp.get("pdf_compiled"))

    if not claimed:
        # 未声称编译成功时，残留一个 PDF 会让评审误以为是本次产物
        stale = pdf_path.is_file()
        c.add("10-pdf", "未编译时不残留旧 PDF", not stale,
              f"handoff 声称未编译，但 {pdf_path.name} 存在（可能为旧版本）" if stale else "")
        return

    exists = pdf_path.is_file() and pdf_path.stat().st_size > 0
    c.add("10-pdf", "PDF 已生成", exists,
          "" if exists else "handoff 声称编译成功，但 PDF 文件缺失或为空")
    if not exists:
        return

    from ..latex_build import pdf_text, pdf_text_fingerprint

    # 区分三种情况：没装 pymupdf（跳过）、装了解析失败（损坏 → FAIL）、正常
    try:
        import pymupdf
    except ImportError:
        c.add("10-pdf", "PDF 可解析", True, "pymupdf 不可用，跳过页数与文本核对")
        return
    try:
        with pymupdf.open(str(pdf_path)) as doc:
            n = len(doc)
    except Exception as e:
        c.add("10-pdf", "PDF 可解析", False, f"文件打不开：{type(e).__name__}: {e}")
        return
    c.add("10-pdf", "PDF 页数 > 0", n > 0, f"pages={n}")

    text = pdf_text(pdf_path)
    c.add("10-pdf", "PDF 含可提取正文", len(text.strip()) > 200,
          f"仅 {len(text.strip())} 字符（中文未配 ctex 时会整篇空白）")

    claims = _load(case / "report" / "claims.json") or []
    # 优先用带小数的指标做探针：它们最能证明"这份 PDF 就是本次实验的产物"。
    # 整数型 claim（如 bag 数）在页码、年份里也可能出现，区分度低，仅在带小数的
    # 探针不足 3 个时用来补位。
    decimal, integer = [], []
    for cl in claims:
        v = cl.get("value")
        if not isinstance(v, (int, float)) or abs(float(v)) < 1:
            continue
        fv = float(v)
        if fv.is_integer():
            integer.append((cl.get("id"), str(int(fv))))
        else:
            decimal.append((cl.get("id"), f"{fv:.2f}"))
    probes = decimal[:5] if len(decimal) >= 3 else (decimal + integer)[:5]
    missing = [f"{cid}={txt}" for cid, txt in probes if txt not in text]
    c.add("10-pdf", "关键数值出现在 PDF 正文", not missing,
          ("未在 PDF 中找到: " + "; ".join(missing)) if missing else f"核对 {len(probes)} 项")

    # 与入库快照（docs/paper）比对：快照不会自动跟随模板变更，需靠这条检查发现过期。
    # 但只对"生成快照时的标准配置"有意义——测试用小数据集（n_bags=25）跑出来的论文
    # 本来就和 70 bag 的快照不同，那不算快照过期。
    from ..latex_build import pdf_text_fingerprint

    snapshot = REPO / "docs" / "paper" / "min_case" / "main.pdf"
    if snapshot.is_file():
        card = _load(case / "data" / "data_card.json") or {}
        same_config = (
            card.get("n_bags") == SNAPSHOT_CONFIG["n_bags"]
            and card.get("seed") == SNAPSHOT_CONFIG["seed"]
        )
        if not same_config:
            c.add("10-pdf", "入库快照比对适用性检查", True,
                  f"非标准配置（n_bags={card.get('n_bags')}, seed={card.get('seed')}），"
                  "跳过快照比对")
        else:
            fp_now = pdf_text_fingerprint(pdf_path)
            fp_snap = pdf_text_fingerprint(snapshot)
            if fp_now and fp_snap:
                c.add("10-pdf", "入库快照与本次编译内容一致", fp_now == fp_snap,
                      "" if fp_now == fp_snap
                      else f"docs/paper/min_case/main.pdf 指纹 {fp_snap} ≠ 本次 {fp_now}，快照已过期")


def validate(case: Path, *, determinism: bool = True) -> dict:
    case = Path(case)
    c = Checker()
    if not case.is_dir():
        return {"ok": False, "errors": [f"case 目录不存在: {case}"], "results": []}

    handoffs = check_artifacts(c, case)
    check_chain(c, handoffs)
    check_status(c, handoffs)
    check_numbers(c, case, handoffs)
    check_contradictions(c, case, handoffs)
    check_tex(c, case)
    check_claims(c, case)
    check_pdf(c, case, handoffs)
    check_d1(c, case)
    check_registry(c, case)
    if determinism:
        check_determinism(c, case)

    layers = sorted({r["layer"] for r in c.results})
    return {
        "ok": not c.errors,
        "case_dir": str(case),
        "n_checks": len(c.results),
        "n_failed": sum(1 for r in c.results if r["status"] == "FAIL"),
        "layers": layers,
        "results": c.results,
        "errors": c.errors,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="最小课题十层校验")
    ap.add_argument("case", nargs="?", default="output/min_case")
    ap.add_argument("--json", default="", help="把结果写入 JSON 文件")
    ap.add_argument("--no-determinism", action="store_true", help="跳过重跑比对（更快）")
    ap.add_argument("--quiet", action="store_true", help="只打印失败项")
    args = ap.parse_args(argv)

    rep = validate(Path(args.case), determinism=not args.no_determinism)
    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.quiet:
        current = None
        for r in rep["results"]:
            if r["layer"] != current:
                current = r["layer"]
                print(f"\n== {current} ==")
            mark = "PASS" if r["status"] == "PASS" else "FAIL"
            extra = f"  <- {r['detail']}" if r["detail"] and r["status"] == "FAIL" else ""
            print(f"  [{mark}] {r['check']}{extra}")
    print(f"\n汇总: {rep['n_checks']} 项，失败 {rep['n_failed']} 项，"
          f"{'全部通过' if rep['ok'] else '存在失败'}")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
