"""多模态科学数据解析 MCP Server（书生 InternVL / 原页渲染）。

两层能力：
1) 视觉解析：parse_figure 调用书生视觉模型（internvl3.5-241b-a28b）把科学图
   （谱图/曲线/柱状/显微图/分子式）读成结构化 JSON，走 OpenAI 兼容接口。
2) 原页渲染：render_pdf_pages 把论文 PDF 渲染成 PNG，交给书生 intern-s2 做
   科学多模态原页理解（图+表+公式同帧联合推理）。image_to_data_uri 把 PNG
   转 base64 data URI，供 Agent 以 image_url 直接发给 sheng/intern-s2。

两者的分工（别混）：原页理解走 intern-s2 直读，不经过本模型的文本化中转；
parse_figure 只在「要把一张图定量抽成数」时用（峰位、曲线范围、柱高），
因为那是谱图数字化任务，不是版面理解任务。
"""
import base64
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
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

# ── InternVL 视觉解析后端（parse_figure 用）───────────────────────────────────
# 与 ~/.openclaw/openclaw.json 的 sheng provider 同一入口：baseUrl 必须是 chat. 域
# （误用 internlm.intern-ai.org.cn/api/v1 会 404，见模板 §1 注释）。
VL_DEFAULT_BASE_URL = "https://chat.intern-ai.org.cn/api/v1"
VL_DEFAULT_MODEL = "internvl3.5-241b-a28b"
VL_DEFAULT_TIMEOUT_S = 180
# 硬夹取上限。为什么必须有：sci-data 的客户端闸门 requestTimeoutMs=600000（见配置模板），
# 内层 HTTP 若允许跑到 600s，模型拿到的是 `-32001 Request timed out` 而不是我们的降级建议，
# 优雅降级被截胡（2026-10-28 就是这么烧掉一整轮阶段的）。
VL_TIMEOUT_CEILING_S = 480
# 单图 base64 字符上限，与 image_to_data_uri 的默认闸同值（dpi≤130 整页 ≈57 万字符）。
VL_DEFAULT_MAX_B64 = 600_000

# 输出契约：字段读不到就填 null / 空数组，禁止用先验补数值——这是反幻觉的落点，
# 也是本工具与"看起来成功了"的占位实现的区别。
_VL_OUTPUT_SCHEMA = """{
  "modality": "spectrum|curve|bar|scatter|micrograph|molecule|table|diagram|photo|unknown",
  "title": "图上读到的题名/图注，读不到填 null",
  "x_axis": {"label": "", "unit": "", "min": null, "max": null},
  "y_axis": {"label": "", "unit": "", "min": null, "max": null},
  "series": [{"name": "图例原文", "style": "颜色/线型", "trend": "", "value_min": null, "value_max": null}],
  "peaks": [{"position": null, "unit": "", "intensity": null, "label_in_figure": ""}],
  "key_numbers": [{"value": "图上原样的位数", "meaning": "", "where_in_figure": "在图的哪个位置"}],
  "text_in_figure": ["图内每一处可读文字，逐条原样抄"],
  "unreadable": "哪些刻度/区域读不清；没有则空字符串",
  "confidence": "high|medium|low"
}"""

_VL_SYSTEM = (
    "你是科学仪器谱图与图表的读数员。规则（违反任何一条都算失败）：\n"
    "1) 只写这张图里直接可见的内容。图上看不到的一律填 null 或空数组，"
    "禁止用领域常识、元素表、典型谱线来补全数值。\n"
    "2) 数值保持图上印出的位数与单位，不要四舍五入、不要换算、不要自己算差值。\n"
    "3) 需要估读的点（没有刻度标注支撑）必须在 label_in_figure 或 meaning 里写明"
    "「估读」，不得伪装成图上标值。\n"
    "4) 只输出一个 JSON 对象，不要 markdown 代码块、不要任何解释文字。\n"
    "5) 输出结构严格如下（键名不得增删改）：\n" + _VL_OUTPUT_SCHEMA
)


def _vl_key() -> tuple[str, str]:
    """返回 (可用 Key, 不可用原因)。

    为什么还要判 `${`：openclaw 会把配置里的 `${VAR}` 按它自己的环境解析，未设置时
    可能原样留着——那串东西当 Bearer 发出去只会收到 401，不如在这里就说清是配置问题。
    """
    key = (os.environ.get("INTERN_API_KEY") or "").strip()
    if not key:
        return "", "missing"
    if "${" in key:
        return "", "unresolved"
    return key, ""


