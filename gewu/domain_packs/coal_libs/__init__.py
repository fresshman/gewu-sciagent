"""领域包：coal_libs（参考实现 — 大颗粒原煤 LIBS 光谱热值预测）。

领域工作流由「通用工具 + 领域模型」组合而成，真实推理委托给
``gewu/mcp/coal_infer.py``（模型与未发表数据按路径引用，不入库）。
"""
from .tools import (
    coal_predict,
    coal_preprocess,
    coal_cv_summary,
    register_coal_tools,
)

__all__ = ["coal_predict", "coal_preprocess", "coal_cv_summary", "register_coal_tools"]
