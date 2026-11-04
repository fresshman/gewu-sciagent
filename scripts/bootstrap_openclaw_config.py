#!/usr/bin/env python3
"""把仓库里的 openclaw/openclaw.json 模板生成为网关真正读取的配置。

为什么需要这一步：模板里有 26 处指向仓库根的绝对路径（网关 workspace + 7 个角色工作区 +
各 MCP 的 args/cwd），另有 10 处解释器写成 `C:/Users/<user>/...`。换一台机器照 README 手改
这些行既容易漏、又没法验证，是「成果可复现性」最直接的坑。本脚本按当前仓库根与指定解释器
重写，产出可直接放进 ~/.openclaw/openclaw.json 的文件，并把结果交给一组检查。

模板是带注释的 JSONC（键不加引号、有 // 注释），**不能 json.load**，所以这里做
纯文本前缀替换而不是解析——这样产物的结构与模板逐字同构，注释也保留。

用法：
    python scripts/bootstrap_openclaw_config.py             # 干跑：打印替换清单、检查结论、与现有配置的 diff
    python scripts/bootstrap_openclaw_config.py --check     # 只做检查，有问题退出码非 0
    python scripts/bootstrap_openclaw_config.py --write     # 落盘（已存在则先备份）
    python scripts/bootstrap_openclaw_config.py --target /tmp/x.json --write

`--python` 默认取**运行本脚本的解释器**，所以请用装了 mcp<2/numpy/pymupdf 的那个 venv 跑它；
`--node`（chart-cloud）默认取 PATH 上的 node 并校验 openclaw 的版本闸门；两个外部包的
`--paper-python` / `--office-python` 不给就保留占位，并由检查报 fail（不给 = 明确失败，
比生成一份"看起来成功了"的配置好）。
"""
from __future__ import annotations

import argparse
import difflib
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "openclaw" / "openclaw.json"
DEFAULT_TARGET = Path.home() / ".openclaw" / "openclaw.json"

# 模板里写死的仓库根（换机必须重写）。用正斜杠，与模板保持一致。
TEMPLATE_REPO_ROOT = "F:/python-exercise/Industrial_LLM/langchain-learn/gewu-sciagent"

# 模板里以 C:/Users/<user>/... 形式书写的解释器占位。每一项给出：
#   (占位全文, CLI 参数名, 是否必须解析)
# 必须项覆盖 7 个自研 Python server 共用的 default 环境与 chart-cloud 用的 node；
# 两个外部包（paper-search / office-word）各装各的 venv，没提供时保留占位并由检查报 fail。
PLACEHOLDER_BINS = [
    ("C:/Users/<user>/.workbuddy/binaries/python/envs/default/Scripts/python.exe",
     "python", True, "7 个自研 Python MCP server 的解释器（需含 mcp<2/numpy/sklearn/scipy/pymupdf）"),
    ("C:/Users/<user>/tools/node26/node-v26.9.0-win-x64/node.exe",
     "node", True, "chart-cloud 用的 Node（openclaw 要求 ≥24.16 且 <25，或 ≥26.1）"),
    ("C:/Users/<user>/.workbuddy/binaries/python/envs/paper-search/Scripts/python.exe",
     "paper-python", False, "paper-search-mcp 所在 venv 的 Python"),
    ("C:/Users/<user>/.workbuddy/binaries/python/envs/office-word/Scripts/python.exe",
     "office-python", False, "office-word-mcp-server 所在 venv 的 Python"),
]


def as_posix(p: str | Path) -> str:
    r"""统一成正斜杠。JSONC 字符串里的反斜杠是非法转义，所以绝不往产物里留反斜杠。"""
    return Path(p).as_posix()


