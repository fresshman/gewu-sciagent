"""图表出处旁文件（provenance sidecar）。

问题：sci_plot 以前只落 `<stem>_<时间戳>.pdf` + `.png` 两个文件，文件名里的
stem 和时间戳就是全部的「出处」。事后没人能回答：这张图是哪个工具画的、
喂的是什么数据、标题写的是哪一版、和稿子里那张图是不是同一张。

做法：每画一张图，在旁边写一份 `<base>.meta.json`，记录三件事——

1. **谁画的**：工具函数名（`plot_bar`）、gewu 版本、git 短 sha、调用时间；
2. **拿什么画的**：调用参数摘要——数值序列只存 sha256/形状/极值，不存原值
   （单张光谱几万点，原样抄进 json 会把目录撑爆，且可能含未发表数据）；
3. **画出了什么**：从渲染完的 Figure 上反读 Axes 里的 line/collection/patch/image
   取值，逐 series 给指纹。这一条是**事后可校验**的：拿同样的数据重画一遍，
   指纹应当一致；指纹不一致就说明图和数据对不上了。

两条设计约束：
- **不伪造**：读不出来的字段一律留空并记 `errors`，不猜。
- **不影响出图**：旁文件写失败只让返回值里 `provenance: false`，图照常出。
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

SCHEMA = 1
TZ = timezone(timedelta(hours=8))  # 与项目其它产物一致，写 +08:00
_MAX_STR = 200  # 标题/标签这类字符串截断长度
_MAX_ITEMS = 40  # 单个 series 列表最多记多少条


# ── 基础工具 ──────────────────────────────────────────────


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fig_id(pdf_sha: str) -> str:
    """图纸 id：内容寻址。同一张图（字节完全相同）在不同目录里都是同一个 id。"""
    return f"fig-{str(pdf_sha)[:8]}"


def _num(v: Any) -> Any:
    """把 numpy 标量 / nan / inf 转成 json 能写的值。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return "nan"
    if f in (float("inf"), float("-inf")):
        return "inf" if f > 0 else "-inf"
    return round(f, 6)


def _array_brief(a: np.ndarray) -> Dict[str, Any]:
    """数值数组摘要：形状 + 指纹 + 极值。原值不外泄。"""
    arr = np.asarray(a, dtype=float)
    flat = np.ascontiguousarray(arr.ravel(), dtype=np.float64)
    out: Dict[str, Any] = {
        "kind": "array",
        "shape": [int(x) for x in arr.shape],
        "n": int(flat.size),
        "sha256": sha256_bytes(flat.tobytes())[:16],
    }
    finite = flat[np.isfinite(flat)]
    if float(finite.size) > 0:
        out["min"] = _num(finite.min())
        out["max"] = _num(finite.max())
    return out


def brief(v: Any) -> Dict[str, Any]:
    """把任意入参压成「够认出来、又不泄露原值」的小字典。"""
    if v is None:
        return {"kind": "null"}
    if isinstance(v, (bool, np.bool_)):
        return {"kind": "bool", "value": bool(v)}
    if isinstance(v, (int, float, np.integer, np.floating)):
        return {"kind": "number", "value": _num(v)}
    if isinstance(v, str):
        return {
            "kind": "str",
            "value": v[:_MAX_STR],
            "chars": len(v),
            **({"truncated": True} if len(v) > _MAX_STR else {}),
        }
    if isinstance(v, np.ndarray):
        return _array_brief(v)
    if isinstance(v, (list, tuple)):
        try:
            arr = np.asarray(v, dtype=float)
        except (TypeError, ValueError):
            head = [str(x)[:_MAX_STR] for x in list(v)[:8]]
            return {"kind": "list", "n": len(v), "values": head}
        b = _array_brief(arr)
        b["kind"] = "seq"
        return b
    if isinstance(v, dict):
        return {"kind": "dict", "keys": [str(k) for k in list(v)[:_MAX_ITEMS]]}
    return {"kind": type(v).__name__}


# ── 从渲染结果反读「画了什么」 ────────────────────────────


def _series_of(fig) -> List[Dict[str, Any]]:
    """遍历每个 Axes，把实际被绘制的数值读出来。只认能读的，读不到就记类型。"""
    series: List[Dict[str, Any]] = []
    for ai, ax in enumerate(fig.axes):
        for ln in ax.lines:
            try:
                xy = np.asarray(ln.get_xydata(), dtype=float)
            except (TypeError, ValueError):
                continue
            if xy.size:
                series.append({**_array_brief(xy), "axis": ai, "kind": "line"})

        for col in ax.collections:
            name = type(col).__name__
            try:
                off = np.asarray(col.get_offsets(), dtype=float)
            except (TypeError, ValueError):
                off = np.empty((0, 2))
            if off.size:
                series.append({**_array_brief(off), "axis": ai, "kind": name})
            else:
                # violin / box 填充这类是 PolyCollection，没有 offsets，只有路径
                try:
                    paths = col.get_paths()
                except Exception:  # noqa: BLE001 - 第三方集合行为不可控
                    paths = []
                verts = []
                for p in paths:
                    try:
                        verts.append(np.asarray(p.vertices, dtype=float))
                    except (TypeError, ValueError):
                        continue
                if verts:
                    allv = np.concatenate(verts, axis=0)
                    series.append(
                        {**_array_brief(allv), "axis": ai, "kind": name, "paths": len(verts)}
                    )

        rects = []
        for pt in ax.patches:
            try:
                x, y = pt.get_xy()
                rects.append([float(x), float(y), float(pt.get_width()), float(pt.get_height())])
            except (AttributeError, TypeError, ValueError):
                continue
        if rects:
            series.append({**_array_brief(np.asarray(rects)), "axis": ai, "kind": "patch"})

        for im in ax.images:
            try:
                arr = np.asarray(im.get_array(), dtype=float)
            except (TypeError, ValueError):
                continue
            if arr.size:
                series.append({**_array_brief(arr), "axis": ai, "kind": "image"})
    return series[:_MAX_ITEMS]


