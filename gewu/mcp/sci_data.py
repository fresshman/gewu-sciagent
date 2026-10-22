"""多模态科学数据解析 MCP Server（InternVL 视觉）。MVP 阶段返回占位结构。"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("sci-data")


@mcp.tool()
def parse_figure(image_path: str) -> dict:
    """用 InternVL 解析科学图（谱图/曲线/分子式）为结构化数据。

    说明：生产环境调用书生视觉模型（settings.internlm.vision_model）；
    MVP 阶段返回占位结构，便于流水线先行打通。
    """
    return {
        "modality": "unknown",
        "path": image_path,
        "note": "调用 InternVL 解析；MVP 阶段用占位结构，接 settings.internlm.vision_model",
    }


if __name__ == "__main__":
    mcp.run()
