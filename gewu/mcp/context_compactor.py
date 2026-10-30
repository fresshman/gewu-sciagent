"""MCP 工具结果的可逆压缩：摘要 + 原文落盘 + 按需回取（CCR 模式）。

为什么不是「截断」，也不是 LLMLingua 式 token 删减：
    格物的立身之处是数值可溯源。`RMSE=214.5699±25.7094` 这种串一旦被改写或被
    删 token，整条复现链就失去意义。所以本模块只做**结构化去冗**，规则是：
      · 标量（数值、短字符串）逐字保留：不四舍五入、不改写、不重排；
      · 超长的同构列表只内联前 `head` 条，其余给出可直接使用的 selector，
        并对分类型字段（status 之类）给全量 tally、数值字段给真实 min/max，
        让"判读"通常不必回取——一次回取等于一次网关往返；
      · 列表内重复的长公共前缀（如 14 个 bag 的绝对路径）提取一次、逐条去掉，
        取回时走原文，不做字符串拼接重建；
      · 原文按内容寻址落盘（文件名 = 原文哈希），`expand()` 读的就是那一份本身；
        同参重跑但内容漂移时绝不复用旧文件，否则摘要与原文就不同源了。
    代价：一次回取等于一次网关往返（实测轮次粒度 10–20s），压得太狠反而更快撞
    墙钟闸门。所以默认只处理超过 GEWU_MCP_COMPACT_LIMIT（3000 字符）的结果，
    小结果原样透出，零开销、零额外往返。

环境变量：
    GEWU_MCP_COMPACT       =0 全局关闭（调试/对照用）
    GEWU_MCP_COMPACT_LIMIT 内联上限字符数，默认 3000
    GEWU_MCP_HEAD          摘要内联的列表条数，默认 8
    GEWU_MCP_EXPAND_MAX    单次回取允许内联的最大字符数，默认 8000
    GEWU_MCP_RAW_DIR       原文落盘根目录，默认 ~/.gewu/mcp-raw
    GEWU_MCP_RAW_DAYS      原文保留天数，默认 7（每次进程首次压缩时清理）
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from typing import Any

VERSION = "gewu-ccr-v1"

# 单个超长字符串在摘要里保留的头部长
_LONG_STR_HEAD = 300
# 前缀去冗的触发门槛：列表至少这么多条，且前缀吃掉该字段总长的这么多比例
_MIN_DEDUP_ITEMS = 5
_MIN_PREFIX_CHARS = 30
_MIN_DEDUP_RATIO = 0.35
# 压缩至少得省出这么多比例，否则信封的固定开销会把收益吃掉（见 compact 的实测注释）
MIN_SAVING = 0.12

_pruned = False


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, "")).strip() or default)
    except ValueError:
        return default


def raw_root() -> str:
    return os.environ.get("GEWU_MCP_RAW_DIR", "").strip() or os.path.join(
        os.path.expanduser("~"), ".gewu", "mcp-raw"
    )


def _limit() -> int:
    return _env_int("GEWU_MCP_COMPACT_LIMIT", 3000)


def _head() -> int:
    return _env_int("GEWU_MCP_HEAD", 8)


def enabled() -> bool:
    return os.environ.get("GEWU_MCP_COMPACT", "").strip() != "0"


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


# --------------------------------------------------------------------------
# 摘要构造
# --------------------------------------------------------------------------
def _numeric_min_max(items: list[dict]) -> dict:
    """给未内联条目的数值字段一个精确的取值范围（真算自原文，非估计）。"""
    out: dict[str, dict] = {}
    if not items:
        return out
    keys = [k for k in items[0] if not isinstance(items[0][k], bool)]
    for k in keys[:8]:
        vals = [d[k] for d in items
                if isinstance(d.get(k), (int, float)) and not isinstance(d.get(k), bool)]
        if len(vals) >= 3:
            out[k] = {"min": min(vals), "max": max(vals), "n": len(vals)}
    return out


def _category_tally(items: list[dict]) -> dict[str, dict]:
    """给分类型字段（status / is_figure_page 这类）一次全量计数。

    存在的意义：像 verify_papers 这种「只关心哪几条不对劲」的结果，
    靠 tally 就能判读，不必为数 12 条未内联的条目再花一次网关往返。
    """
    out: dict[str, dict] = {}
    if not items or len(items) < 3:
        return out
    for k in items[0]:
        vals = [d.get(k) for d in items]
        if not all(isinstance(v, (str, bool)) for v in vals):
            continue
        distinct: dict[Any, int] = {}
        for v in vals:
            distinct[v] = distinct.get(v, 0) + 1
        if 1 < len(distinct) <= 6:
            out[k] = dict(sorted(distinct.items(), key=lambda kv: -kv[1]))
    return dict(list(out.items())[:4])


def _string_prefixes(items: list[dict]) -> dict[str, str]:
    """找出「每条都重复一遍」的长公共前缀——长绝对路径是这里最大的冗余来源。"""
    out: dict[str, str] = {}
    for k in items[0]:
        vals = [d[k] for d in items if isinstance(d.get(k), str)]
        if len(vals) < len(items) or len(vals) < _MIN_DEDUP_ITEMS:
            continue
        prefix = os.path.commonprefix(vals)
        total = sum(len(v) for v in vals)
        if len(prefix) >= _MIN_PREFIX_CHARS and total and len(prefix) * len(vals) / total >= _MIN_DEDUP_RATIO:
            out[k] = prefix
    return out


def _digest(value: Any, head: int) -> Any:
    if isinstance(value, dict):
        return {k: _digest(v, head) for k, v in value.items()}

    if isinstance(value, list):
        dicts = [v for v in value if isinstance(v, dict)]
        use_dedup = len(dicts) == len(value) and len(value) >= _MIN_DEDUP_ITEMS
        prefixes = _string_prefixes(dicts) if use_dedup else {}

        if len(value) <= head and not prefixes:
            return [_digest(v, head) for v in value]

        shown = [_digest(v, head) for v in value[:head]]
        if prefixes:
            for item in shown:
                if not isinstance(item, dict):
                    continue
                for k, p in prefixes.items():
                    v = item.get(k)
                    if isinstance(v, str) and v.startswith(p):
                        item[k] = v[len(p):]

        env: dict[str, Any] = {"_list": len(value), "items": shown}
        if prefixes:
            env["_prefix"] = prefixes
            env["_prefix_note"] = "被抽前缀的字段值 = 完整值去掉 _prefix 里的前缀，拼回即完整"
        if len(value) > head:
            env["more"] = "[%d:%d]" % (head, len(value))
            agg = _numeric_min_max(dicts)
            if agg:
                env["numeric_min_max"] = agg
            tally = _category_tally(dicts)
            if tally:
                env["tally"] = tally
        return env

    if isinstance(value, str) and len(value) > _LONG_STR_HEAD:
        return {"_long_str": len(value), "head": value[:_LONG_STR_HEAD],
                "note": "整段原文在 __raw_path，用 expand_result 取"}

    return value


# --------------------------------------------------------------------------
# 原文落盘
# --------------------------------------------------------------------------
def _prune(root: str) -> None:
    global _pruned
    if _pruned:
        return
    _pruned = True
    keep_after = time.time() - _env_int("GEWU_MCP_RAW_DAYS", 7) * 86400
    try:
        for day in os.listdir(root):
            d = os.path.join(root, day)
            try:
                if os.path.getmtime(d) < keep_after:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass
    except OSError:
        pass


def _raw_path(server: str, tool: str, wire: str, day: str) -> str:
    """内容寻址：文件名只由原文决定，但先不算写。

    为什么不能按 (tool, args) 命名：verify_papers 这类结果两次调用之间本身会漂移
    （实测 hallucination_rate 0.0588→0.1111），按参数命名会让第二次的 digest 指向
    第一次的原文——摘要与可回取的字节不再同源，溯源直接失效。

    只算名字不建目录不写文件：压缩可能因"省不出 MIN_SAVING"被放弃，那时不该留下水坑。
    """
    key = hashlib.sha1(wire.encode("utf-8")).hexdigest()[:12]
    safe_tool = "".join(c if c.isalnum() or c in "-_" else "_" for c in tool)[:48]
    return os.path.join(raw_root(), day,
                        f"{server}.{safe_tool}.{key}.json").replace("\\", "/")


def _ensure_raw(path: str, wire: str) -> str:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    _prune(raw_root())
    if not os.path.exists(path):  # 同内容重跑复用同一份，不无限膨胀
        with open(path, "w", encoding="utf-8") as f:
            f.write(wire)
    return path


def _envelope(payload: Any, raw_path: str, *, server: str, tool: str,
              wire_chars: int, head: int, selector_base: str = "") -> dict:
    """信封要够短：说明文字本身也进上下文，写长了就把去冗收益吃回去（实测过）。"""
    digest = _digest(payload, head)
    first_more = _first_more(payload, head)
    out = {
        "__compacted": VERSION,
        "tool": tool,
        "raw_chars": wire_chars,
        "__raw_path": raw_path,
        "expand": 'mcp__%s__expand_result(path=__raw_path, selector="%s")' % (
            server, first_more or ""),
        "digest": digest,
        "note": "digest 内数值/ID 逐字未改；原文一字不动存在 __raw_path。"
                "缺的条目用 expand 取，别凭印象补。",
    }
    if selector_base:
        out["selector_base"] = selector_base
    return out


def _first_more(payload: Any, head: int, _path: str = "", _depth: int = 0) -> str:
    """给出第一个「还没内联」的切片位置，省掉模型先探路的那次往返。"""
    if _depth > 2 or not isinstance(payload, dict):
        return ""
    for k, v in payload.items():
        p = f"{_path}.{k}" if _path else str(k)
        if isinstance(v, list) and len(v) > head:
            return f"{p}[{head}:{len(v)}]"
        if isinstance(v, dict):
            got = _first_more(v, head, p, _depth + 1)
            if got:
                return got
    return ""


# --------------------------------------------------------------------------
# 对外：压缩
# --------------------------------------------------------------------------
def compact(payload: Any, *, server: str, tool: str,
            limit: int | None = None, head: int | None = None,
            raw_path: str | None = None, selector_base: str = "") -> Any:
    """超过内联上限**且确实更省**时返回 {digest, __raw_path, expand…}，否则原样返回 payload。

    "更省"是硬条件：信封自身有固定开销（__raw_path + expand 提示 + note 约 400–500 字符）。
    实测 reproduce_fold 的 14 条逐 bag 明细只超出阈值一点点，压缩后反而从 3,128 字符
    涨到 3,219（-2.9%）。压了却更长，等于白付一次回取往返的风险，所以低于 MIN_SAVING
    直接放弃压缩、连原文都不落盘。
    """
    if not enabled():
        return payload
    wire = _dumps(payload)
    lim = _limit() if limit is None else limit
    if len(wire) <= lim:
        return payload
    h = _head() if head is None else head
    path = raw_path or _raw_path(server, tool, wire, time.strftime("%Y-%m-%d"))
    env = _envelope(payload, path, server=server, tool=tool,
                    wire_chars=len(wire), head=h, selector_base=selector_base)
    if raw_path is None and len(_dumps(env)) > len(wire) * (1 - MIN_SAVING):
        return payload  # 省不到 MIN_SAVING 就别制造信封
    _ensure_raw(path, wire)
    return env


# --------------------------------------------------------------------------
# 对外：回取
# --------------------------------------------------------------------------
def _tokenize(selector: str) -> list[tuple[str, Any]]:
    steps: list[tuple[str, Any]] = []
    s = (selector or "").strip()
    buf = ""
    i = 0
    while i < len(s):
        c = s[i]
        if c == ".":
            if buf:
                steps.append(("key", buf))
                buf = ""
            i += 1
        elif c == "[":
            if buf:
                steps.append(("key", buf))
                buf = ""
            j = s.find("]", i)
            if j < 0:
                raise ValueError("selector 解析失败：'[' 没有配对的 ']'")
            inner = s[i + 1:j].strip()
            if inner == "*":
                steps.append(("star", None))
            elif ":" in inner:
                a, b = inner.split(":", 1)
                steps.append(("slice", (int(a) if a.strip() else None,
                                        int(b) if b.strip() else None)))
            else:
                steps.append(("index", int(inner)))
            i = j + 1
        else:
            buf += c
            i += 1
    if buf:
        steps.append(("key", buf))
    return steps


def _select(node: Any, steps: list) -> Any:
    if not steps:
        return node
    kind, arg = steps[0]
    rest = steps[1:]
    if kind == "key":
        if isinstance(node, list):
            # jq 式映射：val_bags[0:2].bag_id 取的是每条的 bag_id
            return [_select(item, steps) for item in node]
        if not isinstance(node, dict):
            raise TypeError(f"'{arg}' 的父节点不是对象，而是 {type(node).__name__}")
        if arg not in node:
            raise KeyError(f"找不到键 '{arg}'，可选键：{list(node)[:20]}")
        return _select(node[arg], rest)
    if kind == "index":
        if not isinstance(node, list):
            raise TypeError(f"[{arg}] 的父节点不是数组")
        return _select(node[arg], rest)
    if kind == "slice":
        if not isinstance(node, list):
            raise TypeError(f"[{arg[0]}:{arg[1]}] 的父节点不是数组")
        return _select(node[arg[0]:arg[1]], rest)
    if kind == "star":
        if not isinstance(node, list):
            raise TypeError("[*] 的父节点不是数组")
        return [_select(item, rest) for item in node]
    raise TypeError("selector 解析失败")


def expand(path: str, selector: str = "", fields: list[str] | None = None,
           max_chars: int | None = None, server: str = "gewu") -> dict:
    """按 __raw_path 取回落盘原文（或其切片）。落盘文件本身不改，所以取回即原文。"""
    if not path or not str(path).strip():
        return {"status": "error", "detail": "path 不能为空（用压缩结果里的 __raw_path）"}

    root = os.path.realpath(raw_root())
    source = os.path.realpath(str(path).strip().replace("\\", "/"))
    if source != root and not source.startswith(root + os.sep):
        return {"status": "error",
                "detail": f"只允许读取落盘目录内的文件：{root}",
                "requested": source}
    if not os.path.exists(source):
        return {"status": "error",
                "detail": "落盘原文不存在（可能已过期清理），请重新调用原工具",
                "path": source.replace("\\", "/")}
    target = source.replace("\\", "/")
    try:
        with open(source, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return {"status": "error", "detail": f"读取失败：{e}", "path": target}

    try:
        value = _select(data, _tokenize(selector))
    except (KeyError, IndexError, TypeError, ValueError) as e:
        return {"status": "error", "detail": f"selector '{selector}' 取不到：{e}", "path": target}

    if fields and isinstance(value, list):
        value = [{k: it.get(k) for k in fields} if isinstance(it, dict) else it for it in value]

    cap = _env_int("GEWU_MCP_EXPAND_MAX", 8000) if max_chars is None else int(max_chars)

    # 单个超长字符串（base64 data_uri、整页正文）：再压一层也没人能从上下文里
    # 抄回十万字符，所以直接给头部 + 用脚本取原文的说明，而不是假装可以回取。
    if isinstance(value, str) and len(value) > cap:
        return {
            "status": "too_large",
            "chars": len(value),
            "from": target,
            "selector": selector,
            "head": value[:min(cap, 400)],
            "howto": "这种字节流不能靠读上下文搬运（模型抄不回十万字符）。"
                     "请让脚本/代码直接从 from 指向的文件里取该字段，"
                     "或把原始文件路径交给下游（图片本身就有 path 字段）。",
        }

    wire = _dumps(value)
    if len(wire) <= cap:
        return {"status": "ok", "selector": selector or "(整份原文)",
                "chars": len(wire), "from": target, "value": value}

    # 切片仍然太大 → 再压一层（指向同一份原文，selector 可继续叠加），不截字节。
    recompact = compact(value, server=server, tool=f"expand[{selector}]",
                        limit=cap, head=max(3, _head() // 2),
                        raw_path=target, selector_base=selector or "")
    if "__compacted" not in recompact:
        recompact = {"status": "ok", "selector": selector, "chars": len(wire),
                     "from": target, "value": value}
    else:
        recompact["note"] = ("这次取回的切片仍超过 %d 字符，已再压一层；"
                             "__raw_path 仍是同一份原文，selector 可以继续叠加。" % cap)
    return recompact