def substitute(text: str, bins: dict[str, str]) -> tuple[str, list[str], list[str]]:
    """返回 (结果文本, 替换说明, 未解析占位)。纯文本替换，保注释与结构。

    模板是带注释的 JSONC（键不加引号），解析再序列化会丢注释并改写格式，
    所以这里只做前缀替换——产物与模板逐字同构，diff 也能只反映路径变化。
    """
    notes: list[str] = []
    unresolved: list[str] = []
    out = text

    actual_root = as_posix(REPO_ROOT)
    n = out.count(TEMPLATE_REPO_ROOT)
    if n:
        out = out.replace(TEMPLATE_REPO_ROOT, actual_root)
        notes.append(f"仓库根（{n} 处）{TEMPLATE_REPO_ROOT} → {actual_root}")

    for placeholder, arg, required, hint in PLACEHOLDER_BINS:
        cnt = out.count(placeholder)
        if not cnt:
            continue
        value = bins.get(arg, "")
        if value:
            out = out.replace(placeholder, as_posix(value))
            notes.append(f"{arg}（{cnt} 处）→ {as_posix(value)}")
        elif required:
            unresolved.append(f"{arg}：{placeholder}（{cnt} 处，必须给 --{arg}）")
        else:
            unresolved.append(f"{arg}（可选，{cnt} 处）：{placeholder} —— {hint}")

    return out, notes, unresolved


def checks(text: str, unresolved: list[str], node_ver: str = "") -> list[tuple[str, str]]:
    """返回 [(级别, 说明)]。级别 ∈ ok / warn / fail。"""
    res: list[tuple[str, str]] = []

    if node_ver:
        # openclaw 的版本闸门：Node ≥24.16 且 <25，或 ≥26.1。不满足时网关直接拒绝启动，
        # 而报错来自 openclaw 而不是本脚本，所以在这里提前判掉。
        m = re.match(r"v?(\d+)\.(\d+)", node_ver)
        if m:
            major, minor = int(m.group(1)), int(m.group(2))
            ok = (major == 24 and minor >= 16) or (major == 26 and minor >= 1) or major > 26
            res.append(("ok" if ok else "fail",
                        f"Node {node_ver} {'满足' if ok else '不满足'} openclaw 闸门（24.16 ≤ v < 25，或 v ≥ 26.1）"))

    required_missing = [u for u in unresolved if u.startswith(("python：", "node："))]
    optional_left = [u for u in unresolved if not u.startswith(("python：", "node："))]
    if required_missing:
        for u in required_missing:
            res.append(("fail", f"未解析必需占位 {u}"))
    if optional_left:
        for u in optional_left:
            res.append(("warn", f"保留占位 {u}"))
    left = len(re.findall(r'command:\s*"[^"]*<user>[^"]*"', text))
    if left:
        res.append(("fail", f"产物里仍有 {left} 处 MCP command 指向 `<user>` 占位，这些 server 起不来"))
    else:
        res.append(("ok", "MCP command 里无 `<user>` 占位残留（注释里的说明性 `<user>` 不计）"))

    # 大括号配平（去掉字符串里的花括号不可靠，这里按计数做粗校验）
    if text.count("{") != text.count("}"):
        res.append(("fail", f"花括号不配平：{{ = {text.count('{')}，}} = {text.count('}')}"))
    else:
        res.append(("ok", f"花括号配平（{text.count('{')} 对）"))

    servers = re.findall(r'"(sci-[a-z-]+|mil-model|report|chart-cloud|paper-search|office-word)":\s*\{', text)
    if len(servers) >= 10:
        res.append(("ok", f"MCP servers 共 {len(servers)} 个：{' '.join(sorted(set(servers)))}"))
    else:
        res.append(("fail", f"MCP servers 只解析到 {len(servers)} 个，模板应有 10 个"))

    agents = re.findall(r'"(gewu-[a-z-]+)":\s*\{', text)
    if len(agents) >= 7:
        res.append(("ok", f"Agent 条目 {len(set(agents))} 个"))
    else:
        res.append(("fail", f"Agent 条目只解析到 {len(set(agents))} 个，应有 7 个"))

    # workspace 路径是否真的存在
    for ws in sorted(set(re.findall(r'workspace:\s*"([^"]+)"', text))):
        p = Path(ws.replace("\\", "/"))
        res.append(("ok" if p.exists() else "fail", f"workspace {'存在' if p.exists() else '不存在'}：{ws}"))

    # MCP command 指向的解释器是否存在
    for cmd in sorted(set(re.findall(r'command:\s*"([^"]+)"', text))):
        p = Path(cmd.replace("\\", "/"))
        ok = p.exists() or cmd in ("python", "python3", "node")
        res.append(("ok" if ok else "warn", f"MCP command {'可用' if ok else '找不到'}：{cmd}"))

    return res


