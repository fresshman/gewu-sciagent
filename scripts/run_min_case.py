#!/usr/bin/env python3
"""最小课题：七阶段端到端链路（零外部数据依赖）。

用法
----
    python scripts/run_min_case.py                 # 跑全链路 + 校验
    python scripts/run_min_case.py --offline       # 不联网（D1 核验诚实降级）
    python scripts/run_min_case.py --json          # 只输出汇总 JSON（供 sci-exp rerun）
    python scripts/run_min_case.py --no-validate   # 只跑链路，不校验

为什么需要它
------------
真实课题依赖未发表的私有数据与权重，评审无法独立执行。本脚本用**合成光谱**从零
生成数据、训练、出数、成稿、投稿、沉淀，用来证明七阶段链路可自主跑完。

退出码：0 成功且校验通过；1 链路或校验失败。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from gewu.demo import pipeline, verify  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="合成数据最小课题（七阶段端到端）")
    ap.add_argument("--out", default=str(pipeline.DEFAULT_OUT), help="输出目录")
    ap.add_argument("--n-bags", type=int, default=70, help="bag 数量（默认 70）")
    ap.add_argument("--seed", type=int, default=20261109, help="随机种子")
    ap.add_argument("--offline", action="store_true", help="跳过联网核验")
    ap.add_argument("--commit-registry", action="store_true",
                    help="把注册表条目写入 gewu/mcp/registry/demo_synth.json")
    ap.add_argument("--json", action="store_true", help="stdout 只输出汇总 JSON")
    ap.add_argument("--no-validate", action="store_true", help="跳过校验")
    ap.add_argument("--emit-snapshot", action="store_true",
                    help="把聚合结果快照写入 docs/verification/min_case_snapshot.json（可入库）")
    args = ap.parse_args(argv)

    def log(msg: str) -> None:
        if not args.json:
            print(msg, flush=True)

    out = Path(args.out)
    try:
        result = pipeline.run(
            out,
            n_bags=args.n_bags,
            seed=args.seed,
            offline=args.offline,
            commit_registry=args.commit_registry,
            log=log,
        )
    except Exception as e:
        if args.json:
            print(json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
        else:
            import traceback

            traceback.print_exc()
        return 1

    rep = None
    if not args.no_validate:
        log("\n[verify] 十层校验 ...")
        rep = verify.validate(out, determinism=True)
        if not args.json:
            for r in rep["results"]:
                if r["status"] == "FAIL":
                    print(f"  FAIL [{r['layer']}] {r['check']} :: {r['detail']}")
            print(f"  校验结果: {rep['n_checks']} 项，失败 {rep['n_failed']} 项")

    if args.emit_snapshot and not args.json:
        from gewu.demo import pipeline as _p

        p = _p.write_snapshot(
            result, rep, REPO / "docs" / "verification" / "min_case_snapshot.json"
        )
        print(f"  快照已写入: {p.relative_to(REPO).as_posix()}")

    if args.json:
        payload = dict(result)
        if rep is not None:
            payload["validation"] = {"ok": rep["ok"], "n_failed": rep["n_failed"],
                                     "errors": rep["errors"]}
        print(json.dumps(payload, ensure_ascii=False))
        return 0 if (rep is None or rep["ok"]) else 1

    print("\n== 链路完成 ==")
    for arm, key in (("PLSR 基线", "plsr_baseline"), ("MIL 直接", "mil_direct"),
                     ("本方法", "our_hybrid")):
        s = result["summary"][key]
        print(f"  {arm:9s} RMSE {s['rmse_mean']:8.2f} ± {s['rmse_std']:6.2f} kcal/kg"
              f"   R²={s['r2_mean']:.3f}")
    t = result["paired_tests"]["hybrid_vs_plsr"]
    print(f"  改进 {result['improvement_pct']:.2f}% | 配对 t={t.get('t')} p={t.get('p')} "
          f"| 五折同向={t['all_same_direction']}")
    print(f"  文献核验: {result['refs_status']} | 用时 {result['elapsed_s']}s")
    print(f"  产物目录: {result['case_dir']}")
    if not args.commit_registry:
        print("  提示：加 --commit-registry 可让 sci-exp 直接 rerun 本课题")
    return 0 if (rep is None or rep["ok"]) else 1


if __name__ == "__main__":
    sys.exit(main())
