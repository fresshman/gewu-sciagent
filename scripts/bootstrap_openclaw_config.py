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

`--intern-api-key`（默认取当前 shell 的 `INTERN_API_KEY`）会写进产物里 sci-data 的 `env` 段。
这一步不能省：实测 openclaw 起 stdio MCP 子进程只给 15 个键的环境白名单，网关 export 的变量
不透传；而 env 里留未解析的 `${...}` 会让整个 sci-data 静默不启动。所以拿到真值才注入，
拿不到就不加，并在检查里明确 warn（模板与仓库里任何时候都不出现 Key 明文）。
"""
from __future__ import annotations

import argparse
import difflib
import os
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


VL_SERVER = "sci-data"


def json_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def inject_vl_key(text: str, api_key: str) -> tuple[str, str]:
    """把 InternVL 用的 API Key 写进产物里 sci-data 的 env 段（产物在仓库外，模板不含 Key）。

    为什么必须走这条路（2026-11-04 实测）：openclaw 起 stdio MCP 子进程时只给一个
    **15 个键的环境白名单**（PATH/TEMP/USERPROFILE/SYSTEMROOT…），网关自己 export 的
    变量不会透传进子进程；只有 mcp.servers.<name>.env 里的条目会合并进去。
    所以「在起网关的 shell 里 export INTERN_API_KEY」对这个工具是不够的。

    为什么只在拿到真值时才注入（同一轮实测）：env 值里留 `${INTERN_API_KEY}` 而该变量
    未设置时，**整个 sci-data 会静默不启动**——`openclaw mcp probe` 无输出、退出码还是 0。
    那比少一个工具严重得多，所以宁可不注入。
    """
    if not api_key:
        return text, ""
    m = re.search(rf'"{VL_SERVER}"\s*:\s*\{{\n(?P<body>.*?)\n[ ]*\}}', text, re.S)
    if not m:
        return text, f"⚠ 模板里找不到 {VL_SERVER} 段，未注入 Key"
    body = m.group("body")
    if re.search(r"^\s*env\s*:", body, re.M):
        # 用 (?m)^ 锚行首：body 是「{ 之后的第一行」开头，前面没有 \n，
        # 若写成 (\n\s*env...) 会匹配不到第一行的 env，导致重跑时不更新 Key。
        new_body = re.sub(r'(?m)^(\s*env\s*:\s*\{)[^}]*\}',
                          rf'\1 INTERN_API_KEY: "{json_escape(api_key)}" }}', body, count=1)
        action = "更新"
    else:
        indent = re.match(r"[ ]*", body.split("\n", 1)[0]).group(0)
        new_body = f'{indent}env: {{ INTERN_API_KEY: "{json_escape(api_key)}" }},\n' + body
        action = "新增"
    out = text[: m.start("body")] + new_body + text[m.end("body") :]
    return out, f"{action} {VL_SERVER}.env.INTERN_API_KEY（len={len(api_key)}，值不打印）"


def redact(text: str, secret: str) -> str:
    """任何要打印到终端/diff 的文本都先过一遍：Key 明文绝不进 stdout（会落进日志与轨迹表）。"""
    if not secret:
        return text
    return text.replace(secret, f"sk-***REDACTED(len={len(secret)})***")


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

    # sci-data 的 env：parse_figure 能不能拿到视觉模型 Key，取决于这里有没有注入
    m = re.search(r'"sci-data"\s*:\s*\{(?P<body>.*?)\n[ ]*\}', text, re.S)
    if not m:
        res.append(("fail", "找不到 mcp.servers.sci-data 段"))
    else:
        body = m.group("body")
        if "${" in body:
            res.append(("fail", "sci-data.env 里仍有未解析的 ${...}：这个 server 会静默不启动"
                               "（实测 `openclaw mcp probe` 无输出且退出码 0）"))
        elif re.search(r'env\s*:\s*\{[^}]*INTERN_API_KEY\s*:\s*"[^"]+"', body):
            res.append(("ok", "sci-data.env 已带 INTERN_API_KEY，parse_figure 可直接调书生视觉模型"))
        else:
            res.append(("warn", "sci-data.env 未带 INTERN_API_KEY：parse_figure 会返回 status=missing_key"
                               "（其余 4 个工具不受影响）。给 --intern-api-key，或先 export 再重跑本脚本"))

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


def _node_gate_ok(ver: str) -> bool:
    """openclaw 的 Node 版本闸门：≥24.16 且 <25，或 ≥26.1。"""
    m = re.match(r"v?(\d+)\.(\d+)", ver or "")
    if not m:
        return False
    major, minor = int(m.group(1)), int(m.group(2))
    return (major == 24 and minor >= 16) or (major == 26 and minor >= 1) or major > 26


def find_node() -> str:
    """自动挑一个满足 openclaw 闸门的 node：优先 PATH，其次常见便携安装目录。

    实测动机：本机 PATH 上的 node 常是 v22（WorkBuddy 自带），不满足闸门会直接
    被 openclaw 拒绝启动；但机器上往往还有 tools/node26 或 versions 目录里的合规
    版本。零参数跑本脚本时应自动挑到合规的那个，而不是让产物留一个起不来的解释器。
    """
    import glob
    cands: list[str] = []
    w = shutil.which("node")
    if w:
        cands.append(w)
    home = os.path.expanduser("~")
    for pat in (
        os.path.join(home, "tools", "node26", "*", "node.exe"),
        os.path.join(home, ".workbuddy", "binaries", "node", "versions", "*", "node.EXE"),
    ):
        cands.extend(sorted(glob.glob(pat)))
    for c in cands:
        if os.path.exists(c) and _node_gate_ok(node_version(c)):
            return c
    return w or ""


def find_venv_python(env_name: str, module: str) -> str:
    """探测 WorkBuddy 托管的独立 venv，并验证目标模块确实可导入。

    只按目录名猜路径不够：venv 存在但没装包同样起不来（paper-search / office-word
    常是后装的）。这里用 `import <module>` 做一次真实探针，避免生成"看起来成功"的配置。
    """
    import subprocess
    home = os.path.expanduser("~")
    for c in (
        os.path.join(home, ".workbuddy", "binaries", "python", "envs", env_name, "Scripts", "python.exe"),
        os.path.join(home, ".workbuddy", "binaries", "python", "envs", env_name, "bin", "python"),
    ):
        if not os.path.exists(c):
            continue
        try:
            r = subprocess.run([c, "-c", f"import {module}"], capture_output=True, timeout=60)
            if r.returncode == 0:
                return c
        except (OSError, subprocess.SubprocessError):
            pass
    return ""


def detect_coal_root() -> str:
    """从仓库根的 .coal_project_root（已 gitignore）读外部煤项目根，路径存在才返回。"""
    hint = REPO_ROOT / ".coal_project_root"
    if hint.exists():
        v = hint.read_text(encoding="utf-8").strip()
        if v and os.path.exists(v):
            return v
    return ""


def inject_coal_env(text: str, coal_python: str, coal_root: str) -> tuple[str, str]:
    """把 GEWU_COAL_PYTHON / COAL_PROJECT_ROOT 注入 mil-model 的 env 段。

    为什么需要：mil-model 以 subprocess 拉起 coal_infer.py，而 openclaw 给 stdio
    子进程的是 15 键白名单，shell 里 export 的变量不会透传。mil_model 自身虽有
    「按名探测 coal-torch + 读 .coal_project_root」的兜底，但依赖固定目录名；
    对换了 venv 名/路径的机器，显式注入 env 才稳。两者都探测不到就不注入，让
    mil-model 返回 not-configured（诚实降级，不编数）。
    """
    if not coal_python and not coal_root:
        return text, ""
    m = re.search(r'"mil-model"\s*:\s*\{\n(?P<body>.*?)\n[ ]*\}', text, re.S)
    if not m:
        return text, "⚠ 模板里找不到 mil-model 段，未注入 coal env"
    pairs: list[str] = []
    if coal_python:
        pairs.append(f'GEWU_COAL_PYTHON: "{json_escape(as_posix(coal_python))}"')
    if coal_root:
        pairs.append(f'COAL_PROJECT_ROOT: "{json_escape(as_posix(coal_root))}"')
    body = m.group("body")
    joined = ", ".join(pairs)
    if re.search(r"^\s*env\s*:", body, re.M):
        # 同 inject_vl_key：body 首行没有前置 \n，必须用 (?m)^ 锚行首才能命中。
        new_body = re.sub(r'(?m)^(\s*env\s*:\s*\{)[^}]*\}', rf'\1 {joined} }}', body, count=1)
        action = "更新"
    else:
        indent = re.match(r"[ ]*", body.split("\n", 1)[0]).group(0)
        new_body = f"{indent}env: {{ {joined} }},\n" + body
        action = "新增"
    out = text[: m.start("body")] + new_body + text[m.end("body") :]
    names = " + ".join(p.split(":", 1)[0] for p in pairs)
    return out, f"{action} mil-model.env（{names}）"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成网关配置（模板 → ~/.openclaw/openclaw.json）")
    ap.add_argument("--target", default=str(DEFAULT_TARGET), help="输出文件，默认 ~/.openclaw/openclaw.json")
    ap.add_argument("--python", default=sys.executable,
                    help="自研 MCP server 的解释器，默认当前 python。**请用装了 mcp<2/numpy/… 的那个 env 跑本脚本**")
    ap.add_argument("--node", default="",
                    help="chart-cloud 用的 Node；默认自动挑满足 openclaw 闸门的版本（PATH → tools/node26 → versions）")
    ap.add_argument("--paper-python", default="", help="paper-search-mcp 所在 venv 的 python；默认自动探测 envs/paper-search")
    ap.add_argument("--office-python", default="", help="office-word-mcp-server 所在 venv 的 python；默认自动探测 envs/office-word")
    ap.add_argument("--coal-python", default="",
                    help="含 torch 的解释器（mil-model 真实推理）；默认自动探测 envs/coal-torch 或 envs/gewu")
    ap.add_argument("--coal-root", default="", help="外部煤项目根；默认读仓库根 .coal_project_root")
    ap.add_argument("--intern-api-key", default=os.environ.get("INTERN_API_KEY", ""),
                    help="写进 sci-data.env 的书生 API Key；缺省取当前 shell 的 INTERN_API_KEY，"
                         "都没有就不注入（parse_figure 会返回 missing_key，其余工具不受影响）")
    ap.add_argument("--write", action="store_true", help="落盘；目标已存在则先备份")
    ap.add_argument("--check", action="store_true", help="只检查，有问题返回退出码 1")
    args = ap.parse_args(argv)

    if not TEMPLATE.exists():
        print(f"✗ 模板不存在：{TEMPLATE}")
        return 2

    raw = TEMPLATE.read_text(encoding="utf-8")

    # 自动探测：显式传入优先，其次自动找。目标是「零参数也能生成一份起得来的配置」。
    node = args.node or find_node()
    paper_py = args.paper_python or find_venv_python("paper-search", "paper_search_mcp")
    office_py = args.office_python or find_venv_python("office-word", "word_document_server")
    coal_py = (args.coal_python
               or find_venv_python("coal-torch", "torch")
               or find_venv_python("gewu", "torch"))
    coal_root = args.coal_root or detect_coal_root()

    bins = {"python": args.python, "node": node,
            "paper-python": paper_py, "office-python": office_py}
    text, notes, unresolved = substitute(raw, bins)
    text, coal_note = inject_coal_env(text, coal_py, coal_root)
    if coal_note:
        notes.append(coal_note)
    key = (args.intern_api_key or "").strip()
    text, vl_note = inject_vl_key(text, key)
    if vl_note:
        notes.append(vl_note)

    print(f"模板：{TEMPLATE}")
    print(f"仓库根：{REPO_ROOT}")
    print(f"目标：{args.target}")
    print(f"当前状态：{'已存在' if Path(args.target).exists() else '不存在（全新机器）'}")
    nv = node_version(node)
    if nv:
        print(f"Node：{node}（{nv}）")
    if notes:
        print("\n替换动作：")
        for n in notes:
            print(f"  · {redact(n, key)}")
    else:
        print("\n替换动作：（无需替换，模板已是本机路径）")

    print("\n检查结论：")
    failed = False
    for level, msg in checks(text, unresolved, nv):
        icon = {"ok": "✓", "warn": "⚠", "fail": "✗"}[level]
        print(f"  {icon} {redact(msg, key)}")
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
            print(redact("\n".join(diff[:80]), key))
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
