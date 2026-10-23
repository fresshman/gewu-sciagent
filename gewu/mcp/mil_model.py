"""MIL 热值预测 MCP Server（领域专属，真实推理）。

与旧版（返回硬编码 demo 值）的关键差别：
    本服务**不再持有任何模型权重或数据**。真实 MIL 模型与 LIBS 数据留在
    用户本机未发表项目（coal-calorific-value）中，通过环境变量
    ``COAL_PROJECT_ROOT`` 在运行时按路径引用；本服务以 subprocess 调用
    同目录的 ``coal_infer.py`` 完成真实前向推理。

    这样既让格物跑出**可复现的真实热值预测**（而非占位数字），
    又保证未发表的模型权重与实验数据不进入格物仓库、不出本机。

推理链：hybrid(kcal/kg) = PLSR(bag_mean) + MIL_residual，再按 0.004184 换算 MJ/kg。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mil-model")

_HERE = os.path.dirname(os.path.abspath(__file__))
COAL_INFER = os.path.join(_HERE, "coal_infer.py")

# 外部项目根目录（仅路径引用，不复制数据入库）。仓库内不写死任何机器绝对路径，
# 按优先级发现：环境变量 COAL_PROJECT_ROOT → 项目根 .coal_project_root 文件（已 gitignore）
_PROJECT_ROOT_HINT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".coal_project_root",
)


def _coal_root() -> str:
    env = os.environ.get("COAL_PROJECT_ROOT", "").strip()
    if env:
        return env
    if os.path.exists(_PROJECT_ROOT_HINT):
        with open(_PROJECT_ROOT_HINT, "r", encoding="utf-8") as f:
            v = f.read().strip()
        if v:
            return v
    return ""


def _coal_python() -> str:
    """定位带 torch 的解释器：环境变量优先，其次探测 WorkBuddy 的独立 venv。

    coal-torch 是独立 venv（含 torch），与格物 default venv 的 mcp<2 环境隔离，
    避免污染其余 Python MCP 服务。
    """
    env = os.environ.get("GEWU_COAL_PYTHON")
    if env and os.path.exists(env):
        return env
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".workbuddy", "binaries", "python", "envs", "coal-torch", "Scripts", "python.exe"),
        os.path.join(home, ".workbuddy", "binaries", "python", "envs", "coal-torch", "bin", "python"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return sys.executable


def _run(args: list[str], timeout: int = 1800) -> dict:
    """调用 coal_infer.py 并解析其 JSON 输出。"""
    if not os.path.exists(COAL_INFER):
        return {"status": "error", "detail": f"推理脚本缺失: {COAL_INFER}"}
    root = _coal_root()
    if not root:
        return {
            "status": "not-configured",
            "detail": "未配置煤热值项目根目录（模型与未发表数据保持在外部项目，格物只按路径读取）",
            "howto": "设置环境变量 COAL_PROJECT_ROOT，或在格物项目根写入 .coal_project_root 文件（内容=绝对路径，已 gitignore）",
        }
    env = dict(os.environ)
    env["COAL_PROJECT_ROOT"] = root
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            [_coal_python(), COAL_INFER, *args],
            capture_output=True, text=True, encoding="utf-8",
            env=env, timeout=timeout, cwd=_HERE,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "detail": f"推理超时（>{timeout}s），可增大 timeout 或改用 predict_fold 分批"}
    except FileNotFoundError as e:
        return {"status": "error", "detail": f"解释器不可用: {e}；请设置 GEWU_COAL_PYTHON"}

    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        return {
            "status": "error",
            "returncode": proc.returncode,
            "stderr": (proc.stderr or "")[-1500:],
            "hint": "确认 COAL_PROJECT_ROOT 指向 coal-calorific-value 项目，且 coal-torch 环境已装 torch",
        }
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        tail = out[-800:]
        try:
            return json.loads(tail)
        except json.JSONDecodeError:
            return {"status": "error", "detail": "输出非 JSON", "raw": tail}


@mcp.tool()
def predict_calorific_value(bag_dir: str, fold: int = 0) -> dict:
    """用真实 MIL 模型预测一个原煤 bag 的热值（真实推理，非 demo）。

    bag_dir: 单个 bag 目录，内含该样品的多张 LIBS 光谱 CSV（多示例学习的"袋"）。
    fold:    使用第几折交叉验证的模型权重（0-4），默认 0。

    返回 hybrid 融合预测（PLSR + MIL 残差修正），同时给出 kcal/kg 与 MJ/kg。
    模型与数据始终留在 COAL_PROJECT_ROOT 指向的外部项目，不入库、不上云。
    """
    if not bag_dir or not str(bag_dir).strip():
        return {"status": "error", "detail": "bag_dir 不能为空"}
    return _run(["predict-bag", "--bag-dir", str(bag_dir), "--fold", str(int(fold))], timeout=900)


@mcp.tool()
def list_val_bags(fold: int = 0) -> dict:
    """列出第 fold 折交叉验证的验证集 bag 列表（供选择真实样本做预测）。"""
    return _run(["list-bags", "--fold", str(int(fold))], timeout=600)


@mcp.tool()
def reproduce_fold(fold: int = 0) -> dict:
    """复现第 fold 折验证集的全部预测，返回 RMSE/MAE/R² 与逐 bag 明细。

    用于验证格物能否**真实复现**论文中的 5 折交叉验证结果（可复现性校验）。
    计算量较大（需前向推理整个验证集），请耐心等待。
    """
    return _run(["predict-fold", "--fold", str(int(fold))], timeout=1800)


@mcp.tool()
def cv_summary() -> dict:
    """汇总 5 折交叉验证指标，并与外部项目官方 summary.json 交叉校验。

    返回每折 RMSE（PLSR 基线 vs MIL+PLSR 融合）、均值±标准差，
    以及"官方记录值 vs 本地重算值"的差值（用于确认结果未被篡改/可复现）。
    """
    return _run(["cv-summary"], timeout=600)


if __name__ == "__main__":
    mcp.run()