def _axis_labels(fig) -> Dict[str, Any]:
    """标题与轴标签——用来核对「这张图的标题是不是稿子里描述的那一版」。"""
    out: Dict[str, Any] = {"titles": [], "x": [], "y": []}
    for ax in fig.axes:
        out["titles"].append(str(ax.get_title())[:_MAX_STR])
        out["x"].append(str(ax.get_xlabel())[:_MAX_STR])
        out["y"].append(str(ax.get_ylabel())[:_MAX_STR])
    return out


def figure_fingerprint(fig) -> Dict[str, Any]:
    """渲染后指纹：series 摘要 + 轴标签。用于「同数据重画应一致」的校验。"""
    series = _series_of(fig)
    basis = json.dumps(
        [{k: s.get(k) for k in ("axis", "kind", "n", "sha256")} for s in series],
        sort_keys=True,
        ensure_ascii=False,
    )
    return {
        "axes": len(fig.axes),
        "series": series,
        "labels": _axis_labels(fig),
        "digest": sha256_bytes(basis.encode("utf-8"))[:16],
    }


# ── 调用现场 ──────────────────────────────────────────────


def caller_args(frame) -> Dict[str, Any]:
    """从调用者栈帧里取**函数签名参数**（不含局部中间变量）。

    这样不用改 17 个工具函数的调用点，也能拿到「传进来的是什么」。
    非参数局部变量一律不读，避免把数据副本和路径抄进去。
    """
    try:
        info = inspect.getargvalues(frame)
    except Exception:  # noqa: BLE001
        return {}
    out: Dict[str, Any] = {}
    for name in list(info.args) + list(info.keywords or {}):
        if name in ("self", "cls"):
            continue
        if name not in frame.f_locals:
            continue
        out[name] = brief(frame.f_locals[name])
    return out


_GIT: Optional[str] = None


def git_sha() -> Optional[str]:
    """仓库短 sha。拿不到就返回 None（不编造）。"""
    global _GIT
    if _GIT is not None:
        return _GIT or None
    import subprocess

    root = Path(__file__).resolve().parents[2]
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=3,
        )
        _GIT = r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        _GIT = ""
    return _GIT or None


def _version() -> Optional[str]:
    """包版本。脚本方式启动时 `import gewu` 可能失败（openclaw 直接跑 sci_plot.py），
    此时直接读 gewu/__init__.py 里的 __version__，不写死也不留 null。"""
    try:
        import gewu

        v = getattr(gewu, "__version__", None)
        if v:
            return v
    except Exception:  # noqa: BLE001 - 包不在 path 上是正常情况
        pass
    try:
        init = Path(__file__).resolve().parents[1] / "__init__.py"
        for line in init.read_text(encoding="utf-8").splitlines():
            if line.startswith("__version__"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


# ── 组装与落盘 ────────────────────────────────────────────


def build_meta(
    *,
    stem: str,
    tool: str,
    fig,
    files: Dict[str, Dict[str, Any]],
    args: Optional[Dict[str, Any]] = None,
    dpi: int = 300,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """组装旁文件内容。纯函数（除了会读 fig 的渲染状态），便于单测。"""
    errors: List[str] = []
    try:
        draw = figure_fingerprint(fig)
    except Exception as exc:  # noqa: BLE001 - 指纹不能拖垮出图
        errors.append(f"fingerprint: {type(exc).__name__}: {exc}")
        draw = {"axes": None, "series": [], "labels": {}, "digest": None}

    pdf = files.get("pdf") or {}
    meta: Dict[str, Any] = {
        "schema": SCHEMA,
        "created_at": created_at or datetime.now(TZ).isoformat(timespec="seconds"),
        "stem": stem,
        "tool": tool,
        "fig_id": fig_id(pdf.get("sha256", "")),
        "args": args or {},
        "draw": draw,
        "files": files,
        "dpi": dpi,
        "gewu": {"version": _version(), "git": git_sha()},
    }
    if errors:
        meta["errors"] = errors
    return meta


def write_sidecar(
    base: Path,
    *,
    stem: str,
    tool: str,
    fig,
    paths: Dict[str, Path],
    args: Optional[Dict[str, Any]] = None,
    dpi: int = 300,
) -> Optional[Path]:
    """写 `<base>.meta.json`。失败返回 None，绝不抛（出图优先）。"""
    try:
        files = {}
        for fmt, p in paths.items():
            p = Path(p)
            if p.exists():
                files[fmt] = {
                    "name": p.name,
                    "bytes": p.stat().st_size,
                    "sha256": sha256_file(p),
                }
        meta = build_meta(stem=stem, tool=tool, fig=fig, files=files, args=args, dpi=dpi)
        out = Path(base).with_suffix(".meta.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".meta.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, out)  # 原子替换：避免读到写一半的 json
        return out
    except Exception:  # noqa: BLE001
        return None


def read_sidecar(path) -> Optional[Dict[str, Any]]:
    """读旁文件；坏 json 当没有，不猜。"""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


if __name__ == "__main__":  # 手工排查用：把旁文件打出来
    for p in sys.argv[1:]:
        print(json.dumps(read_sidecar(p), ensure_ascii=False, indent=2))
