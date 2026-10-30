"""煤热值 / LIBS 领域工具：用「通用工具 + 领域模型」组合出领域工作流。

改动说明（重要）：
    旧版依赖早已移除的 ``orchestrator.ToolRegistry``（格物 Python 侧只保留工具层，
    控制流交给 OpenClaw 原生编排），因此本文件实际是**无法运行的死代码**，
    且 ``coal_predict`` 返回硬编码 23.4 —— 属于占位空壳。

    现改为**薄封装**：直接委托 ``coal_infer.py`` 做真实推理（subprocess 调用，
    torch 运行在独立的 coal-torch 环境，不污染本进程）。领域工作流语义保留，
    但输出的是真实预测值。

    模型权重与未发表 LIBS 数据始终留在 ``COAL_PROJECT_ROOT`` 指向的外部项目，
    本模块只按路径引用，不复制、不入库、不上云。
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# 指向 gewu/mcp/coal_infer.py
COAL_INFER = os.path.normpath(os.path.join(_HERE, "..", "..", "mcp", "coal_infer.py"))
_PROJECT_ROOT_HINT = os.path.normpath(
    os.path.join(_HERE, "..", "..", "..", ".coal_project_root")
)


def _coal_python() -> str:
    """定位带 torch 的解释器（环境变量优先，其次 WorkBuddy 独立 venv）。"""
    env = os.environ.get("GEWU_COAL_PYTHON")
    if env and os.path.exists(env):
        return env
    home = os.path.expanduser("~")
    for c in (
        os.path.join(home, ".workbuddy", "binaries", "python", "envs", "coal-torch", "Scripts", "python.exe"),
        os.path.join(home, ".workbuddy", "binaries", "python", "envs", "coal-torch", "bin", "python"),
    ):
        if os.path.exists(c):
            return c
    return sys.executable


def _coal_root() -> str:
    """外部项目根目录：环境变量优先，其次 gitignore 的 .coal_project_root。"""
    env = os.environ.get("COAL_PROJECT_ROOT", "").strip()
    if env:
        return env
    if os.path.exists(_PROJECT_ROOT_HINT):
        with open(_PROJECT_ROOT_HINT, "r", encoding="utf-8") as f:
            v = f.read().strip()
        if v:
            return v
    return ""


def _call(args: list[str], timeout: int = 900) -> dict:
    root = _coal_root()
    if not root:
        return {
            "status": "not-configured",
            "detail": "未配置 COAL_PROJECT_ROOT（模型与未发表数据保留在外部项目，格物只按路径读取）",
        }
    env = dict(os.environ)
    env["COAL_PROJECT_ROOT"] = root
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            [_coal_python(), COAL_INFER, *args],
            capture_output=True, text=True, encoding="utf-8",
            env=env, timeout=timeout, cwd=os.path.dirname(COAL_INFER),
            stdin=subprocess.DEVNULL,  # 同 mil_model：不让子进程继承 MCP 的 stdin 管道
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "detail": f"推理超时（>{timeout}s）"}
    except FileNotFoundError as e:
        return {"status": "error", "detail": f"解释器不可用: {e}"}
    out = (proc.stdout or "").strip()
    if not out:
        return {"status": "error", "stderr": (proc.stderr or "")[-1000:]}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"status": "error", "detail": "输出非 JSON", "raw": out[-600:]}


def coal_preprocess(bag_dir: str) -> dict:
    """LIBS 谱预处理（sg 平滑 → als 基线校正 → mms 归一化）。

    实际预处理在 ``coal_infer.py`` 内部复用原项目 ``src/data/preprocess.py`` 完成，
    与训练时字节级一致；此处只做输入校验与工作流说明，避免重复实现导致行为漂移。
    """
    if not os.path.isdir(bag_dir):
        return {"status": "error", "detail": f"bag 目录不存在: {bag_dir}"}
    n = len(glob.glob(os.path.join(bag_dir, "*.csv")))
    return {
        "status": "ok",
        "bag_dir": bag_dir,
        "n_spectra": n,
        "pipeline": ["sg", "als", "mms"],
        "note": "预处理由 coal_infer 复用原项目 src 实现，与训练严格一致",
    }


def coal_predict(bag_dir: str, fold: int = 0) -> dict:
    """预测一个 bag 的原煤热值（真实推理，非 demo）。

    领域工作流 = 通用预处理 + PLSR 基线 + 领域 MIL 残差修正。
    """
    return _call(["predict-bag", "--bag-dir", str(bag_dir), "--fold", str(int(fold))])


def coal_cv_summary() -> dict:
    """获取 5 折交叉验证指标汇总（含与官方 summary.json 的交叉校验）。"""
    return _call(["cv-summary"])


def register_coal_tools(reg=None):
    """兼容旧接口：传入具 register 方法的注册表则注册，否则返回函数映射。

    格物的工具注册已由 MCP 层承担（控制流在 OpenClaw），此处保留仅为兼容。
    """
    tools = {
        "coal_preprocess": coal_preprocess,
        "coal_predict": coal_predict,
        "coal_cv_summary": coal_cv_summary,
    }
    if reg is not None and hasattr(reg, "register"):
        for name, fn in tools.items():
            reg.register(name, fn)
        return reg
    return tools
