"""多模态科学数据解析 MCP Server（书生 InternVL / 原页渲染）。

两层能力：
1) 视觉解析：parse_figure 调用书生视觉模型（internvl3.5）解析科学图（谱图/曲线/分子式）。
2) 原页渲染：render_pdf_pages 把论文 PDF 渲染成 PNG，交给书生 intern-s2 做
   科学多模态原页理解（图+表+公式同帧联合推理）。image_to_data_uri 把 PNG
   转 base64 data URI，供 Agent 以 image_url 直接发给 sheng/intern-s2。
"""
import base64
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from context_compactor import compact as _compact, expand as _expand  # noqa: E402

SERVER = "sci-data"
mcp = FastMCP(SERVER)


def _out(payload: dict, tool: str) -> dict:
    """大结果（整页清单、几十张渲染图路径）只回摘要，原文落盘可回取。

    例外：image_to_data_uri 不走这里——它的返回值是给模型的图像载荷，不是给模型读的数据。
    """
    return _compact(payload, server=SERVER, tool=tool)

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


def _open_fitz():
    """导入 PyMuPDF：新版包名 pymupdf，旧版兼容 fitz。"""
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover - 旧环境回退
        import fitz
    return fitz


def _page_stats(doc) -> list:
    """逐页统计：文本字数、内嵌图数、是否为图表页的启发式判定。"""
    stats = []
    for i in range(doc.page_count):
        page = doc[i]
        text = page.get_text().strip()
        n_imgs = len(page.get_images())
        # 启发式：含内嵌图 → 必有图；文本很少(纯图页) → 大概率是图版
        is_fig = n_imgs > 0
        stats.append(
            {
                "page": i + 1,
                "n_chars": len(text),
                "n_images": n_imgs,
                "is_figure_page": is_fig,
                "head": " ".join(text.split())[:40],
            }
        )
    return stats


@mcp.tool()
def pdf_page_map(pdf_path: str) -> dict:
    """渲染前先探明"哪些页有图/表"，避免盲目渲染浪费上下文。

    实测教训：直接按正文提到的图号猜页码常猜错（图号与页码不对应，
    且一页可能无图只有表）。先调本工具拿到含图页清单，再把这些页号
    传给 render_pdf_pages，可显著减少无效 base64 与 token 消耗。

    Args:
        pdf_path: PDF 文件路径。

    Returns:
        {pdf, n_pages, pages:[{page,n_chars,n_images,is_figure_page,head}],
         figure_pages:[...], suggested_pages:"1,3,5"}
    """
    fitz = _open_fitz()
    pdf_path = os.path.expanduser(pdf_path)
    if not os.path.isfile(pdf_path):
        return {"error": f"PDF 不存在: {pdf_path}"}
    doc = fitz.open(pdf_path)
    stats = _page_stats(doc)
    doc.close()
    fig_pages = [s["page"] for s in stats if s["is_figure_page"]]
    return _out({
        "pdf": os.path.abspath(pdf_path),
        "n_pages": len(stats),
        "pages": stats,
        "figure_pages": fig_pages,
        "suggested_pages": ",".join(str(p) for p in fig_pages),
        "note": "把 suggested_pages（或按需精选）传给 render_pdf_pages.pages",
    }, "pdf_page_map")


