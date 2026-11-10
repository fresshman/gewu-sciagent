#!/usr/bin/env python3
"""生成 / 校验 `requirements.lock.txt`（精确版本锁）。

为什么需要锁
------------
`requirements.txt` 写的是区间（`mcp>=1.0,<2`、`numpy>=1.26`）。区间保证的是「装得上」，
不保证「装到同一套」。半年后 `numpy` 换了主版本、`scikit-learn` 改了默认参数，
论文里的数字就可能复现不出来——而失败会表现为「结果不一致」，不是「装不上」，
这是最难查的一类问题。

锁文件回答一个问题：**2026-11-10 跑出这些数字的那套包，具体是哪些版本。**

设计取舍（写清楚，免得被误当成 pip-tools）
------------------------------------------
* **不引入新依赖**：只用 `pip freeze`。不装 pip-tools / uv，评委机器零额外成本。
* **锁的是当前环境**：本脚本必须在**按 requirements.txt 装好的干净 venv** 里运行。
  如果在杂乱的全局环境里跑，锁里会混进一堆无关包——这是用法问题，脚本用警告提示。
* **锁文件里带 requirements.txt 的哈希**：`requirements.txt` 一改而锁没重生成，
  `tests/test_deps_lock.py` 会失败。锁过期是最常见的「假锁定」。
* **不锁平台**：只锁版本，不锁 wheel/哈希。跨平台（CPU/OS/架构）差异不在本锁覆盖范围，
  这一点在文件头里明写，不假装它是可复现构建（reproducible build）。

用法::

    python scripts/lock_deps.py              # 生成 requirements.lock.txt
    python scripts/lock_deps.py --check      # 校验：锁是否过期、是否覆盖全部顶层依赖、
                                             # 当前环境是否与锁一致（不一致只警告，不失败，
                                             # 因为评审机可能装的是 requirements.txt 的最新解）
    python scripts/lock_deps.py --check --strict   # 上面第三条也算失败（用于「锁定环境」自检）
"""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQ = os.path.join(REPO, "requirements.txt")
LOCK = os.path.join(REPO, "requirements.lock.txt")

_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_REQ_LINE_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*([<>=!~].*)?$")


def normalize(name: str) -> str:
    """PEP 503 归一：`PyMuPDF` / `pymupdf` / `py-mu-pdf` 视为同一个包。"""
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def parse_requirements(path: str = REQ) -> list[dict]:
    """解析 requirements.txt，返回顶层依赖（忽略注释、空行、`-r` 之类的选项行）。"""
    out = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            m = _REQ_LINE_RE.match(line)
            if not m:
                continue
            out.append({
                "raw": line,
                "name": m.group(1),
                "key": normalize(m.group(1)),
                "spec": (m.group(3) or "").strip(),
            })
    return out


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def freeze(python: str | None = None) -> dict[str, str]:
    """当前解释器的 `pip freeze`，返回 {归一包名: 版本}。"""
    py = python or sys.executable
    proc = subprocess.run([py, "-m", "pip", "freeze"], capture_output=True,
                          text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"pip freeze 失败：{proc.stderr.strip()[:400]}")
    out: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        if "==" not in line:
            # 可编辑安装 / 直接 URL —— 无法锁定，明确跳过而不是写个假版本
            continue
        name, ver = line.split("==", 1)
        out[normalize(name)] = ver.split(";")[0].strip()
    return out


def parse_lock(path: str = LOCK) -> dict[str, str]:
    """读锁文件里的 `name==version`。"""
    out: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            if "==" not in line:
                continue
            name, ver = line.split("==", 1)
            out[normalize(name)] = ver.strip()
    return out


def lock_meta(path: str = LOCK) -> dict:
    """从锁文件头读出元信息（requirements 哈希、生成环境）。"""
    meta: dict[str, str] = {}
    if not os.path.isfile(path):
        return meta
    with open(path, encoding="utf-8") as f:
        for raw in f:
            if not raw.startswith("#"):
                break   # 头部注释结束
            m = re.match(r"#\s*(requirements\.txt sha256|python|platform)\s*[:：]\s*(.+)", raw)
            if m:
                meta[m.group(1)] = m.group(2).strip()
    return meta


