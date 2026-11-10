#!/usr/bin/env python
"""成本审计：把「一次完整课题要花多少钱」算成可复核的数字，而不是拍一个区间。

为什么需要这个脚本
------------------
评审问的是「一次多少钱」，此前的仓库**答不出来**：没有账单埋点、没有 token 台账，
README 里也找不到任何单价与用量。本脚本用 tiktoken 对**真实落盘产物**分词，
把用量变成可复算的量，再乘公开单价得到成本。

它诚实到什么程度（必须和数字一起读）
------------------------------------
* **输出侧是实测**：对 7 个 handoff JSON 与论文 `main.tex` 真分词，不是估。
* **输入侧是重构下界**：每阶段的真实 prompt（系统提示 + 工具定义 + 完整会话历史）
  只有运行时才知道，仓库里没有埋点。这里用「该 agent 的 AGENTS.md + 它挂的技能文档
  + 上一阶段 handoff」近似，**没有**把工具 schema、系统提示、重试算进去 ——
  所以真实输入必然大于此值，本脚本给出的是**下界**。
* **重试与失败重跑没有计入**：一次真跑会有返工，倍数未知，不给编造的乘数。
* **单价是公开牌价**，脚本内嵌并写明来源与查询日期；不臆造企业折扣。

分词器的选择：tiktoken 的 `o200k_base` 与 `cl100k_base` 都不是 Intern / DeepSeek 的
原生分词器，中文密度会差 10%–20%。所以同时给两个分词器的结果，**把差异当作误差带**，
不挑一个更好看的数字单独引用。

用法
----
    python scripts/cost_audit.py                    # 打印表格
    python scripts/cost_audit.py --json             # 打印 JSON
    python scripts/cost_audit.py --ledger docs/verification/cost_audit.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import time

try:
    import tiktoken
except ImportError:  # pragma: no cover - 只在缺依赖时触发
    raise SystemExit("需要 tiktoken：pip install tiktoken")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENC = None


def _enc():
    global ENC
    if ENC is None:
        ENC = {"o200k_base": tiktoken.get_encoding("o200k_base"),
               "cl100k_base": tiktoken.get_encoding("cl100k_base")}
    return ENC


def tok(text: str) -> dict:
    e = _enc()
    return {k: len(v.encode(text, disallowed_special=())) for k, v in e.items()}


def tok_file(path: str) -> dict:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return tok(f.read())
    except OSError:
        return {"o200k_base": 0, "cl100k_base": 0}


def _sum(parts: list[dict]) -> dict:
    out = {"o200k_base": 0, "cl100k_base": 0}
    for p in parts:
        for k in out:
            out[k] += p[k]
    return out


# 7 阶段：代理目录 -> 该阶段 handoff 产物
STAGES = [
    (1, "gewu-director", "handoff_1_direction.json", "方向立项"),
    (2, "gewu-ideation", "handoff_2_litreview.json", "文献调研"),
    (3, "gewu-reproduction", "handoff_3_repro.json", "复现基线"),
    (4, "gewu-improver", "handoff_4_improver.json", "改进与消融"),
    (5, "gewu-writer", "handoff_5_writer.json", "撰写"),
    (6, "gewu-publication", "handoff_6_publication.json", "投稿匹配"),
    (7, "gewu-distillation", "handoff_7_distillation.json", "沉淀"),
]

# 公开牌价（每百万 tokens）。来源与查询日期写死在数据里，避免口径漂移无人负责。
PRICES = [
    {
        "model": "DeepSeek-V4-Flash（空闲时段）",
        "input_per_mtok": 1.5, "output_per_mtok": 4.5, "currency": "CNY",
        "source": "腾讯网转央视财经《DeepSeek调价，今日生效》(2026-08-17)：空闲 V4-Flash 输入 1.5 元、输出 4.5 元/百万 tokens",
        "retrieved": "2026-11-10",
    },
    {
        "model": "DeepSeek-V4-Flash（高峰时段）",
        "input_per_mtok": 3.0, "output_per_mtok": 9.0, "currency": "CNY",
        "source": "同上（高峰为闲时两倍）",
        "retrieved": "2026-11-10",
    },
    {
        "model": "DeepSeek-V4-Pro（空闲时段）",
        "input_per_mtok": 4.5, "output_per_mtok": 13.5, "currency": "CNY",
        "source": "同上：空闲 V4-Pro 输入 4.5 元、输出 13.5 元/百万 tokens",
        "retrieved": "2026-11-10",
    },
]


def stage_rows():
    rows = []
    prev = {"o200k_base": 0, "cl100k_base": 0}
    for idx, agent, handoff, label in STAGES:
        adir = os.path.join(REPO_ROOT, "openclaw", "workspace", "agents", agent)
        instr_files = [os.path.join(adir, "AGENTS.md")]
        instr_files += sorted(glob.glob(os.path.join(adir, "skills", "**", "*.md"), recursive=True))
        instr_files = [p for p in instr_files if os.path.exists(p)]
        instr = _sum([tok_file(p) for p in instr_files])
        out_path = os.path.join(adir, handoff)
        out = tok_file(out_path)
        rows.append({
            "stage": idx,
            "agent": agent,
            "label": label,
            "instruction_files": len(instr_files),
            "instruction_tokens": instr,
            "context_tokens": prev,
            "output_tokens": out,
            "output_path": os.path.relpath(out_path, REPO_ROOT).replace("\\", "/"),
            "output_exists": os.path.exists(out_path),
        })
        prev = out
    return rows


def deliverable_rows():
    out = []
    paper = os.path.join(REPO_ROOT, "output", "documents", "coal_report", "main.tex")
    if os.path.exists(paper):
        out.append({"name": "论文 LaTeX 正文（未入库，本机存档）",
                    "path": "output/documents/coal_report/main.tex",
                    "bytes": os.path.getsize(paper), "tokens": tok_file(paper)})
    for p in sorted(glob.glob(os.path.join(REPO_ROOT, "reports", "*.json"))):
        out.append({"name": f"产物 {os.path.basename(p)}",
                    "path": os.path.relpath(p, REPO_ROOT).replace("\\", "/"),
                    "bytes": os.path.getsize(p), "tokens": tok_file(p)})
    return out


def build():
    rows = stage_rows()
    deliverables = deliverable_rows()

    out_tokens = _sum([r["output_tokens"] for r in rows])
    in_tokens = _sum([r["instruction_tokens"] for r in rows] + [r["context_tokens"] for r in rows])
    deliverable_tokens = _sum([d["tokens"] for d in deliverables])

    costs = []
    # 输出侧要算上「论文正文」这类交付物：它们同样是模型产出，只统计 handoff 会把成本报小。
    # 代码（*.py）也是人机混合产出，无法归因，明确不计入。
    out_tokens_total = _sum([out_tokens, deliverable_tokens])
    for p in PRICES:
        base_lo = (in_tokens["o200k_base"] * p["input_per_mtok"]
                   + out_tokens_total["o200k_base"] * p["output_per_mtok"]) / 1_000_000
        base_hi = (in_tokens["cl100k_base"] * p["input_per_mtok"]
                   + out_tokens_total["cl100k_base"] * p["output_per_mtok"]) / 1_000_000
        costs.append({
            "model": p["model"],
            "currency": p["currency"],
            "cost_range": [round(base_lo, 4), round(base_hi, 4)],
            "sensitivity_by_retry_multiplier": {
                str(m): [round(base_lo * m, 4), round(base_hi * m, 4)] for m in (1, 3, 10)
            },
            "source": p["source"],
            "retrieved": p["retrieved"],
        })

    return {
        "schema_version": "1.0",
        "method": "tiktoken 对真实落盘产物分词；输出侧实测，输入侧为重构下界（不含系统提示/工具 schema/重试/会话历史）",
        "measured_at_local": time.strftime("%Y-%m-%d %H:%M:%S"),
        "gewu_commit": _git_commit(),
        "stages": rows,
        "deliverables": deliverables,
        "totals": {
            "output_tokens": out_tokens,
            "input_tokens_lower_bound": in_tokens,
            "deliverable_tokens": deliverable_tokens,
            "deliverable_count": len(deliverables),
            "output_tokens_counted_for_cost": out_tokens_total,
            "cost_counting_rule": "输出侧计入 handoff 与论文正文等文本交付物；导出的 *.py 代码为人机混合产出，无法归因，不计入",
            "local_compute_cost_cny": 0.0,
            "local_compute_note": "全部推理在自备 CPU 上完成（torch CPU / sklearn / tectonic），无租卡费用；电费忽略不计，未计",
        },
        "pricing": PRICES,
        "cost_per_full_run": costs,
        "caveats": [
            "输入侧是下界：真实 prompt 含系统提示、工具 schema、会话历史，仓库无埋点，无法精确还原",
            "未计重试与失败重跑；一次真跑通常有 1–3 次返工",
            "分词器非模型原生（o200k/cl100k 对中文密度与 Intern/DeepSeek 原生差 10%–20%），故给两个分词器的区间",
            "本机无 API key，无法给出账单级实测；上述为「按公开牌价 × 真实产物用量」的复算，不是账单",
            "分词器编码表首次调用需联网拉取（约 1 MB），之后离线可用；完全断网且无缓存时本脚本不可用",
            "论文存档（output/documents/）按设计不入库：干净 clone 里 deliverable_count=0，输出侧少约 13k tokens，"
            "成本随之下移（实测 0.22–0.26 元 vs 仓库内 0.25–0.29 元）。两个数都对，差别是环境，不是口径",
        ],
    }


def _git_commit() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True,
                           text=True, timeout=10, stdin=subprocess.DEVNULL)
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def main(argv=None):
    ap = argparse.ArgumentParser(description="一次完整课题的 token 用量与成本审计")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--ledger", default="", help="落盘 JSON 路径")
    args = ap.parse_args(argv)

    data = build()
    if args.ledger:
        os.makedirs(os.path.dirname(os.path.abspath(args.ledger)) or ".", exist_ok=True)
        with open(args.ledger, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    if args.json:
        print(json.dumps(data, ensure_ascii=False))
        return 0

    print("阶段               指令(下界)      上游上下文      产出")
    for r in data["stages"]:
        print(f"  {r['stage']} {r['label']:<8} "
              f"{r['instruction_tokens']['o200k_base']:>9,}  "
              f"{r['context_tokens']['o200k_base']:>12,}  "
              f"{r['output_tokens']['o200k_base']:>8,}")
    t = data["totals"]
    print(f"\n输出侧（实测）：        {t['output_tokens']['o200k_base']:,} tokens (o200k)"
          f" / {t['output_tokens']['cl100k_base']:,} (cl100k)")
    print(f"输入侧（重构下界）：    {t['input_tokens_lower_bound']['o200k_base']:,} tokens (o200k)"
          f" / {t['input_tokens_lower_bound']['cl100k_base']:,} (cl100k)")
    print(f"额外交付物（论文等）：  {t['deliverable_tokens']['o200k_base']:,} tokens")
    print(f"计入成本的输出合计：    {t['output_tokens_counted_for_cost']['o200k_base']:,} tokens"
          f"（handoff + 论文正文；代码不计，见口径）")
    print("\n按公开牌价折算（一次完整课题，仅成功链路）：")
    for c in data["cost_per_full_run"]:
        lo, hi = c["cost_range"]
        print(f"  {c['model']:<26} {lo:.4f} – {hi:.4f} {c['currency']}")
    print("\n返工敏感性（同一牌价，按重跑倍数放大；倍数是假设，不是实测）：")
    for c in data["cost_per_full_run"][:1]:
        for m, (lo, hi) in c["sensitivity_by_retry_multiplier"].items():
            print(f"  ×{m:<3} {lo:.3f} – {hi:.3f} CNY")
    print("\n本地算力：0 元（自备 CPU；电费未计）")
    print("注意：" + data["caveats"][0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
