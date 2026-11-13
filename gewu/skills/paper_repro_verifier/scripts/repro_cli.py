#!/usr/bin/env python3
"""paper-repro-verifier driver.

    python repro_cli.py run       --case /input/case.json --task /input/task.md \
                                  --work /app/work --out /app/output
    python repro_cli.py locate    --out /app/output --q "RMSE"
    python repro_cli.py execute   --out /app/output --cmd "python reproduce.py"
    python repro_cli.py finalize  --case /input/case.json --out /app/output

Standard library only for the core flow; numpy/matplotlib/Pillow are optional.
The driver never invents paper content: it reads the actual files given to it.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import attribution as attribution_mod  # noqa: E402
import compare as compare_mod  # noqa: E402
import environment as environment_mod  # noqa: E402
import materials as materials_mod  # noqa: E402
import params as params_mod  # noqa: E402
import pdf_text  # noqa: E402
import report as report_mod  # noqa: E402
from common import (RunLog, case_id_of, contract_fields, load_case,  # noqa: E402
                    now_iso, read_json, write_json, write_text)

DEFAULT_CASE = "/input/case.json"
DEFAULT_TASK = "/input/task.md"
DEFAULT_WORK = "/app/work"
DEFAULT_OUT = "/app/output"


def _common_base(roots: list[Path]) -> Path:
    try:
        return Path(os.path.commonpath([str(r) for r in roots]))
    except ValueError:
        return roots[0] if roots else Path.cwd()


def _default_roots(case_path: Path | None, task_path: Path | None) -> list[Path]:
    roots = []
    for p in (case_path, task_path):
        if p and p.parent.exists() and p.parent not in roots:
            roots.append(p.parent.resolve())
    if not roots:
        roots = [Path.cwd()]
    return roots


def _readable(paths: list[Path]) -> list[Path]:
    return [p for p in paths if p.suffix.lower() in
            (pdf_text.TEXT_EXT | pdf_text.PDF_EXT)]


def cmd_run(args) -> int:
    out, work = Path(args.out).resolve(), Path(args.work).resolve()
    (out / "repro").mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    log = RunLog(out)

    case_path = Path(args.case) if args.case and Path(args.case).exists() else None
    task_path = Path(args.task) if args.task and Path(args.task).exists() else None
    case = load_case(case_path)
    fields, shape = contract_fields(case)
    cid = case_id_of(case, case_path)
    log.step("case", case.get("_status", "ok"), case_id=cid,
             contract_shape=shape, n_fields=len(fields))

    roots = ([Path(x).resolve() for x in args.inputs] if args.inputs
             else _default_roots(case_path, task_path))
    base = _common_base(roots)
    log.step("inputs", "ok", roots=[str(r) for r in roots], base=str(base))

    ledger = log.guarded("materials", lambda: materials_mod.build(roots, base)) or {
        "n_files": 0, "items": [], "checklist": [], "warnings": ["materials scan failed"]}
    write_json(out / "materials_ledger.json", ledger)

    files = materials_mod.discover(roots)[0]
    roles = {it["path"]: it["role"] for it in ledger.get("items", [])}
    idx = log.guarded("evidence_index", lambda: pdf_text.build_index(
        _readable(files)[:200], base, roles=roles)) or {"documents": []}
    write_json(out / "repro" / "evidence_index.json", idx)

    env = log.guarded("environment", environment_mod.build) or {
        "python": {}, "platform": {}, "n_packages_detected": 0, "gpu": {}, "seeds": {},
        "installed_packages": {}, "cpu_count": None, "rebuild_hint": ""}
    write_json(out / "environment_snapshot.json", env)
    write_text(out / "repro" / "rebuild.sh", env.get("rebuild_hint", ""))
    env_checks = log.guarded("environment_check",
                             lambda: environment_mod.compare_to_paper(idx, env)) or {
        "n_claims": 0, "checks": []}
    write_json(out / "environment_check.json", env_checks)

    params = log.guarded("parameters", lambda: params_mod.build(idx, base, ledger["items"])) or {
        "executable_parameter_table": [], "n_parameters": 0, "n_conflicts": 0, "policy": ""}
    write_json(out / "parameters.json", params)

    declared = log.guarded("extract_declared", lambda: compare_mod.extract_declared(idx)) or []
    observed = log.guarded("extract_observed",
                           lambda: compare_mod.extract_observed(base, ledger["items"])) or []
    comparison = log.guarded("comparison",
                             lambda: compare_mod.compare(declared, observed)) or {
        "rows": [], "counts": {"total": 0, "pass": 0, "fail": 0, "unverifiable": 0},
        "tolerance": {}}
    external = log.guarded(
        "external_comparison",
        lambda: compare_mod.load_external(base, ledger["items"], (out,))) or {
        "n_sources": 0, "sources": []}
    comparison["external_verified"] = external
    write_json(out / "comparison.json", comparison)
    figures = log.guarded("figures", lambda: compare_mod.make_figures(
        observed, ledger["items"], base, out / "figures")) or {
        "generated": [], "note": "figure generation failed", "originals_found": []}
    write_json(out / "figures" / "figure_status.json", figures)

    execution = read_json(out / "execution.json", {"status": "not_run"})
    if execution.get("status") == "not_run":
        execution = {"status": "not_run", "command": None, "exit_code": None,
                     "note": "No reproduction command has actually been run yet. "
                             "Use `repro_cli.py execute --cmd '...'` with the project's real "
                             "reproduction command; do not fabricate an exit code."}
    write_json(out / "execution.json", execution)

    attrib = log.guarded("attribution", lambda: attribution_mod.build(
        comparison, env_checks, params, ledger, execution, external)) or {
        "grade": "indeterminate", "basis": "attribution stage failed",
        "items": [], "decision_tree": []}
    write_json(out / "attribution.json", attrib)

    contract = {"fields": fields, "shape": shape, "case_id": cid,
                "note": "field names are read from the actual case.json, never hardcoded"}
    md = report_mod.build(ledger, env, env_checks, params, comparison, attrib,
                          execution, contract, figures)
    write_text(out / "repro_report.md", md)

    result_path = out / "result.json"
    if not result_path.exists():
        skel = {"case_id": cid}
        for f in fields:
            skel[f] = None
        for k, v in {
            "status": "partial",
            "sources": [],
            "uncertainty": [],
            "change_records": [],
            "reproduction": {"grade": attrib.get("grade"), "basis": attrib.get("basis")},
            "limits": [],
            "_contract": contract,
        }.items():
            skel.setdefault(k, v)
        write_json(result_path, skel)
        log.step("result_skeleton", "created", n_contract_fields=len(fields))
    else:
        log.step("result_skeleton", "preserved", note="existing result.json was NOT overwritten")

    index = [
        "# Reproduction audit · navigation", "",
        f"- case_id: `{cid}`　|　contract: `{shape}` ({len(fields)} fields)",
        f"- grade: **{attrib.get('grade')}** — {attrib.get('basis')}",
        "- Read `../repro_report.md` first, then fill `../result.json` per `task.md`.",
        "- Evidence lookup: `python repro_cli.py locate --out <OUT> --q \"<keyword>\"`.",
        "- Run the real reproduction command: `python repro_cli.py execute --out <OUT> --cmd \"...\"`.",
        "- Finish with: `python repro_cli.py finalize --case <CASE> --out <OUT>`.", "",
        "## Artifacts", "",
        "| file | content |", "|---|---|",
        "| `../materials_ledger.json` | materials + explicit missing categories |",
        "| `../environment_snapshot.json` | rebuildable environment |",
        "| `../environment_check.json` | paper-declared vs actual versions |",
        "| `../parameters.json` | three-source executable parameter table |",
        "| `../comparison.json` | pre-declared tolerance comparison |",
        "| `../attribution.json` | verifiable difference hypotheses + grade |",
        "| `../execution.json` | real command, exit code, stdout/stderr |",
        "| `../repro_report.md` | evidence-linked human report |",
        "| `../result.json` | output_contract answer file (fill this) |",
        "| `evidence_index.json` | page/line text for precise citations |",
        "| `run_log.jsonl` | step-by-step run trace |", "",
        "Missing / unreadable / conflicting items must also appear in `result.json.uncertainty`.",
    ]
    write_text(out / "repro" / "index.md", "\n".join(index) + "\n")
    log.step("done", "ok", grade=attrib.get("grade"),
             n_comparisons=comparison.get("counts", {}).get("total"))
    print(json.dumps({"status": "ok", "case_id": cid, "grade": attrib.get("grade"),
                      "contract_shape": shape, "n_contract_fields": len(fields),
                      "n_materials": ledger.get("n_files"),
                      "comparisons": comparison.get("counts"),
                      "external_verified": external.get("n_sources", 0),
                      "out": str(out)}, ensure_ascii=False))
    return 0


def cmd_locate(args) -> int:
    out = Path(args.out).resolve()
    idx = read_json(out / "repro" / "evidence_index.json", {"documents": []})
    hits = pdf_text.locate(idx, args.q, max_hits=args.limit)
    print(json.dumps({"query": args.q, "n_hits": len(hits), "hits": hits},
                     ensure_ascii=False, indent=2))
    return 0 if hits else 2


def cmd_execute(args) -> int:
    out = Path(args.out).resolve()
    log = RunLog(out)
    t0 = time.time()
    rec = {"status": "ok", "command": args.cmd, "cwd": args.cwd or os.getcwd(),
           "started_at": now_iso(), "exit_code": None}
    try:
        p = subprocess.run(args.cmd, shell=True, cwd=rec["cwd"], capture_output=True,
                           timeout=args.timeout)
        rec["exit_code"] = p.returncode
        rec["stdout"] = p.stdout.decode("utf-8", "replace")[-20000:]
        rec["stderr"] = p.stderr.decode("utf-8", "replace")[-20000:]
        rec["status"] = "ok" if p.returncode == 0 else "failed"
    except subprocess.TimeoutExpired as exc:
        rec.update(status="failed", exit_code=None,
                   stderr=f"TIMEOUT after {args.timeout}s: {exc}")
    except Exception as exc:  # noqa: BLE001
        rec.update(status="failed", exit_code=None,
                   stderr=f"{type(exc).__name__}: {exc}")
    rec["elapsed_s"] = round(time.time() - t0, 3)
    rec["note"] = "Actual subprocess result; nothing here is simulated."
    write_json(out / "execution.json", rec)
    log.step("execute", rec["status"], command=args.cmd,
             exit_code=rec["exit_code"], elapsed_s=rec["elapsed_s"])
    print(json.dumps({k: rec.get(k) for k in ("status", "exit_code", "elapsed_s")},
                     ensure_ascii=False))
    return 0 if rec["status"] == "ok" else 2


def cmd_finalize(args) -> int:
    out = Path(args.out).resolve()
    case_path = Path(args.case) if args.case and Path(args.case).exists() else None
    case = load_case(case_path)
    fields, shape = contract_fields(case)
    cid = case_id_of(case, case_path)
    result = read_json(out / "result.json", {})
    problems, notes = [], []

    for f in fields:
        if f not in result:
            problems.append(f"missing output_contract field: {f}")
        elif result[f] is None:
            notes.append(f"field `{f}` is null; justify it in uncertainty if unverifiable")
    if result.get("case_id") != cid:
        problems.append(f"case_id mismatch: got {result.get('case_id')!r}, want {cid!r}")
    # output_contract may itself declare status/uncertainty/etc. The skeleton
    # sets contract fields to null; normalise the list-typed ones here so a
    # contract/meta name collision cannot crash finalization.
    for k in ("sources", "uncertainty", "change_records", "limits"):
        if not isinstance(result.get(k), list):
            result[k] = []
            notes.append(f"initialised `{k}` to an empty list (was missing or null)")
    if result.get("status") is None:
        result["status"] = "partial"
        notes.append("status was null; initialised to 'partial' (fill it after answering)")
    if result.get("status") not in ("success", "partial", "failed", "indeterminate"):
        problems.append(f"invalid status: {result.get('status')!r}")
    if result.get("status") == "partial" and not result.get("limits"):
        notes.append("status=partial but `limits` is empty; state what is incomplete")
    if not result.get("uncertainty"):
        notes.append("uncertainty is empty: confirm there are truly no missing/conflicting items")

    ledger = read_json(out / "materials_ledger.json", {"checklist": []})
    for g in ledger.get("checklist", []):
        if g.get("status") == "missing":
            tag = f"missing_material:{g['category']}"
            if not any(tag in json.dumps(u, ensure_ascii=False)
                       for u in (result.get("uncertainty") or [])):
                notes.append(f"missing category `{g['category']}` not yet reflected in uncertainty")

    report = {"generated_at": now_iso(), "case_id": cid, "contract_shape": shape,
              "n_contract_fields": len(fields), "problems": problems, "notes": notes,
              "verdict": "PASS" if not problems else "NEEDS_ATTENTION"}
    write_json(out / "validation.json", report)
    write_json(out / "result.json", result)
    RunLog(out).step("finalize", report["verdict"],
                     n_problems=len(problems), n_notes=len(notes))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not problems else 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # `dest` must NOT be "cmd": the execute subparser also defines --cmd and
    # would overwrite the subcommand name (argparse uses one shared namespace).
    sub = ap.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run the full seven-stage automated audit")
    r.add_argument("--case", default=DEFAULT_CASE)
    r.add_argument("--task", default=DEFAULT_TASK)
    r.add_argument("--inputs", nargs="*", default=None,
                   help="material directories/files; defaults to the case.json directory")
    r.add_argument("--work", default=DEFAULT_WORK)
    r.add_argument("--out", default=DEFAULT_OUT)

    l = sub.add_parser("locate", help="find precise page/line evidence")
    l.add_argument("--out", default=DEFAULT_OUT)
    l.add_argument("--q", required=True)
    l.add_argument("--limit", type=int, default=20)

    e = sub.add_parser("execute", help="actually run a reproduction command")
    e.add_argument("--out", default=DEFAULT_OUT)
    e.add_argument("--cmd", required=True)
    e.add_argument("--cwd", default=None)
    e.add_argument("--timeout", type=int, default=600)

    f = sub.add_parser("finalize", help="validate result.json against output_contract")
    f.add_argument("--case", default=DEFAULT_CASE)
    f.add_argument("--out", default=DEFAULT_OUT)

    args = ap.parse_args()
    return {"run": cmd_run, "locate": cmd_locate,
            "execute": cmd_execute, "finalize": cmd_finalize}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