def build(python: str | None = None, req: str = REQ) -> str:
    tops = parse_requirements(req)
    env = freeze(python)
    py = python or sys.executable
    ver = subprocess.run([py, "-c", "import platform;print(platform.python_version())"],
                         capture_output=True, text=True, timeout=60).stdout.strip()

    missing = [t["name"] for t in tops if t["key"] not in env]
    lines = [
        "# 精确版本锁 —— 由 scripts/lock_deps.py 生成，请勿手改。",
        "# 生成命令：python scripts/lock_deps.py",
        f"# requirements.txt sha256: {file_sha256(req)}",
        f"# python: {ver}",
        f"# platform: {platform.platform()}",
        "#",
        "# 口径：只锁版本，不锁 wheel 哈希、不锁平台。换了 OS/架构/CPU 特性",
        "# （如 AVX512 与 MKL 后端差异）不在本锁覆盖范围，本文件不是可复现构建定义。",
        f"# 顶层依赖 {len(tops)} 个（来自 requirements.txt，标 [top]），其余为传递依赖。",
        "",
    ]
    if missing:
        lines.append(f"# ⚠ 以下顶层依赖在当前解释器里没装，无法锁定：{', '.join(missing)}")
        lines.append("#   锁文件不完整。请在按 requirements.txt 装好的干净 venv 里重跑本脚本。")
        lines.append("")

    top_keys = {t["key"]: t["name"] for t in tops}
    for key in sorted(top_keys):
        if key in env:
            lines.append(f"{top_keys[key]}=={env[key]}   # [top]")
    lines.append("")
    lines.append("# ---- 传递依赖 ----")
    for key in sorted(env):
        if key in top_keys:
            continue
        lines.append(f"{key}=={env[key]}")
    return "\n".join(lines) + "\n"


def check(strict_env: bool = False, req: str = REQ) -> list[str]:
    """返回问题清单；空 = 通过。"""
    problems: list[str] = []
    if not os.path.isfile(LOCK):
        return [f"锁文件不存在：{LOCK}（先跑 python scripts/lock_deps.py）"]

    tops = parse_requirements(req)
    lock = parse_lock(LOCK)
    # 顶层依赖必须被精确钉住 —— 这是锁存在的意义
    unpinned = [t["name"] for t in tops if t["key"] not in lock]
    if unpinned:
        problems.append(f"顶层依赖未出现在锁里：{', '.join(unpinned)}")

    # 锁里不允许区间/未钉版本
    with open(LOCK, encoding="utf-8") as f:
        for i, raw in enumerate(f, 1):
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            if "==" not in line:
                problems.append(f"第 {i} 行不是精确版本：{line!r}")

    meta = lock_meta(LOCK)
    want = file_sha256(req)
    got = meta.get("requirements.txt sha256", "")
    if got != want:
        problems.append(
            "锁已过期：requirements.txt 的 sha256 是 "
            f"{want[:12]}…，锁里记的是 {got[:12] or '(缺失)'}…。"
            "改了依赖却没重生成锁，等于没有锁。请重跑 python scripts/lock_deps.py"
        )

    env = freeze()
    drift = [(k, lock[k], env[k]) for k in sorted(lock) if k in env and env[k] != lock[k]]
    if drift:
        msg = "当前环境与锁不一致：" + ", ".join(f"{k} 锁 {a} / 装 {b}" for k, a, b in drift[:6])
        if len(drift) > 6:
            msg += f"（另有 {len(drift) - 6} 个）"
        msg += "。若你在按 requirements.txt 装的最新解上跑，这是预期的；要复现论文数字请按锁装。"
        (problems if strict_env else _warnings).append(msg)

    # 约束必须被锁满足（如 mcp 必须 <2，2.x 移除了 FastMCP 会直接导入失败）
    for t in tops:
        if t["key"] not in lock or not t["spec"]:
            continue
        try:
            from packaging.specifiers import SpecifierSet
            from packaging.version import Version
        except ImportError:      # pragma: no cover - packaging 由 pip 自带，通常可用
            break
        if not SpecifierSet(t["spec"]).contains(Version(lock[t["key"]])):
            problems.append(
                f"锁里 {t['name']}=={lock[t['key']]} 不满足 requirements.txt 的约束 {t['spec']}"
            )
    return problems


_warnings: list[str] = []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成/校验 requirements.lock.txt")
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    ap.add_argument("--strict", action="store_true", help="与 --check 共用：环境漂移也算失败")
    ap.add_argument("--python", default=None, help="指定解释器（默认当前）")
    args = ap.parse_args(argv)

    _warnings.clear()
    if args.check:
        problems = check(strict_env=args.strict)
        for w in _warnings:
            print(f"WARN  {w}")
        for p in problems:
            print(f"FAIL  {p}")
        if problems:
            print(f"\n锁校验未通过：{len(problems)} 个问题")
            return 1
        lock = parse_lock()
        print(f"锁校验通过：{len(lock)} 个包被精确钉住，顶层依赖全部覆盖，未过期"
              + ("（含环境一致性）" if args.strict else ""))
        return 0

    text = build(args.python)
    with open(LOCK, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    lock = parse_lock()
    # 只数真正的包行；文件头里也含 "[top]" 字样，不能拿它计数
    n_top = sum(1 for ln in text.splitlines()
                if "[top]" in ln and not ln.startswith("#"))
    print(f"已写入 {os.path.relpath(LOCK, REPO)}：{len(lock)} 个包（其中顶层 {n_top} 个）")
    if "⚠" in text:
        print("注意：锁不完整，见文件头警告。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
