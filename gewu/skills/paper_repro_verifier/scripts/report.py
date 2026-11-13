"""Human-readable, evidence-linked reproduction report."""
from __future__ import annotations

from common import now_iso


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def _loc(e) -> str:
    if not isinstance(e, dict):
        return "—"
    bits = [e.get("source") or e.get("path") or "?"]
    if e.get("page"):
        bits.append(f"p.{e['page']}")
    if e.get("line"):
        bits.append(f"l.{e['line']}")
    if e.get("section"):
        bits.append(str(e["section"]))
    return ":".join(str(b) for b in bits)


def build(materials, env, env_checks, parameters, comparison, attribution,
          execution, result_contract, figures) -> str:
    L = []
    A = L.append
    A("# 论文复现与方法验证 · 可核验报告")
    A("")
    A(f"生成时间：{now_iso()}　|　由 `paper-repro-verifier` 自动汇总（数值均来自实际文件）")
    A("")
    A(f"**复现结论：`{attribution.get('grade', 'indeterminate')}`**")
    A("")
    A(f"> 依据：{attribution.get('basis', '')}")
    A("")
    A("---")
    A("")
    A("## 1. 材料定位（找得齐）")
    A("")
    A(f"扫描到 {materials.get('n_files', 0)} 个文件。必需材料类别核查：")
    A("")
    A("| 类别 | 状态 | 证据文件 |")
    A("|---|---|---|")
    for g in materials.get("checklist", []):
        A(f"| {g['category']} | {g['status']} | {', '.join(g.get('evidence_paths', [])[:3]) or '—'} |")
    gaps = [g for g in materials.get("checklist", []) if g["status"] == "missing"]
    if gaps:
        A("")
        A("**显式缺失登记**（不得用合成数据替代）：")
        for g in gaps:
            A(f"- `{g['category']}`：{g.get('reason','')}；接管方式：{g.get('takeover','')}")
    if materials.get("warnings"):
        A("")
        A("扫描告警：" + "; ".join(materials["warnings"][:5]))
    A("")
    A("## 2. 环境检查（跑得对）")
    A("")
    p, pl = env.get("python", {}), env.get("platform", {})
    A(f"- Python `{p.get('version')}` / {p.get('implementation')}；"
      f"{pl.get('system')} {pl.get('release')} / {pl.get('machine')}；CPU {env.get('cpu_count')}")
    A(f"- 检出依赖 {env.get('n_packages_detected')} 个（完整版本见 `environment_snapshot.json`）")
    A(f"- GPU：{env.get('gpu', {}).get('status')}　|　种子：{env.get('seeds', {}).get('python_hashseed')}")
    n_mm = sum(1 for c in env_checks.get("checks", []) if c.get("status") == "version_mismatch")
    n_na = sum(1 for c in env_checks.get("checks", []) if c.get("status") == "not_installed")
    A(f"- 与论文声明比对：{env_checks.get('n_claims', 0)} 条声明，"
      f"版本不一致 {n_mm}，缺失 {n_na}（明细见 `environment_check.json`）")
    A("")
    A("## 3. 参数复原（三源对齐）")
    A("")
    A(f"共 {parameters.get('n_parameters', 0)} 个候选参数，其中 **{parameters.get('n_conflicts', 0)} 个冲突**。")
    A("")
    A("| 参数 | 论文值 | 代码默认 | 采用值 | 来源类别 | 冲突 | 证据 |")
    A("|---|---|---|---|---|---|---|")
    for r in parameters.get("executable_parameter_table", [])[:60]:
        ev = (r.get("paper_evidence") or r.get("config_evidence") or r.get("code_evidence") or [{}])[0]
        A(f"| `{r['name']}` | {_fmt(r['paper_values'][0]) if r.get('paper_values') else '—'} "
          f"| {_fmt(r['code_defaults'][0]) if r.get('code_defaults') else '—'} "
          f"| {_fmt(r.get('resolved'))} | `{r.get('source_class')}` "
          f"| {'⚠' if r.get('conflict') else ''} | {_loc(ev.get('evidence', ev))} |")
    A("")
    A("裁决规则：" + parameters.get("policy", ""))
    A("")
    A("## 4. 代码运行")
    A("")
    A(f"状态：`{execution.get('status', 'not_run')}`　|　"
      f"命令：`{execution.get('command', '—')}`　|　退出码：{_fmt(execution.get('exit_code'))}")
    if execution.get("note"):
        A("")
        A(execution["note"])
    A("")
    A("## 5. 结果比较（对得上，容差事前声明）")
    A("")
    tol = comparison.get("tolerance", {})
    c = comparison.get("counts", {})
    A(f"容差：绝对 `{tol.get('default_abs')}` + 相对 `{tol.get('default_rel')}`"
      f"（比较前写入 `comparison.json`）。"
      f"共 {c.get('total',0)} 项：PASS {c.get('pass',0)} / FAIL {c.get('fail',0)} / "
      f"UNVERIFIABLE {c.get('unverifiable',0)}；"
      f"另有 {c.get('needs_review', c.get('deferred',0))} 条叙述/逐折声明标 NEEDS_REVIEW"
      f"（保留证据，需人工确认口径），{c.get('discarded',0)} 条判为解析噪声已剔除。")
    A("")
    ext = comparison.get("external_verified", {})
    if ext.get("n_sources"):
        A("### 5.1 实际验证脚本的数值比较（优先采信）")
        A("")
        A("以下数值来自**真实运行**的验证脚本，优先于正则启发式比较：")
        A("")
        A("| 来源 | 条目 | PASS | FAIL |")
        A("|---|---:|---:|---:|")
        for s in ext["sources"]:
            A(f"| `{s['source_file']}` | {s['n_rows']} | {s['n_pass']} | {s['n_fail']} |")
        A("")
        for s in ext["sources"][:1]:
            A("| 指标 | 论文声明 | 重算值 | 判定 | 定位 |")
            A("|---|---|---|---|---|")
            for r in s["rows"][:40]:
                A(f"| `{r.get('metric')}` | {_fmt(r.get('declared'))} | {_fmt(r.get('observed'))} "
                  f"| {r.get('verdict')} | {_loc(r.get('evidence'))} |")
        A("")
    else:
        A("> 未发现实际验证脚本产出的数值比较。请运行项目自带的复现/评价脚本，"
          "把结果 JSON 放进 `--out`，再重跑 `run` 以采信真实数值。")
        A("")
    A("### 5.2 启发式聚合比较（兜底）")
    A("")
    A("")
    A("| 指标 | 论文声明 | 复现实测 | 绝对差 | 容差 | 判定 | 论文定位 |")
    A("|---|---|---|---|---|---|---|")
    for r in comparison.get("rows", [])[:80]:
        A(f"| `{r.get('metric')}` | {_fmt(r.get('declared'))} | {_fmt(r.get('observed'))} "
          f"| {_fmt(r.get('abs_diff'))} | {_fmt((r.get('tolerance') or {}).get('effective'))} "
          f"| {r.get('verdict')} | {_loc(r.get('evidence'))} |")
    if figures.get("generated"):
        A("")
        A("复现图与论文原图对比：" + ", ".join(f"`{f}`" for f in figures["generated"]))
    if figures.get("note"):
        A("")
        A("出图说明：" + figures["note"])
    A("")
    A("## 6. 差异归因（讲得清）")
    A("")
    A("按 环境 → 数据 → 实现 → 描述不足 → 随机性 次序排除；每条需填 `resolution` 与证据。")
    A("")
    for it in attribution.get("items", [])[:30]:
        A(f"- **{it['id']}** `{it.get('metric')}` 声明 {_fmt(it.get('declared'))} / "
          f"实测 {_fmt(it.get('observed'))}（{it.get('kind')}）")
        for h in it.get("hypotheses", [])[:5]:
            A(f"  - [{h['weight']}] `{h['category']}`：{h['hypothesis']} → {h['verification_action']}")
    A("")
    A("## 7. 结论与不确定性")
    A("")
    A(f"- 分级：**{attribution.get('grade')}**；依据：{attribution.get('basis')}")
    A("- 数值波动仅在事前声明容差内成立；方法性差异必须单列，不得靠放宽容差抹平。")
    A("- 未报告 / 无法判断 / 材料冲突需分别写入 `result.json` 的 `uncertainty`。")
    A("")
    A("## 8. 输出契约与复核路径")
    A("")
    A(f"`result.json` 需含字段：{', '.join(result_contract.get('fields', [])) or '（输入未声明契约）'}"
      f"（来源：{result_contract.get('shape', 'absent')}），并附 `case_id` / `status` / "
      f"`sources` / `uncertainty` / `change_records`。")
    A("")
    A("复核顺序：`materials_ledger.json` → `environment_snapshot.json` → `parameters.json` → "
      "`execution.json` → `comparison.json` → `attribution.json` → `repro/run_log.jsonl` → 本报告。")
    A("")
    A("> 本报告由脚本从实际文件生成；凡标「—」「unverifiable」「missing」处均为真实缺口，不是省略。")
    return "\n".join(L) + "\n"
