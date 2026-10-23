"""多模态科学数据解析 MCP Server（书生 InternVL / 原页渲染）。

两层能力：
1) 视觉解析：parse_figure 调用书生视觉模型（internvl3.5）解析科学图（谱图/曲线/分子式）。
2) 原页渲染：render_pdf_pages 把论文 PDF 渲染成 PNG，交给书生 intern-s2 做
   科学多模态原页理解（图+表+公式同帧联合推理）。image_to_data_uri 把 PNG
   转 base64 data URI，供 Agent 以 image_url 直接发给 sheng/intern-s2。
"""
import base64
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("sci-data")

# 渲染图输出目录（默认与 sci-plot 共用 GEWU_FIG_DIR，避免散落）
_FIG_DIR = os.environ.get("GEWU_FIG_DIR", "output/figures")
_PAGES_DIR = os.path.join(_FIG_DIR, "pdf_pages")


@mcp.tool()
def parse_figure(image_path: str) -> dict:
    """用 InternVL 解析科学图（谱图/曲线/分子式）为结构化数据。

    说明：生产环境调用书生视觉模型（internvl3.5-241b-a28b）；
    MVP 阶段返回占位结构，便于流水线先行打通。
    """
    return {
        "modality": "unknown",
        "path": image_path,
        "note": "调用 InternVL 解析；MVP 阶段用占位结构，接 internvl3.5-241b-a28b",
    }


@mcp.tool()
def render_pdf_pages(pdf_path: str, pages: str = "all", dpi: int = 150, out_dir: str = "") -> dict:
    """把论文 PDF 渲染成 PNG 图片，供书生(intern-s2)多模态原页理解。

    这是"科学多模态原页理解"的本地前置：把 PDF 原页转成模型能吃的图像，
    再由 Agent 以 image_url（见 image_to_data_uri）直接发给 sheng/intern-s2，
    让模型在统一表征空间联合理解图/表/公式，而非仅看文本摘要。

    Args:
        pdf_path: PDF 文件路径（本地绝对/相对路径）。
        pages: "all"=全页；或逗号分隔 1-based 页码（如 "1,3,5"）；
               或 "figtab"=启发式选含图/表的页（暂退化为全页，留扩展位）。
        dpi: 渲染分辨率，默认 150。省 token 可降到 110~130；
             过高会显著增大后续 base64 体积。
        out_dir: 输出目录，默认 <GEWU_FIG_DIR>/pdf_pages/。

    Returns:
        {pdf, n_pages, rendered, images:[{page, path, width, height}], note}
    """
    import fitz  # PyMuPDF，default venv 已装

    pdf_path = os.path.expanduser(pdf_path)
    if not os.path.isfile(pdf_path):
        return {"error": f"PDF 不存在: {pdf_path}"}

    out = out_dir or _PAGES_DIR
    os.makedirs(out, exist_ok=True)

    doc = fitz.open(pdf_path)
    total = doc.page_count

    if pages in ("all", "figtab"):
        idxs = list(range(total))
    else:
        try:
            idxs = [int(p.strip()) - 1 for p in pages.split(",") if p.strip()]
        except ValueError:
            return {"error": "pages 格式错误，应为 'all' / 'figtab' / '1,3,5'"}
    idxs = [i for i in idxs if 0 <= i < total]
    if not idxs:
        return {"error": "没有可渲染的页面"}

    images = []
    for i in idxs:
        page = doc[i]
        pix = page.get_pixmap(dpi=dpi)
        w, h = pix.width, pix.height
        fname = f"page_{i + 1:03d}.png"
        fpath = os.path.join(out, fname)
        pix.save(fpath)
        images.append({"page": i + 1, "path": os.path.abspath(fpath), "width": w, "height": h})
    doc.close()

    return {
        "pdf": os.path.abspath(pdf_path),
        "n_pages": total,
        "rendered": len(images),
        "images": images,
        "note": "下一步用 image_to_data_uri 转 base64，再作为 image_url 发给 sheng/intern-s2 做原页理解",
    }


@mcp.tool()
def image_to_data_uri(image_path: str, max_bytes: int = 4_000_000) -> dict:
    """把本地 PNG/JPG 转成 data:image/...;base64,... URI，供 Agent 直接发给多模态模型。

    书生 intern-s2 走 openai-completions 兼容接口，支持 image_url 内联 base64。
    警告：base64 会显著占用上下文（150dpi A4 ≈ 数十 KB→数万 token/图），
    请配合 render_pdf_pages 的 dpi/pages 精选使用；单图超过 max_bytes 会提示降分辨率。

    Args:
        image_path: 图片路径（通常是 render_pdf_pages 的输出）。
        max_bytes: 单图 base64 上限（默认 4MB），超出返回警告与建议。

    Returns:
        {path, media_type, data_uri, size_bytes, truncated, note}
    """
    image_path = os.path.expanduser(image_path)
    if not os.path.isfile(image_path):
        return {"error": f"图片不存在: {image_path}"}
    ext = Path(image_path).suffix.lower()
    media = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(ext, "image/png")
    with open(image_path, "rb") as f:
        raw = f.read()
    b64 = base64.b64encode(raw).decode("ascii")
    size = len(b64)
    if size > max_bytes:
        return {
            "path": os.path.abspath(image_path),
            "media_type": media,
            "size_bytes": size,
            "truncated": True,
            "warning": (
                f"base64 体积 {size} 超上限 {max_bytes}，请降低 render_pdf_pages 的 "
                f"dpi 或缩小 pages 范围后再调用"
            ),
        }
    return {
        "path": os.path.abspath(image_path),
        "media_type": media,
        "data_uri": f"data:{media};base64,{b64}",
        "size_bytes": size,
        "truncated": False,
        "note": "将此 data_uri 作为 image_url 的 url 字段，与文本 content 一起发给 sheng/intern-s2",
    }


if __name__ == "__main__":
    mcp.run()