def _vl_env(name: str, default: str) -> str:
    """环境变量在调用时读，不在 import 时读——MCP 进程可能被复用，配置改了要生效。"""
    return (os.environ.get(name) or "").strip() or default


def _env_int(name: str, default: int) -> int:
    """整型环境变量，写坏时用默认值并把坏值说清楚（不静默吞掉）。"""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _vl_extract_json(text: str) -> tuple[dict | None, str]:
    """从模型回复里取出 JSON 对象。返回 (对象, 错误串)。

    容错只做两件：剥掉 ```json 围栏、退一步找最外层花括号。不做"尽量救一下"的
    宽松解析——救回来的半截结构会被下游当成读数，那正是本项目要防的事。
    """
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw), ""
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1]), ""
        except json.JSONDecodeError as e:
            return None, f"JSON 解析失败：{e}"
    return None, "回复里找不到 JSON 对象"


def _vl_complete(body: dict, timeout: int) -> tuple[dict | None, str, str]:
    """一次 OpenAI 兼容 chat/completions 调用，返回 (响应 JSON, 错误类别, 错误详情)。

    类别是机器可读的（""/timeout/http_error/network/bad_json），调用方靠它选降级话术——
    不去嗅探错误字符串里有没有 "timeout"，那种判定在中文报错上会静默失效。
    拆成独立函数是为了单测能注入假传输层。绝不把 Key 写进任何返回值。
    """
    key, _ = _vl_key()
    url = _vl_env("GEWU_VL_BASE_URL", VL_DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:400]
        except Exception:  # noqa: BLE001 - 读错误体失败不影响主结论
            pass
        return None, "http_error", f"HTTP {e.code} {detail}".strip()
    except (TimeoutError, socket.timeout):
        return None, "timeout", f"请求超时（{timeout}s 内未返回）"
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower():
            return None, "timeout", f"请求超时（{timeout}s 内未返回）：{reason}"
        return None, "network", f"网络失败：{reason}"
    except OSError as e:
        return None, "network", f"网络失败：{e}"
    try:
        return json.loads(raw), "", ""
    except json.JSONDecodeError:
        return None, "bad_json", f"响应不是合法 JSON：{raw[:300]}"


def _encode_for_vl(image_path: str, max_b64: int) -> tuple[str, str, int, str]:
    """(data_uri, media_type, base64 字符数, 错误串)。"""
    ext = Path(image_path).suffix.lower()
    media = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(ext, "image/png")
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    if len(b64) > max_b64:
        return "", media, len(b64), (
            f"base64 共 {len(b64)} 字符，超上限 {max_b64}。先裁到目标子图或降 dpi"
            f"（render_pdf_pages 用 dpi=110~130、pages 只给含图页），"
            f"确需整页再显式放大 max_b64"
        )
    return f"data:{media};base64,{b64}", media, len(b64), ""


