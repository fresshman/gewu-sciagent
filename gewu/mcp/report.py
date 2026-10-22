"""报告 / 论文生成 MCP Server。"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("report")


@mcp.tool()
def generate_report(context: dict) -> str:
    """根据科研上下文生成 Markdown 报告 / 论文草稿。"""
    return f"# 科研报告\n\n{context}"


if __name__ == "__main__":
    mcp.run()