def node_version(exe: str) -> str:
    """取 node 版本字符串，用于提示 openclaw 的版本闸门（≥24.16 且 <25，或 ≥26.1）。"""
    if not exe:
        return ""
    import subprocess
    try:
        return subprocess.run([exe, "-v"], capture_output=True, text=True,
                              timeout=15).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成网关配置（模板 → ~/.openclaw/openclaw.json）")
    ap.add_argument("--target", default=str(DEFAULT_TARGET), help="输出文件，默认 ~/.openclaw/openclaw.json")
    ap.add_argument("--python", default=sys.executable,
                    help="自研 MCP server 的解释器，默认当前 python。**请用装了 mcp<2/numpy/… 的那个 env 跑本脚本**")
    ap.add_argument("--node", default=shutil.which("node") or "",
                    help="chart-cloud 用的 Node，默认取 PATH 上的 node")
    ap.add_argument("--paper-python", default="", help="paper-search-mcp 所在 venv 的 python（可选）")
    ap.add_argument("--office-python", default="", help="office-word-mcp-server 所在 venv 的 python（可选）")
    ap.add_argument("--write", action="store_true", help="落盘；目标已存在则先备份")
    ap.add_argument("--check", action="store_true", help="只检查，有问题返回退出码 1")
    args = ap.parse_args(argv)

    if not TEMPLATE.exists():
        print(f"✗ 模板不存在：{TEMPLATE}")
        return 2

    raw = TEMPLATE.read_text(encoding="utf-8")
    bins = {"python": args.python, "node": args.node,
            "paper-python": args.paper_python, "office-python": args.office_python}
    text, notes, unresolved = substitute(raw, bins)

    print(f"模板：{TEMPLATE}")
    print(f"仓库根：{REPO_ROOT}")
    print(f"目标：{args.target}")
    print(f"当前状态：{'已存在' if Path(args.target).exists() else '不存在（全新机器）'}")
    nv = node_version(args.node)
    if nv:
        print(f"Node：{args.node}（{nv}）")
    if notes:
        print("\n替换动作：")
        for n in notes:
            print(f"  · {n}")
    else:
        print("\n替换动作：（无需替换，模板已是本机路径）")

    print("\n检查结论：")
    failed = False
    for level, msg in checks(text, unresolved, nv):
        icon = {"ok": "✓", "warn": "⚠", "fail": "✗"}[level]
        print(f"  {icon} {msg}")
        failed = failed or level == "fail"

    target = Path(args.target)
    if target.exists():
        old = target.read_text(encoding="utf-8")
        if old == text:
            print("\n目标内容与生成结果一致，无需改动。")
        else:
            diff = list(difflib.unified_diff(old.splitlines(), text.splitlines(),
                                             "现有配置", "生成结果", lineterm="", n=1))
            print(f"\n与现有配置的差异（{sum(1 for d in diff if d.startswith('+') and not d.startswith('+++'))} 增 / "
                  f"{sum(1 for d in diff if d.startswith('-') and not d.startswith('---'))} 删）：")
            print("\n".join(diff[:80]))
            if len(diff) > 80:
                print(f"  …（其余 {len(diff) - 80} 行省略，加 --write 会先备份）")
    else:
        print("\n目标不存在：首次部署，--write 将新建。")

    if args.check:
        return 1 if failed else 0

    if not args.write:
        print("\n（干跑结束。加 --write 落盘；目标已存在会先备份为 openclaw.json.bak.<时间戳>）")
        return 1 if failed else 0

    if target.exists():
        bak = target.with_name(f"{target.name}.bak.{datetime.now():%Y%m%d-%H%M%S}")
        bak.write_bytes(target.read_bytes())
        print(f"已备份原文件 → {bak}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"已写入 {target}")
    print("下一步：openclaw config validate 校验，再 openclaw gateway run --force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