@mcp.tool()
def parse_figure(image_path: str, question: str = "", max_b64: int = 0) -> dict:
    """用书生 InternVL3.5 把科学图（谱图/曲线/柱状/显微图/分子式）读成结构化 JSON。

    定位：这是「把一张图定量抽成数」的谱图数字化工具，不是版面理解工具——
    读论文原页请用 render_pdf_pages + image_to_data_uri 交给 intern-s2 直读。

    前置：本进程环境里要有 INTERN_API_KEY。实测 openclaw 起 stdio MCP 子进程只给一个
    15 键的环境白名单，网关 export 的变量不透传，所以 Key 必须写在配置的
    mcp.servers.sci-data.env 里——用 scripts/bootstrap_openclaw_config.py --intern-api-key
    一条命令注入（产物在仓库外）。拿不到 Key 时本工具返回 status=missing_key 并给出修法，
    不猜、不编。

    Args:
        image_path: 图片路径（本地绝对/相对）。
        question  : 可选，追加的具体问题（如「只读 400-500nm 区间的峰位」）。
        max_b64   : 可选，单图 base64 字符上限，0=用 GEWU_VL_MAX_B64 或默认 600000。

    Returns:
        status=ok 时：{status, modality, figure(结构化读数), model, latency_s,
                      usage, path, image_base64_chars, warning?}
        其它：{status, error, hint, path}——任何降级都不返回 figure，
              避免调用方把失败读成一次真实读数。
    """
    image_path = os.path.expanduser(image_path)
    if not os.path.isfile(image_path):
        return {"status": "file_not_found", "error": f"图片不存在: {image_path}", "path": image_path}

    ceiling = int(max_b64) if int(max_b64 or 0) > 0 else _env_int("GEWU_VL_MAX_B64", VL_DEFAULT_MAX_B64)
    uri, media, n_chars, err = _encode_for_vl(image_path, ceiling)
    if err:
        return {
            "status": "too_large",
            "error": err,
            "path": os.path.abspath(image_path),
            "media_type": media,
            "image_base64_chars": n_chars,
        }

    key, key_reason = _vl_key()
    if not key:
        return {
            "status": "missing_key",
            "error": (
                "MCP 子进程环境里没有可用的 INTERN_API_KEY，无法调用书生视觉模型。"
                if key_reason == "missing"
                else "INTERN_API_KEY 还是未解析的 ${...} 引用，等于没有 Key。"
            ),
            "hint": (
                "实测：openclaw 起 stdio MCP 子进程只给 15 个键的环境白名单（PATH/TEMP/USERPROFILE…），"
                "网关自己 export 的变量不会透传进来，所以只在 shell 里 export 是不够的。"
                "正确做法：python scripts/bootstrap_openclaw_config.py --intern-api-key sk-xxx --write"
                "（它把 Key 写进产物里 mcp.servers.sci-data.env，产物在 ~/.openclaw/ 下、不进仓库），"
                "然后树杀网关再起 bash start-gewu.sh --gateway 让子进程重读配置。"
            ),
            "path": os.path.abspath(image_path),
        }

    model = _vl_env("GEWU_VL_MODEL", VL_DEFAULT_MODEL)
    timeout = min(_env_int("GEWU_VL_TIMEOUT_S", VL_DEFAULT_TIMEOUT_S), VL_TIMEOUT_CEILING_S)
    user_text = "请按规则输出这张图的 JSON。"
    if question.strip():
        user_text += f"\n额外要求：{question.strip()}"
    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _VL_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": uri}},
                ],
            },
        ],
    }

    t0 = time.time()
    resp, err_kind, err_msg = _vl_complete(body, timeout)
    latency = round(time.time() - t0, 2)
    if resp is None:
        hints = {
            "timeout": (
                f"模型 {model} 未在 {timeout}s 内返回：缩小图片范围或调 GEWU_VL_TIMEOUT_S"
                f"（上限 {VL_TIMEOUT_CEILING_S}s，必须留在 sci-data 的 600s 客户端闸门之下）"
            ),
            "http_error": "确认 baseUrl 是 chat.intern-ai.org.cn/api/v1、Key 有效、模型 ID 在 provider 列表里",
            "network": "本机到书生 API 不通：检查网络/代理，或稍后重试",
            "bad_json": "网关返回的不是 JSON，可能被代理或登录页拦截",
        }
        return {
            "status": err_kind or "http_error",
            "error": err_msg,
            "hint": hints.get(err_kind, hints["http_error"]),
            "path": os.path.abspath(image_path),
            "latency_s": latency,
        }

    choices = resp.get("choices") or []
    content = ((choices[0].get("message") or {}).get("content") if choices else "") or ""
    if not content.strip():
        return {
            "status": "empty_response",
            "error": "模型返回空内容",
            "raw_response_head": json.dumps(resp, ensure_ascii=False)[:400],
            "path": os.path.abspath(image_path),
            "latency_s": latency,
        }

    figure, parse_err = _vl_extract_json(content)
    if figure is None:
        return {
            "status": "unparsable",
            "error": parse_err,
            "hint": "模型没按契约输出 JSON。重试并在 question 里收窄要求，或换 GEWU_VL_MODEL",
            "model": model,
            # 只回头部：整段原文交给瘦身层落盘，但这里连头部都不该长——真长了就是模型跑偏
            "reply_head": content[:1200],
            "path": os.path.abspath(image_path),
            "latency_s": latency,
        }

    usage = resp.get("usage") or {}
    payload = {
        "status": "ok",
        "path": os.path.abspath(image_path),
        "media_type": media,
        "image_base64_chars": n_chars,
        "model": model,
        "latency_s": latency,
        "usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens") if k in usage},
        "modality": figure.get("modality", "unknown"),
        "figure": figure,
        "warning": (
            "视觉读数可能误认末位数字与刻度位数（本机实测过的风险）。"
            "关键数值请与正文表格或原始数据文件二次对照，不要单独采信。"
        ),
    }
    return _out(payload, "parse_figure")


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
