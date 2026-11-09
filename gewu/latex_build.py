"""LaTeX 编译引擎：探测本机 TeX 引擎并把 .tex 编译为 .pdf。

设计约束（与格物「本地优先」一致）：
- 不假设用户装了 TeX Live（Windows 上常见没有），优先用单文件引擎 tectonic；
- 找不到任何引擎时**不静默降级为成功**，而是明确返回 ``status="no_engine"``，
  由调用方如实标注「未编译」，绝不谎报 ``pdf_compiled=True``；
- 编译产物的可信度以 log 为依据：``!`` 开头的 TeX error 与 ``Missing character``
  （字形缺失，中文场景下等于掉字）都判为失败，而不是仅看进程退出码。

探测器优先级：环境变量 ``GEWU_LATEX_ENGINE`` → ``PATH`` → 常见安装位置。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# 常见安装位置（按平台），仅作 PATH 找不到时的补充探测。
_COMMON_ENGINE_PATHS = {
    "win32": [
        r"%LOCALAPPDATA%\gewu\tools\tectonic.exe",
        r"%LOCALAPPDATA%\Programs\tectonic\tectonic.exe",
        r"%USERPROFILE%\.gewu\tools\tectonic.exe",
        r"C:\texlive\2024\bin\windows\xelatex.exe",
        r"C:\texlive\2023\bin\windows\xelatex.exe",
    ],
    "darwin": [
        "/Library/TeX/texbin/xelatex",
        "/opt/homebrew/bin/tectonic",
        "/usr/local/bin/tectonic",
        "~/.gewu/tools/tectonic",
    ],
    "linux": [
        "/usr/bin/xelatex",
        "/usr/local/bin/xelatex",
        "/usr/local/bin/tectonic",
        "~/.gewu/tools/tectonic",
    ],
}

# 引擎名 → 该引擎的命令行风格
_ENGINE_STYLE = {
    "tectonic": "tectonic",
    "xelatex": "xelatex",
    "lualatex": "lualatex",
    "pdflatex": "pdflatex",
    "latexmk": "latexmk",
}

DEFAULT_TIMEOUT = 900  # 秒；tectonic 首次编译要从 CTAN 拉 bundle，冷启动实测约 6 min


class LatexEngineError(RuntimeError):
    """引擎不可用或调用方式非法。"""


def _norm_engine(path_or_name: str) -> str:
    """把可执行文件路径或别名归一成引擎名。"""
    stem = Path(path_or_name).stem.lower()
    stem = stem.replace("-", "").replace("_", "")
    for name in _ENGINE_STYLE:
        if stem == name.replace("-", ""):
            return name
    # tectonic.exe / tectonic-0.17 之类
    if "tectonic" in stem:
        return "tectonic"
    if "latexmk" in stem:
        return "latexmk"
    if "xelatex" in stem:
        return "xelatex"
    if "lualatex" in stem:
        return "lualatex"
    if "pdflatex" in stem:
        return "pdflatex"
    raise LatexEngineError(f"无法识别的 LaTeX 引擎：{path_or_name}")


def _expand(p: str) -> str:
    return os.path.expanduser(os.path.expandvars(p))


def find_engine(explicit: str | None = None) -> tuple[str, str] | None:
    """探测可用的 LaTeX 引擎。

    返回 ``(engine_name, executable_path)``；找不到返回 ``None``。
    ``explicit`` 可传引擎名（``tectonic``）或可执行文件绝对路径。
    """
    # 1) 显式指定
    candidate = explicit or os.environ.get("GEWU_LATEX_ENGINE")
    if candidate:
        cand = _expand(candidate)
        if os.path.sep in cand or (os.path.altsep and os.path.altsep in cand) or Path(cand).is_file():
            if Path(cand).is_file():
                return _norm_engine(cand), cand
            raise LatexEngineError(f"GEWU_LATEX_ENGINE 指向的文件不存在：{cand}")
        found = shutil.which(cand)
        if found:
            return _norm_engine(found), found
        raise LatexEngineError(f"GEWU_LATEX_ENGINE 指定的引擎不在 PATH 中：{cand}")

    # 2) PATH（优先 tectonic：无系统依赖、按需拉包）
    for name in ("tectonic", "xelatex", "lualatex", "latexmk", "pdflatex"):
        found = shutil.which(name)
        if found:
            return _norm_engine(found), found

    # 3) 常见安装位置
    for raw in _COMMON_ENGINE_PATHS.get(sys.platform, _COMMON_ENGINE_PATHS["linux"]):
        p = Path(_expand(raw))
        if p.is_file():
            return _norm_engine(str(p)), str(p)
    return None


def _parse_log(log_text: str) -> dict:
    """从 TeX 日志里抽出可判定的问题，而不是整段回显。"""
    errors: list[str] = []
    missing_glyphs: list[str] = []
    undefined_citations: list[str] = []
    undefined_refs: list[str] = []
    overfull = 0

    for line in log_text.splitlines():
        s = line.strip()
        if s.startswith("!"):
            # tectonic 会把 "! LaTeX Error: ..." 直接打到 stderr 风格行
            errors.append(s)
        elif s.startswith("Missing character:"):
            missing_glyphs.append(s)
        elif "Citation" in s and "undefined" in s:
            m = re.search(r"Citation `([^']+)'", s)
            undefined_citations.append(m.group(1) if m else s)
        elif "Reference" in s and "undefined" in s:
            m = re.search(r"Reference `([^']+)'", s)
            undefined_refs.append(m.group(1) if m else s)
        elif s.startswith("Overfull \\hbox"):
            overfull += 1

    return {
        "errors": errors,
        "missing_glyphs": missing_glyphs,
        "undefined_citations": sorted(set(undefined_citations)),
        "undefined_references": sorted(set(undefined_refs)),
        "overfull_hbox": overfull,
    }


def _read_log_from_dir(out_dir: Path, stem: str) -> str:
    log = out_dir / f"{stem}.log"
    if log.is_file():
        try:
            return log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    return ""


def build(
    tex_path: str | os.PathLike,
    out_dir: str | os.PathLike | None = None,
    *,
    engine: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    keep_intermediates: bool = False,
    source_date_epoch: int | str | None = None,
) -> dict:
    """编译单个 .tex 文件为 PDF。

    返回结构化结果，关键字段：
    - ``status``: ``ok`` / ``compile_error`` / ``no_engine`` / ``timeout`` / ``not_found``
    - ``pdf``: 成功时的 PDF 绝对路径
    - ``log``: 解析后的问题清单（errors / missing_glyphs / undefined_citations ...）
    - ``pdf_text_ok``: 仅在成功时有意义，交由上层做内容核验

    ``source_date_epoch``：传给引擎的 ``SOURCE_DATE_EPOCH``。默认 ``None`` 表示沿用
    调用方环境；给整数则**钉住** PDF 内嵌时间戳。实测（tectonic 0.17.0）钉住同一
    epoch 连续三次编译，输出**字节级完全相同**；不钉则每次都不同。需要「产物可被
    第三方按哈希复核」时用它，需要「排版可复现即可」时用内容指纹即可。

    失败时 ``ok=False`` 且 ``reason`` 说明原因，绝不伪造成功。
    """
    tex = Path(tex_path).expanduser().resolve()
    if not tex.is_file():
        return {"ok": False, "status": "not_found", "reason": f"tex 文件不存在：{tex}"}

    found = find_engine(engine)
    if found is None:
        return {
            "ok": False,
            "status": "no_engine",
            "reason": (
                "本机未找到可用 LaTeX 引擎（tectonic / xelatex / latexmk 均不可用）。"
                "可安装单文件引擎 tectonic 后重试，或用 GEWU_LATEX_ENGINE 指定可执行文件路径。"
            ),
            "install_hint": {
                "tectonic": "https://github.com/tectonic-typesetting/tectonic/releases",
                "windows_quick": (
                    "下载 tectonic-*-x86_64-pc-windows-msvc.zip，解压到 "
                    r"%LOCALAPPDATA%\gewu\tools\tectonic.exe"
                ),
            },
        }

    engine_name, exe = found
    out = Path(out_dir).expanduser().resolve() if out_dir else tex.parent
    out.mkdir(parents=True, exist_ok=True)

    if engine_name == "tectonic":
        cmd = [exe, "-X", "compile", str(tex.name), "--outdir", str(out), "--keep-logs"]
        if keep_intermediates:
            cmd.append("--keep-intermediates")
        cwd = str(tex.parent)
    elif engine_name == "latexmk":
        cmd = [exe, "-xelatex", "-interaction=nonstopmode", "-halt-on-error", f"-outdir={out}", tex.name]
        cwd = str(tex.parent)
    else:  # xelatex / lualatex / pdflatex：需要跑两遍以稳定交叉引用
        cmd = [
            exe,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            f"-output-directory={out}",
            tex.name,
        ]
        cwd = str(tex.parent)

    started = time.time()
    passes = 1 if engine_name in ("tectonic", "latexmk") else 2
    stdout_parts: list[str] = []
    rc = 0
    compile_env = os.environ.copy()
    if source_date_epoch is not None:
        compile_env["SOURCE_DATE_EPOCH"] = str(source_date_epoch)
    try:
        for i in range(passes):
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=compile_env,
            )
            stdout_parts.append(proc.stdout or "")
            rc = proc.returncode
            if rc != 0:
                # 第二遍失败同样致命，直接退出循环
                break
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "status": "timeout",
            "reason": f"编译超时（>{timeout}s）；tectonic 首次运行需下载 TeX bundle，可先预热缓存",
            "engine": engine_name,
            "executable": exe,
        }

    duration = round(time.time() - started, 2)
    stdout = "\n".join(stdout_parts)
    log_text = _read_log_from_dir(out, tex.stem)
    if not log_text:
        # tectonic 把 note: 打到 stderr，日志可能因 --keep-logs 才落盘；退化为扫 stdout
        log_text = stdout

    parsed = _parse_log(log_text)
    pdf_path = out / f"{tex.stem}.pdf"
    pdf_ok = pdf_path.is_file() and pdf_path.stat().st_size > 0

    # 判定：退出码 0 + PDF 存在 + 无 TeX error + 无缺字
    hard_fail = rc != 0 or not pdf_ok or bool(parsed["errors"]) or bool(parsed["missing_glyphs"])
    result: dict = {
        "ok": not hard_fail,
        "status": "ok" if not hard_fail else "compile_error",
        "engine": engine_name,
        "executable": exe,
        "duration_s": duration,
        "log": parsed,
        "command": " ".join(cmd),
        "out_dir": str(out),
        "source_date_epoch": str(source_date_epoch) if source_date_epoch is not None
        else compile_env.get("SOURCE_DATE_EPOCH"),
    }
    if pdf_ok:
        result["pdf"] = str(pdf_path)
        result["pdf_bytes"] = pdf_path.stat().st_size
    if hard_fail:
        reasons = []
        if rc != 0:
            reasons.append(f"引擎退出码 {rc}")
        if not pdf_ok:
            reasons.append("未生成 PDF")
        if parsed["errors"]:
            reasons.append(f"{len(parsed['errors'])} 条 TeX error")
        if parsed["missing_glyphs"]:
            reasons.append(f"{len(parsed['missing_glyphs'])} 处字形缺失（多为中文字体未设置）")
        result["reason"] = "；".join(reasons)
        result["stdout_tail"] = stdout[-3000:]
    return result


def pdf_page_count(pdf_path: str | os.PathLike) -> int | None:
    """页数；无 pymupdf 时返回 None（不强行依赖）。"""
    try:
        import pymupdf  # noqa: PLC0415
    except ImportError:
        return None
    try:
        with pymupdf.open(str(pdf_path)) as doc:
            return len(doc)
    except Exception:
        return None


def pdf_text(pdf_path: str | os.PathLike) -> str:
    """抽取 PDF 全文；无 pymupdf 时返回空串。"""
    try:
        import pymupdf  # noqa: PLC0415
    except ImportError:
        return ""
    try:
        with pymupdf.open(str(pdf_path)) as doc:
            return "\n".join(page.get_text() for page in doc)
    except Exception:
        return ""


def pdf_text_fingerprint(pdf_path: str | os.PathLike, *, normalize_dates: bool = True) -> str:
    """PDF 的**内容指纹**（规范化文本的 sha256 前 16 位）。

    不能用文件二进制哈希做快照比对：PDF 内嵌 ``/CreationDate``，每次编译字节都不同
    （实测同一 tex 连编两次，二进制哈希不同而正文完全一致）。故以提取文本、
    压缩空白后取哈希，作为"这份 PDF 写了什么"的稳定指纹。

    ``normalize_dates`` 默认开启：论文封面与页脚带生成日期，跨天重跑会让指纹变化，
    而"日期变了"并不等于"结论变了"，故把 ``YYYY-MM-DD`` 统一替换为 ``<DATE>``。
    无 pymupdf 或抽不到文本时返回空串。
    """
    import hashlib
    import re

    text = pdf_text(pdf_path)
    if not text.strip():
        return ""
    normalized = re.sub(r"\s+", " ", text).strip()
    if normalize_dates:
        normalized = re.sub(r"\d{4}-\d{2}-\d{2}", "<DATE>", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def main(argv: list[str] | None = None) -> int:
    """命令行入口：``python -m gewu.latex_build <file.tex>``。"""
    import argparse
    import json

    ap = argparse.ArgumentParser(description="把 .tex 编译为 PDF（自动探测本机引擎）")
    ap.add_argument("tex", help=".tex 文件路径")
    ap.add_argument("--out", default=None, help="输出目录（默认与 tex 同目录）")
    ap.add_argument("--engine", default=None, help="指定引擎名或可执行文件路径")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="超时秒数")
    ap.add_argument("--source-date-epoch", type=int, default=None,
                    help="钉住 PDF 内嵌时间戳；同一值重复编译可得到字节级相同产物")
    ap.add_argument("--json", action="store_true", help="输出完整 JSON 结果")
    args = ap.parse_args(argv)

    r = build(args.tex, out_dir=args.out, engine=args.engine, timeout=args.timeout,
              source_date_epoch=args.source_date_epoch)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif r.get("ok"):
        print(f"OK  {r['pdf']}  ({r['pdf_bytes']} 字节, {r['duration_s']}s, {r['engine']})")
        log = r["log"]
        print(
            f"    error={len(log['errors'])} 缺字={len(log['missing_glyphs'])} "
            f"overfull={log['overfull_hbox']}"
        )
    else:
        print(f"FAIL status={r.get('status')}: {r.get('reason')}")
        for e in (r.get("log", {}).get("errors") or [])[:5]:
            print(f"    {e}")
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