@mcp.tool()
def render_pdf_pages(pdf_path: str, pages: str = "all", dpi: int = 130, out_dir: str = "") -> dict:
    """把论文 PDF 渲染成 PNG 图片，供书生(intern-s2)多模态原页理解。

    这是"科学多模态原页理解"的本地前置：把 PDF 原页转成模型能吃的图像，
    再由 Agent 以 image_url（见 image_to_data_uri）直接发给 sheng/intern-s2，
    让模型在统一表征空间联合理解图/表/公式，而非仅看文本摘要。

    Args:
        pdf_path: PDF 文件路径（本地绝对/相对路径）。
        pages: "all"=全页；或逗号分隔 1-based 页码（如 "1,3,5"）；
               或 "figtab"=只渲染含图的页（推荐：省 token）。
               不确定该渲染哪页时，先用 pdf_page_map 探明含图页。
        dpi: 渲染分辨率，默认 130。为什么不是 150：实测整页 dpi=150 的 base64 有
             706,800 字符，会被 image_to_data_uri 的 600,000 上限直接拒掉；
             dpi=130 → 572,204、dpi=110 → 410,500 才可用。要更高清就显式传 dpi
             并同时放大 max_bytes。
        out_dir: 输出目录，默认 <GEWU_FIG_DIR>/pdf_pages/。

    Returns:
        {pdf, n_pages, rendered, images:[{page, path, width, height}], note}
    """
    import fitz  # noqa: F401 - 兼容旧版；实际用 _open_fitz()
    fitz = _open_fitz()

    pdf_path = os.path.expanduser(pdf_path)
    if not os.path.isfile(pdf_path):
        return {"error": f"PDF 不存在: {pdf_path}"}

    out = out_dir or _PAGES_DIR
    os.makedirs(out, exist_ok=True)

    doc = fitz.open(pdf_path)
    total = doc.page_count

    if pages == "figtab":
        idxs = [s["page"] - 1 for s in _page_stats(doc) if s["is_figure_page"]]
        if not idxs:  # 无内嵌图（如矢量图/扫描件）→ 退回全页
            idxs = list(range(total))
    elif pages == "all":
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

    return _out({
        "pdf": os.path.abspath(pdf_path),
        "n_pages": total,
        "rendered": len(images),
        "images": images,
        "note": "下一步用 image_to_data_uri 转 base64，再作为 image_url 发给 sheng/intern-s2 做原页理解",
    }, "render_pdf_pages")


@mcp.tool()
def image_to_data_uri(image_path: str, max_bytes: int = 600_000) -> dict:
    """把本地 PNG/JPG 转成 data:image/...;base64,... URI，供 Agent 直接发给多模态模型。

    书生 intern-s2 走 openai-completions 兼容接口，支持 image_url 内联 base64。

    【这个工具刻意不做 CCR 压缩】它返回的 base64 就是"发给模型的载荷"本身，而不是
    给模型读的数据。压缩它等于让工具失效（模型拿不到图，expand_result 也补不回来——
    把 46 万字符原样取回正是我们要防的上下文爆炸）。所以本工具用 max_bytes 硬闸把关，
    其余 sci-data 工具仍走摘要+落盘。

    体积口径（本机实测，arXiv 1402.1349 第 1 页整页）：dpi=150 → base64 706,800 字符；
    dpi=130 → 572,204；dpi=110 → 410,500。所以默认上限 600,000 字符就是把"dpi≤130、
    一轮最多 1 页"这条纪律变成硬闸：一个整页就吃掉 256K 窗口的两三成，多喂几轮必然
    在后续阶段被截断（这是实测过的会话杀手）。确实需要更高分辨率时显式传大 max_bytes。

    Args:
        image_path: 图片路径（通常是 render_pdf_pages 的输出）。
        max_bytes : 单图 base64 字符上限，默认 600,000（介于实测 dpi=130 与 dpi=150 之间，
                    即默认拒绝 150dpi 整页）。超出返回 truncated=true + 降 dpi 建议，
                    不返回 data_uri。

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
                f"base64 共 {size} 字符，超上限 {max_bytes}。请降低 render_pdf_pages 的 "
                f"dpi（建议 110~130）或缩小 pages 范围；不返回 data_uri 是故意的——"
                f"整页塞进对话会把一轮任务的上下文吃光，后续轮次只能靠截断收尾"
            ),
        }
    # 不走 _out()：见 docstring，base64 是给模型的载荷，摘要化等于废掉这个工具
    return {
        "path": os.path.abspath(image_path),
        "media_type": media,
        "data_uri": f"data:{media};base64,{b64}",
        "size_bytes": size,
        "truncated": False,
        "note": "将此 data_uri 作为 image_url 的 url 字段，与文本 content 一起发给 sheng/intern-s2；一轮最多 1 张，喂完这页再进下一轮",
    }


@mcp.tool()
def expand_result(path: str, selector: str = "", fields: list[str] | None = None,
                  max_chars: int | None = None) -> dict:
    """取回被压缩工具结果的原文（页面清单、渲染图列表等，逐字未改）。

    path:     压缩信封里的 __raw_path（只允许读 ~/.gewu/mcp-raw 内的文件）。
    selector: 点号 + 下标，可叠加：`pages[12:30]`、`images[*].path`、`figure_pages`。
    注意：`data_uri` 这类字节流超大时会返回 status=too_large，只给头部和取回办法——
    模型无法从上下文里抄回十万字符 base64，需要图像请直接用 path 指向的 PNG。
    """
    return _expand(path, selector=selector, fields=fields, max_chars=max_chars, server=SERVER)


if __name__ == "__main__":
    mcp.run()
