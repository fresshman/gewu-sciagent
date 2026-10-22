"""MIL 热值预测 MCP Server：加载 OpenVINO 量化模型（领域专属，标准封装）。"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mil-model")

_MODEL = None


def _load(model_path: str):
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    import openvino as ov
    _MODEL = ov.Core().read_model(model_path)
    return _MODEL


@mcp.tool()
def predict_calorific_value(spectrum: list[float], model_path: str = "data/models/mil_coal.xml") -> dict:
    """用 OpenVINO 量化的 MIL 模型预测原煤热值(MJ/kg)。

    将你的 MIL 模型导出为 OpenVINO(.xml/.bin) 置于 data/models/ 后启用；
    未导出时返回明确提示，不抛错。
    """
    try:
        import openvino as ov  # noqa: F401
        import numpy as np  # noqa: F401
        _load(model_path)
        # TODO: 按模型输入输出签名补全推理（参考实现阶段完善）
        return {"calorific_value_MJkg": 23.4, "model": model_path, "status": "demo-output"}
    except Exception as e:
        return {
            "status": "model-not-loaded",
            "detail": str(e),
            "note": "将 MIL 模型导出为 OpenVINO(.xml/.bin)置于 data/models/ 后启用",
        }


if __name__ == "__main__":
    mcp.run()
