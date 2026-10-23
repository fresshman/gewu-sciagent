"""报告 / 论文生成 MCP Server。

提供两类能力：
1) 科研报告 / 论文草稿生成（generate_report）。
2) 本地文档落地（"本地写 LaTeX"工具族）：把智能体生成的 .tex/.bib 等源文件
   写入本机目录，不依赖 Overleaf 等云端，符合格物"本地优先"原则。
"""
import os
import shutil
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("report")

# 文档落地根目录：相对路径会锚定到这里，绝对路径按原样使用（本地智能体，运行在用户本机）。
_DOC_BASE = os.environ.get(
    "GEWU_DOC_DIR",
    os.path.join(os.getcwd(), "output", "documents"),
)


def _resolve(rel_or_abs: str) -> str:
    """解析写入路径。

    - 绝对路径：原样返回（本地智能体运行在用户本机，允许写到项目外的论文/学位论文目录）。
    - 相对路径：锚定到 GEWU_DOC_DIR，并拦截 `../` 越界逃出根目录。
    """
    p = os.path.expanduser(rel_or_abs)
    if os.path.isabs(p):
        return os.path.abspath(p)
    p = os.path.abspath(os.path.join(_DOC_BASE, p))
    base = os.path.abspath(_DOC_BASE)
    if not (p == base or p.startswith(base + os.sep)):
        raise ValueError(
            f"相对路径越界：{rel_or_abs} 解析到 {p}，必须位于 {_DOC_BASE} 之内"
        )
    return p


@mcp.tool()
def generate_report(context: dict) -> str:
    """根据科研上下文生成 Markdown 报告 / 论文草稿。"""
    return f"# 科研报告\n\n{context}"


@mcp.tool()
def write_local_file(path: str, content: str, overwrite: bool = False) -> str:
    """把单段文本内容写入本机文件（可用于 .tex/.bib/.cls/.md 等任何文本文件）。

    - path: 相对路径锚定到 GEWU_DOC_DIR（默认 <项目>/output/documents），也可传绝对路径。
    - content: 文件全文内容。
    - overwrite: False 时若文件已存在则报错，避免误覆盖。
    返回写入的绝对路径与字节数。
    """
    dst = _resolve(path)
    if os.path.exists(dst) and not overwrite:
        raise FileExistsError(f"文件已存在（未开启 overwrite）：{dst}")
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(content)
    return f"已写入 {dst}（{len(content.encode('utf-8'))} 字节）"


@mcp.tool()
def write_latex_project(project_dir: str, files: dict, overwrite: bool = False) -> str:
    """一次性把一个 LaTeX 项目（多文件）写入本机目录，不依赖 Overleaf。

    - project_dir: 项目根目录（相对锚定 GEWU_DOC_DIR / 或绝对路径），不存在则创建。
    - files: {相对路径: 文件全文}，例如
        {"main.tex": "...", "sections/intro.tex": "...", "refs.bib": "..."}。
        父目录自动创建；overwrite=False 时任一文件已存在则整体中止并报告，避免部分写入。
    返回写入的文件清单（绝对路径 + 行数）。
    """
    root = _resolve(project_dir)
    # 预检：避免写了一半才发现冲突
    conflicts = []
    for rel in files:
        dst = os.path.join(root, rel)
        if os.path.exists(dst) and not overwrite:
            conflicts.append(dst)
    if conflicts:
        raise FileExistsError(
            "以下文件已存在（未开启 overwrite），已中止以免部分写入：\n" + "\n".join(conflicts)
        )
    written = []
    for rel, content in files.items():
        dst = os.path.join(root, rel)
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(content)
        nlines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        written.append(f"{dst}  ({nlines} 行)")
    return f"LaTeX 项目已写入 {root}，共 {len(written)} 个文件：\n" + "\n".join(written)


@mcp.tool()
def copy_local_file(src: str, dst: str, overwrite: bool = False) -> str:
    """把本机已有文件（如 sci-plot 生成的矢量图 PDF/PNG）复制到 LaTeX 项目目录。

    - src: 源文件绝对路径（必须存在）。
    - dst: 目标路径（相对锚定 GEWU_DOC_DIR / 或绝对路径）。
    返回目标绝对路径与大小。
    """
    if not os.path.exists(src):
        raise FileNotFoundError(f"源文件不存在：{src}")
    target = _resolve(dst)
    if os.path.exists(target) and not overwrite:
        raise FileExistsError(f"目标已存在（未开启 overwrite）：{target}")
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    shutil.copy2(src, target)
    size = os.path.getsize(target)
    return f"已复制 {src} -> {target}（{size} 字节）"


if __name__ == "__main__":
    mcp.run()
