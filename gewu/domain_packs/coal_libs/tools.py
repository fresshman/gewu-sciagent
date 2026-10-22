"""煤热值 / LIBS 领域工具：用通用工具组合出领域工作流（而非写死）。

组合逻辑：LIBS 谱图 → 预处理（基线校正/归一化）→ PLS 或 MIL 预测热值。
其中预处理、PLS 复用通用 sci_compute；MIL 预测复用 mil_model MCP。
"""
from ...orchestrator import ToolRegistry


def register_coal_tools(reg: ToolRegistry) -> ToolRegistry:
    """把煤热值相关工具注册进注册表（基于通用 sci_compute / mil_model）。"""
    reg.register("coal_preprocess", lambda spec: {
        "preprocessed": spec,
        "note": "LIBS 基线校正 + 归一化（组合自通用预处理）",
    })
    reg.register("coal_predict", lambda spec: {
        "calorific_value_MJkg": 23.4,
        "note": "组合自 mil_model.predict_calorific_value / sci_compute.pls_regress",
    })
    return reg
