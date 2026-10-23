"""科学绘图 MCP Server —— 本地 matplotlib 渲染，数据不出本机。

为什么自建而不是用云端出图 MCP：
  云端方案（如 mcp-server-chart）需要把数据 POST 到公有云服务器渲染，
  返回的是一个远程图片 URL，再由客户端自行下载。对格物这种「本地优先、
  可能含未发表实验数据」的科研智能体而言，**数据出域是硬伤**，且产物是
  栅格图而非出版级矢量图。本 server 全程本地渲染，并同时输出：
    - PDF（矢量，投稿 / 出版用，期刊更认）
    - PNG（300 dpi 预览，便于嵌入 docx 与快速查看）

工具（17 个，按论文插图场景收口；其中含数据的图类型与 chart-cloud 云端禁用项一一对应）：
  plot_spectrum   光谱 / 时序曲线（LIBS 等一维信号）
  plot_line       折线图（趋势 / 时序 / 随参数变化）
  plot_area       面积图（累积 / 占比趋势）
  plot_scatter    散点图（可带线性拟合线与 R²）
  plot_pred_true  预测值 vs 真实值（回归论文核心图，自动标注 R²/RMSE/MAE）
  plot_residuals  残差图（检验异方差 / 系统偏差）
  plot_bar        柱状对比（可带误差棒 / 支持横向，适合消融实验）
  plot_boxplot    多组箱线图（适合交叉验证折间对比）
  plot_violin     多组小提琴图（分布形态对比）
  plot_histogram  直方图（单变量分布）
  plot_heatmap    热力图（相关系数矩阵 / 混淆矩阵，自动标注数值）
  plot_curves     多曲线（训练 / 验证损失、学习曲线）
  plot_pie        饼图（构成 / 占比）
  plot_radar      雷达图（多维指标对比）
  plot_dual_axes  双 Y 轴图（两个量纲不同的序列同图）
  plot_waterfall  瀑布图（从基准逐步增减到终值，如误差分解）
  list_figures    列出已生成的图片文件

字体：自动启用中文字体（Windows 走 Microsoft YaHei / SimHei），
并关闭 unicode 减号，避免中文标题/标签渲染成方块。
输出目录：环境变量 GEWU_FIG_DIR，默认 output/figures（相对项目根）。

混合绘图策略（与 chart-cloud 分工）：
  本 server 负责**所有含实验数据的统计图**——它们必须本地渲染、数据不出本机。
  思维导图 / 桑基 / 鱼骨 / 组织架构 / 地图等**纯结构/概念图（不含实验数据）**
  走 chart-cloud（包装 @antv/mcp-server-chart，云端出图）。为强制隔离，chart-cloud
  已通过 DISABLED_TOOLS 关掉下面这些含数据的图类型，使其只能在本地由本 server 出。
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import matplotlib

matplotlib.use("Agg")  # 无 GUI 后端，必须在导入 pyplot 之前设置

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("sci-plot")

FIG_DIR = Path(os.environ.get("GEWU_FIG_DIR", "output/figures"))

plt.rcParams.update(
    {
        "font.sans-serif": [
            "Microsoft YaHei",
            "SimHei",
            "Noto Sans CJK SC",
            "DejaVu Sans",
        ],
        "axes.unicode_minus": False,  # 负号用 ASCII 连字符，避免变成方块
        "font.size": 11,
        "axes.titlesize": 12,
        "figure.dpi": 120,
        "savefig.dpi": 300,
    }
)


# ── 内部工具 ───────────────────────────────────────────────


def _arr(values: Sequence, name: str = "数据") -> np.ndarray:
    """把输入序列转成 float ndarray，并给出可读的错误信息。"""
    try:
        a = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数字序列：{exc}") from None
    if a.size == 0:
        raise ValueError(f"{name} 不能为空。")
    return a


def _save(fig, stem: str) -> dict:
    """保存为 PDF(矢量) + PNG(300dpi)，返回绝对路径。"""
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = FIG_DIR / f"{stem}_{ts}"
    pdf, png = base.with_suffix(".pdf"), base.with_suffix(".png")
    fig.savefig(pdf, format="pdf", bbox_inches="tight")
    fig.savefig(png, format="png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    return {"ok": True, "stem": stem, "pdf": str(pdf.resolve()), "png": str(png.resolve())}


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """回归任务常用指标：R² / RMSE / MAE / 样本数。"""
    err = y_pred - y_true
    ss_res = float(np.sum(err**2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {
        "r2": round(float(r2), 4),
        "rmse": round(float(np.sqrt(np.mean(err**2))), 4),
        "mae": round(float(np.mean(np.abs(err))), 4),
        "n": int(y_true.size),
    }


def _groups(groups: Sequence[Sequence], name: str = "分组数据") -> List[np.ndarray]:
    if not groups:
        raise ValueError(f"{name} 不能为空。")
    return [_arr(g, f"{name}[{i}]") for i, g in enumerate(groups)]


def _labels_for(n: int, labels: Optional[Sequence[str]]) -> List[str]:
    if labels is None:
        return [str(i + 1) for i in range(n)]
    labels = list(labels)
    if len(labels) != n:
        raise ValueError(f"labels 长度({len(labels)}) 与数据组数({n}) 不一致。")
    return [str(x) for x in labels]


# ── 绘图工具 ───────────────────────────────────────────────


@mcp.tool()
def plot_spectrum(
    wavelengths: Sequence[float],
    intensities: Sequence[float],
    title: str = "光谱图",
    xlabel: str = "波长 (nm)",
    ylabel: str = "强度 (a.u.)",
    stem: str = "spectrum",
) -> dict:
    """绘制光谱 / 一维信号曲线（LIBS、NIR、时序信号等）。

    Args:
        wavelengths: 波长（或时间、索引）序列。
        intensities: 对应的强度 / 幅值序列，长度需与 wavelengths 一致。
        title: 图标题。
        xlabel / ylabel: 坐标轴名称。
        stem: 输出文件名前缀。
    """
    x = _arr(wavelengths, "wavelengths")
    y = _arr(intensities, "intensities")
    if x.size != y.size:
        raise ValueError(f"wavelengths({x.size}) 与 intensities({y.size}) 长度不一致。")

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(x, y, linewidth=0.8, color="#1f77b4")
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)
    return _save(fig, stem)


@mcp.tool()
def plot_scatter(
    x: Sequence[float],
    y: Sequence[float],
    title: str = "散点图",
    xlabel: str = "X",
    ylabel: str = "Y",
    fit: bool = True,
    stem: str = "scatter",
) -> dict:
    """绘制散点图，可叠加线性拟合线并标注 R²（看相关性用）。

    Args:
        x / y: 两组等长数值序列。
        fit: 是否叠加最小二乘拟合线与 R² 标注。
        stem: 输出文件名前缀。
    """
    xa = _arr(x, "x")
    ya = _arr(y, "y")
    if xa.size != ya.size:
        raise ValueError(f"x({xa.size}) 与 y({ya.size}) 长度不一致。")

    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    ax.scatter(xa, ya, s=28, alpha=0.75, edgecolors="none", color="#1f77b4")

    out: dict = {}
    if fit and xa.size >= 2:
        slope, intercept = np.polyfit(xa, ya, 1)
        xs = np.linspace(xa.min(), xa.max(), 100)
        ax.plot(xs, slope * xs + intercept, "r--", linewidth=1.5, label="线性拟合")
        corr = float(np.corrcoef(xa, ya)[0, 1])
        r2 = round(corr**2, 4)
        ax.legend()
        ax.text(
            0.05,
            0.92,
            f"$R^2$ = {r2}",
            transform=ax.transAxes,
            fontsize=11,
            color="red",
        )
        out.update({"r2_of_fit": r2, "slope": round(float(slope), 6),
                    "intercept": round(float(intercept), 6)})

    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)
    out.update(_save(fig, stem))
    return out


@mcp.tool()
def plot_pred_true(
    y_true: Sequence[float],
    y_pred: Sequence[float],
    title: str = "预测值 vs 真实值",
    xlabel: str = "真实值",
    ylabel: str = "预测值",
    stem: str = "pred_true",
) -> dict:
    """回归论文核心图：预测值 vs 真实值，含 1:1 参考线与 R²/RMSE/MAE 标注。

    Args:
        y_true: 真实值序列。
        y_pred: 模型预测值序列，长度需与 y_true 一致。
        stem: 输出文件名前缀。

    Returns:
        图片路径 + 指标字典（r2 / rmse / mae / n）。
    """
    t = _arr(y_true, "y_true")
    p = _arr(y_pred, "y_pred")
    if t.size != p.size:
        raise ValueError(f"y_true({t.size}) 与 y_pred({p.size}) 长度不一致。")

    m = _metrics(t, p)
    lo = float(min(t.min(), p.min()))
    hi = float(max(t.max(), p.max()))
    pad = (hi - lo) * 0.05 or 1.0

    fig, ax = plt.subplots(figsize=(6.5, 6))
    ax.scatter(t, p, s=32, alpha=0.75, edgecolors="none", color="#1f77b4", label="样本")
    ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], "k--", linewidth=1.2, label="1:1")
    ax.set_xlim(lo - pad, hi + pad)
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_aspect("equal", adjustable="box")
    ax.legend()
    ax.text(
        0.05,
        0.90,
        f"$R^2$ = {m['r2']}\nRMSE = {m['rmse']}\nMAE = {m['mae']}\nn = {m['n']}",
        transform=ax.transAxes,
        fontsize=10,
        va="top",
        bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.8},
    )
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)
    return {**_save(fig, stem), "metrics": m}


@mcp.tool()
def plot_residuals(
    y_true: Sequence[float],
    y_pred: Sequence[float],
    title: str = "残差图",
    xlabel: str = "预测值",
    ylabel: str = "残差 (预测值 - 真实值)",
    stem: str = "residuals",
) -> dict:
    """绘制残差图：横轴预测值、纵轴残差，用于检验异方差与系统偏差。"""
    t = _arr(y_true, "y_true")
    p = _arr(y_pred, "y_pred")
    if t.size != p.size:
        raise ValueError(f"y_true({t.size}) 与 y_pred({p.size}) 长度不一致。")

    resid = p - t
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.scatter(p, resid, s=28, alpha=0.75, edgecolors="none", color="#d62728")
    ax.axhline(0, color="black", linestyle="--", linewidth=1.2)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)
    out = _save(fig, stem)
    out["resid_mean"] = round(float(resid.mean()), 4)
    out["resid_std"] = round(float(resid.std(ddof=1)) if resid.size > 1 else 0.0, 4)
    return out


@mcp.tool()
def plot_bar(
    labels: Sequence[str],
    values: Sequence[float],
    yerr: Optional[Sequence[float]] = None,
    title: str = "对比",
    ylabel: str = "数值",
    orientation: str = "vertical",
    stem: str = "bar",
) -> dict:
    """柱状对比图，可带误差棒（消融实验 / 多模型对比用）。

    Args:
        labels: 每个柱的类别名。
        values: 对应数值。
        yerr: 可选的误差棒（标准差 / 置信区间），长度与 values 一致。
        orientation: "vertical"（默认，柱形）或 "horizontal"（条形）。
    """
    vals = _arr(values, "values")
    names = _labels_for(vals.size, labels)
    err = None
    if yerr is not None:
        err = _arr(yerr, "yerr")
        if err.size != vals.size:
            raise ValueError(f"yerr({err.size}) 与 values({vals.size}) 长度不一致。")

    fig, ax = plt.subplots(figsize=(7, 4.5))
    horiz = orientation == "horizontal"
    if horiz:
        ax.barh(names, vals, xerr=err, capsize=4, color="#4c72b0", edgecolor="black", linewidth=0.5)
        ax.set_xlabel(ylabel)
        ax.grid(axis="x", alpha=0.3)
    else:
        ax.bar(names, vals, yerr=err, capsize=4, color="#4c72b0", edgecolor="black", linewidth=0.5)
        ax.set_ylabel(ylabel)
        ax.grid(axis="y", alpha=0.3)
        fig.autofmt_xdate(rotation=0)
    ax.set_title(title)
    return _save(fig, stem)


@mcp.tool()
def plot_boxplot(
    groups: Sequence[Sequence[float]],
    labels: Optional[Sequence[str]] = None,
    title: str = "分布对比",
    ylabel: str = "数值",
    stem: str = "boxplot",
) -> dict:
    """多组箱线图（交叉验证各折指标对比、多方法分布对比用）。

    Args:
        groups: 若干组数值，每组一个序列，如 [[0.8,0.9],[0.7,0.75]]。
        labels: 每组名称，缺省用 1,2,3...
    """
    data = _groups(groups)
    names = _labels_for(len(data), labels)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.boxplot(data, tick_labels=names, showmeans=True)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.3)
    return _save(fig, stem)


@mcp.tool()
def plot_violin(
    groups: Sequence[Sequence[float]],
    labels: Optional[Sequence[str]] = None,
    title: str = "分布对比",
    ylabel: str = "数值",
    stem: str = "violin",
) -> dict:
    """多组小提琴图（比箱线图多呈现分布密度形态）。"""
    data = _groups(groups)
    names = _labels_for(len(data), labels)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.violinplot(data, showmeans=True, showmedians=True)
    ax.set_xticks(range(1, len(data) + 1))
    ax.set_xticklabels(names)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.3)
    return _save(fig, stem)


@mcp.tool()
def plot_histogram(
    values: Sequence[float],
    bins: int = 30,
    title: str = "分布直方图",
    xlabel: str = "数值",
    ylabel: str = "频数",
    stem: str = "histogram",
) -> dict:
    """单变量分布直方图。"""
    v = _arr(values, "values")
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.hist(v, bins=int(bins), color="#4c72b0", edgecolor="black", linewidth=0.5)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.3)
    out = _save(fig, stem)
    out.update({"mean": round(float(v.mean()), 4), "std": round(float(v.std(ddof=1)) if v.size > 1 else 0.0, 4)})
    return out


@mcp.tool()
def plot_heatmap(
    matrix: Sequence[Sequence[float]],
    xticklabels: Optional[Sequence[str]] = None,
    yticklabels: Optional[Sequence[str]] = None,
    title: str = "热力图",
    cmap: str = "viridis",
    annotate: bool = True,
    stem: str = "heatmap",
) -> dict:
    """热力图（相关系数矩阵 / 混淆矩阵），小矩阵自动标注数值。

    Args:
        matrix: 二维数值矩阵（等长行）。
        xticklabels / yticklabels: 轴标签。
        cmap: 配色，如 viridis / coolwarm / Blues。
        annotate: 是否在格子内标注数值（默认 True，超过 20x20 自动关闭）。
    """
    try:
        m = np.asarray(matrix, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"matrix 必须是二维数字矩阵：{exc}") from None
    if m.ndim != 2:
        raise ValueError(f"matrix 必须是二维的，当前为 {m.ndim} 维。")

    nrow, ncol = m.shape
    xt = _labels_for(ncol, xticklabels) if xticklabels is not None else [str(i + 1) for i in range(ncol)]
    yt = _labels_for(nrow, yticklabels) if yticklabels is not None else [str(i + 1) for i in range(nrow)]

    fig, ax = plt.subplots(figsize=(max(6, ncol * 0.6), max(5, nrow * 0.5)))
    im = ax.imshow(m, cmap=cmap, aspect="auto")
    fig.colorbar(im, ax=ax)
    ax.set_xticks(range(ncol))
    ax.set_xticklabels(xt, rotation=45, ha="right")
    ax.set_yticks(range(nrow))
    ax.set_yticklabels(yt)
    ax.set_title(title)

    if annotate and nrow <= 20 and ncol <= 20:
        for i in range(nrow):
            for j in range(ncol):
                ax.text(j, i, f"{m[i, j]:.2f}", ha="center", va="center",
                        color="white" if abs(m[i, j]) > (m.max() + m.min()) / 2 else "black",
                        fontsize=9)
    return _save(fig, stem)


@mcp.tool()
def plot_curves(
    series: Dict[str, Sequence[float]],
    x: Optional[Sequence[float]] = None,
    title: str = "曲线对比",
    xlabel: str = "X",
    ylabel: str = "Y",
    stem: str = "curves",
) -> dict:
    """多条曲线同图对比（训练/验证损失、学习曲线、多方法性能随参数变化）。

    Args:
        series: 字典，键为曲线名，值为该曲线的数值序列，如 {"train":[...], "val":[...]}。
        x: 可选横轴（如 epoch 序号）；缺省用 0,1,2...
    """
    if not series:
        raise ValueError("series 不能为空。")
    curves = {str(k): _arr(v, f"series['{k}']") for k, v in series.items()}
    if x is None:
        xa = np.arange(len(next(iter(curves.values()))))
    else:
        xa = _arr(x, "x")

    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    for name, ya in curves.items():
        if ya.size != xa.size:
            raise ValueError(f"曲线 '{name}' 长度({ya.size}) 与横轴({xa.size}) 不一致。")
        ax.plot(xa, ya, linewidth=1.6, label=name)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.legend()
    ax.grid(alpha=0.3)
    return _save(fig, stem)


@mcp.tool()
def plot_line(
    x: Sequence[float],
    y: Sequence[float],
    title: str = "折线图",
    xlabel: str = "X",
    ylabel: str = "Y",
    markers: bool = False,
    stem: str = "line",
) -> dict:
    """折线图（趋势 / 时序 / 随参数变化）。

    Args:
        x / y: 两组等长数值序列。
        markers: 是否在数据点画标记。
    """
    xa = _arr(x, "x")
    ya = _arr(y, "y")
    if xa.size != ya.size:
        raise ValueError(f"x({xa.size}) 与 y({ya.size}) 长度不一致。")
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    ax.plot(xa, ya, linewidth=1.6, marker="o" if markers else None, color="#1f77b4")
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)
    return _save(fig, stem)


@mcp.tool()
def plot_area(
    x: Sequence[float],
    y: Sequence[float],
    title: str = "面积图",
    xlabel: str = "X",
    ylabel: str = "Y",
    stem: str = "area",
) -> dict:
    """面积图（累积 / 占比趋势）。"""
    xa = _arr(x, "x")
    ya = _arr(y, "y")
    if xa.size != ya.size:
        raise ValueError(f"x({xa.size}) 与 y({ya.size}) 长度不一致。")
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    ax.fill_between(xa, ya, alpha=0.35, color="#1f77b4")
    ax.plot(xa, ya, linewidth=1.4, color="#1f77b4")
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)
    return _save(fig, stem)


@mcp.tool()
def plot_dual_axes(
    x: Sequence[float],
    y1: Sequence[float],
    y2: Sequence[float],
    label1: str = "系列1",
    label2: str = "系列2",
    title: str = "双轴图",
    xlabel: str = "X",
    ylabel1: str = "Y1",
    ylabel2: str = "Y2",
    stem: str = "dual_axes",
) -> dict:
    """双 Y 轴图（两个量纲不同的序列同图对比，如温度 vs 产量）。

    Args:
        x: 横轴；y1 / y2: 两条序列，均须与 x 等长。
        label1 / label2: 两条曲线的图例名。
    """
    xa = _arr(x, "x")
    a1 = _arr(y1, "y1")
    a2 = _arr(y2, "y2")
    if not (xa.size == a1.size == a2.size):
        raise ValueError(f"x({xa.size})、y1({a1.size})、y2({a2.size}) 长度须一致。")
    fig, ax1 = plt.subplots(figsize=(7.5, 4.5))
    ax1.plot(xa, a1, color="#1f77b4", linewidth=1.6, label=label1)
    ax1.set_xlabel(xlabel)
    ax1.set_ylabel(ylabel1, color="#1f77b4")
    ax1.tick_params(axis="y", labelcolor="#1f77b4")
    ax2 = ax1.twinx()
    ax2.plot(xa, a2, color="#d62728", linewidth=1.6, label=label2)
    ax2.set_ylabel(ylabel2, color="#d62728")
    ax2.tick_params(axis="y", labelcolor="#d62728")
    ax1.set_title(title)
    ax1.grid(alpha=0.3)
    return _save(fig, stem)


@mcp.tool()
def plot_pie(
    labels: Sequence[str],
    values: Sequence[float],
    title: str = "饼图",
    stem: str = "pie",
) -> dict:
    """饼图（构成 / 占比，如样本类别分布）。"""
    vals = _arr(values, "values")
    names = _labels_for(vals.size, labels)
    if (vals < 0).any():
        raise ValueError("饼图数值不能为负。")
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.pie(vals, labels=names, autopct="%1.1f%%", startangle=90)
    ax.axis("equal")
    ax.set_title(title)
    return _save(fig, stem)


@mcp.tool()
def plot_radar(
    labels: Sequence[str],
    values: Sequence[float],
    title: str = "雷达图",
    stem: str = "radar",
) -> dict:
    """雷达图（多维指标对比，如方法在多维度评分）。

    Args:
        labels: 各维度名称。
        values: 各维度数值（与 labels 等长）。
    """
    vals = _arr(values, "values")
    names = _labels_for(vals.size, labels)
    n = vals.size
    if n < 3:
        raise ValueError("雷达图至少需要 3 个维度。")
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    vals_c = np.concatenate([vals, [vals[0]]])
    angles_c = angles + [angles[0]]
    names_c = names + [names[0]]
    fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
    ax.plot(angles_c, vals_c, linewidth=1.5, color="#1f77b4")
    ax.fill(angles_c, vals_c, alpha=0.25, color="#1f77b4")
    ax.set_xticks(angles)
    ax.set_xticklabels(names)
    ax.set_title(title)
    return _save(fig, stem)


@mcp.tool()
def plot_waterfall(
    labels: Sequence[str],
    values: Sequence[float],
    title: str = "瀑布图",
    ylabel: str = "累计值",
    stem: str = "waterfall",
) -> dict:
    """瀑布图（从基准逐步增减到终值，如误差分解 / 贡献分解）。

    Args:
        labels: 每一步名称。
        values: 每一步的增量（可正可负），自动从 0 累加。
    """
    vals = _arr(values, "values")
    names = _labels_for(vals.size, labels)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    running = 0.0
    for i, (name, v) in enumerate(zip(names, vals)):
        bottom = running if v >= 0 else running + v
        color = "#4c72b0" if v >= 0 else "#d62728"
        ax.bar(i, abs(v), bottom=bottom, color=color, edgecolor="black", linewidth=0.5)
        running += v
    ax.set_xticks(range(vals.size))
    ax.set_xticklabels(names)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.3)
    return _save(fig, stem)


@mcp.tool()
def list_figures() -> dict:
    """列出已生成的图片文件（PDF 矢量 + PNG 预览），便于写报告时取用。"""
    if not FIG_DIR.exists():
        return {"ok": True, "dir": str(FIG_DIR.resolve()), "count": 0, "files": []}
    files = sorted(
        (str(p.resolve()) for p in FIG_DIR.iterdir() if p.suffix.lower() in {".pdf", ".png"}),
    )
    return {"ok": True, "dir": str(FIG_DIR.resolve()), "count": len(files), "files": files}


if __name__ == "__main__":
    mcp.run()
