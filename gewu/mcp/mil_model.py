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

try:  # 作为包导入时
    from .context_compactor import compact as _compact, expand as _expand
except ImportError:  # openclaw 用绝对路径把本文件当脚本起，sys.path[0] 即本目录
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from context_compactor import compact as _compact, expand as _expand

SERVER = "mil-model"
mcp = FastMCP(SERVER)

_HERE = os.path.dirname(os.path.abspath(__file__))
COAL_INFER = os.path.join(_HERE, "coal_infer.py")

# 超时层级铁律：工具内的 gate 必须**小于** MCP 客户端的 requestTimeoutMs，还要留出把错误
# JSON 送回模型的余量。错配的代价是实测过的（2026-10-28 会话 coal-demo-v3，2404s 撞墙超时）：
# reproduce_fold 内部 1800s 还没到，客户端 900s 先炸成 "MCP error -32001: Request timed out"，
# 模型拿不到"改用 predict_fold 分批"这句可执行建议，只能退化成一串 exec 摸索再烧掉十几轮。
# 与 openclaw.json 的 mcp.servers.mil-model.requestTimeoutMs 对齐，回归由
# tests/test_mcp_timeout_hierarchy.py 守。
CLIENT_REQUEST_TIMEOUT_S = 900
TIMEOUT_HEADROOM_S = 60
MAX_TOOL_TIMEOUT_S = CLIENT_REQUEST_TIMEOUT_S - TIMEOUT_HEADROOM_S

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


def _run(args: list[str], timeout: int = MAX_TOOL_TIMEOUT_S, tool: str = "") -> dict:
    """调用 coal_infer.py 并解析其 JSON 输出；大结果按 CCR 规则压缩后再返回。

    timeout 一律被夹到 MAX_TOOL_TIMEOUT_S：调用方写更大的数不会生效，因为超过
    MCP 客户端的 requestTimeoutMs 后先炸的是客户端（-32001），不是这里。
    """
    timeout = min(int(timeout), MAX_TOOL_TIMEOUT_S)
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
            # 必须切断 stdin：本服务由 MCP stdio 拉起，子进程默认继承那根 JSON-RPC 管道，
            # 实测会让子进程一直挂到自己的 timeout（get_cached_metrics 0.2s→60s 超时，
            # cv_summary/reproduce_fold 同理被误判成"推理太慢"）。
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "detail": (
            f"推理超时（>{timeout}s）。单次调用上限就是 MCP 客户端的 "
            f"{CLIENT_REQUEST_TIMEOUT_S}s（留 {TIMEOUT_HEADROOM_S}s 回传余量），调大本工具"
            f"的 timeout 不会生效；要跑更久的任务请改用 predict_calorific_value 逐 bag、"
            f"reproduce_fold 逐折分批，或把它挪出网关轮次走后台")}
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
        return _compact(json.loads(out), server=SERVER, tool=tool or args[0])
    except json.JSONDecodeError:
        tail = out[-800:]
        try:
            return _compact(json.loads(tail), server=SERVER, tool=tool or args[0])
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
    return _run(["predict-bag", "--bag-dir", str(bag_dir), "--fold", str(int(fold))],
                timeout=MAX_TOOL_TIMEOUT_S, tool="predict_calorific_value")


@mcp.tool()
def list_val_bags(fold: int = 0) -> dict:
    """列出第 fold 折交叉验证的验证集 bag 列表（供选择真实样本做预测）。

    列表过长时会返回压缩视图（digest + __raw_path）：数值逐字保留，但被抽掉公共
    前缀的 bag_dir 剩余部分**不能直接当路径用**，要完整路径请调 expand_result；
    未内联的条目用 selector 取，不要凭印象编。
    """
    return _run(["list-bags", "--fold", str(int(fold))], timeout=600, tool="list_val_bags")


@mcp.tool()
def reproduce_fold(fold: int = 0) -> dict:
    """复现第 fold 折验证集的全部预测，返回 RMSE/MAE/R² 与逐 bag 明细。

    用于验证格物能否**真实复现**论文中的 5 折交叉验证结果（可复现性校验）。
    实测整折 14 个 bag 的真实 torch 前向约 11s（首次加载权重），不是分钟级任务。
    逐 bag 明细过长时只内联前若干条，其余用 expand_result(path, "predictions[8:14]") 取。
    """
    return _run(["predict-fold", "--fold", str(int(fold))], timeout=MAX_TOOL_TIMEOUT_S, tool="reproduce_fold")


@mcp.tool()
def cv_summary() -> dict:
    """汇总 5 折交叉验证指标，并与外部项目官方 summary.json 交叉校验。

    返回每折 RMSE（PLSR 基线 vs MIL+PLSR 融合）、均值±标准差，
    以及"官方记录值 vs 本地重算值"的差值（用于确认结果未被篡改/可复现）。
    """
    return _run(["cv-summary"], timeout=600, tool="cv_summary")


@mcp.tool()
def get_cached_metrics() -> dict:
    """秒级返回已缓存的 5 折交叉验证指标，**不加载 torch、不跑任何推理**。

    优先读外部项目官方 summary.json；缺失时退而从各折缓存的 predictions.json 重算 RMSE
    （同样不碰 torch，仅 numpy）。适用于 Agent 在 handoff 中即时、零风险地填真实
    metrics，或作为耗时的 reproduce_fold / cv_summary 的即时替代。
    返回字段含 `source` 标记（official_summary.json / recomputed_from_cached_predictions）
    与 `cross_check`，便于反幻觉溯源；`torch_used` 恒为 False。
    """
    return _run(["get-cached-metrics"], timeout=60, tool="get_cached_metrics")


@mcp.tool()
def expand_result(path: str, selector: str = "", fields: list[str] | None = None,
                  max_chars: int | None = None) -> dict:
    """取回被压缩工具结果的**原文**（字节级一致，读的是落盘那份，不做近似重建）。

    path:     压缩结果里的 __raw_path（只允许读落盘目录 ~/.gewu/mcp-raw 内的文件）。
    selector: 点号 + 下标，可叠加："" 整份 / `val_bags` / `val_bags[8:14]` /
              `val_bags[*].bag_dir` / `digest`；不写就是整份原文。
    fields:   对数组结果做字段投影，如 ["bag_id", "hybrid_pred"]，比整条取回省得多。
    max_chars: 单次允许内联的最大字符数，超出则再压一层并给出更细的 selector。
               不传时用环境变量 GEWU_MCP_EXPAND_MAX（默认 8000）。

    用法纪律：需要 digest 里没有的条目或完整路径时**必须先调本工具**，
    不要根据前缀猜路径、不要凭印象补数值。
    """
    return _expand(path, selector=selector, fields=fields, max_chars=max_chars, server=SERVER)


if __name__ == "__main__":
    mcp.run()
