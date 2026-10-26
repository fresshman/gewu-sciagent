"""EasyScholar 期刊等级查询 —— 反幻觉「期刊信息」溯源层。

为什么存在
----------
期刊推荐（journal-match 技能）目前只从 OpenAlex 拿 bibliometric 元数据
（works_count / cited_by_count / ISSN / 主页）。这些信息不含「期刊等级 / 分区 /
核心目录」——而这类信息恰恰是 LLM 最容易**凭记忆编造**的地方
（"该刊为中科院 1 区" / "属于 CSSCI" 往往张口就来、无法核验）。

本模块把期刊等级/分区锚定到 **EasyScholar 开放 API**（`getPublicationRank`），
返回官方数据集（officialRank: sci/ssci/中科院分区/各校自科目录…）与自定义数据集
（customRank: 用户自建分级）的权威结果。配合 sci-verify 的存在性核验（D1），
让"推荐的期刊 + 期刊等级"都来自可溯源的真实接口，不再依赖模型记忆。

凭据
----
通过环境变量 EASYSCHOLAR_SECRET_KEY 提供；未设置时回退读取本仓库内
gitignored 的本地文件 gewu/mcp/.easyscholar_key（或 ~/.openclaw/easyscholar.key）。
秘钥绝不写入任何会被提交的文件（模板 openclaw.json 仅留占位说明）。

速率限制
--------
文档要求每秒最多 2 次请求。模块级 _throttle() 保证 ~1.8 req/s。

依赖：仅 Python 标准库（urllib / json / time / os / pathlib）。
"""

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://www.easyscholar.cc/open/getPublicationRank"
# 文档要求 ≤2 req/s；取 0.55s 间隔≈1.8 req/s，留安全余量。
_MIN_INTERVAL_S = 0.55
_last_call_ts = 0.0

# rank 数字(1-5) → customRank.rankInfo 中的等级缩写键
_RANK_FIELD = {
    1: "oneRankText",
    2: "twoRankText",
    3: "threeRankText",
    4: "fourRankText",
    5: "fiveRankText",
}


def _throttle() -> None:
    """进程内限速：保证相邻两次真实请求间隔 ≥ _MIN_INTERVAL_S。"""
    global _last_call_ts
    now = time.time()
    wait = _MIN_INTERVAL_S - (now - _last_call_ts)
    if wait > 0:
        time.sleep(wait)
    _last_call_ts = time.time()


def _resolve_secret_key(explicit: str | None = None) -> str | None:
    """解析秘钥：环境变量优先，回退到 gitignored 本地文件。"""
    if explicit:
        return explicit.strip()
    env_key = os.environ.get("EASYSCHOLAR_SECRET_KEY")
    if env_key:
        return env_key.strip()
    candidates = [
        Path(__file__).resolve().parent / ".easyscholar_key",   # 仓库内 gitignored
        Path.home() / ".openclaw" / "easyscholar.key",            # 用户目录（与 live config 同区）
    ]
    for p in candidates:
        try:
            if p.exists():
                return p.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    return None


def _normalize(data: dict) -> dict:
    """把 EasyScholar 原生 data 结构整理成易读的字段。

    officialRank.all / officialRank.select：dict，字段名(如 sci/ssci/swufe/cufe)→等级。
    customRank.rankInfo：list，每个数据集含 uuid / abbName / oneRankText..fiveRankText。
    customRank.rank：list，形如 "{{uuid}}&&&{{rank(1-5)}}"，需拆出数据集与等级。
    """
    official = data.get("officialRank") or {}
    custom = data.get("customRank") or {}

    official_all = official.get("all") or {}
    official_select = official.get("select") or {}

    rank_info = custom.get("rankInfo") or []
    rank_list = custom.get("rank") or []
    info_by_uuid = {r.get("uuid"): r for r in rank_info if r.get("uuid")}

    custom_parsed = []
    for entry in rank_list:
        if not isinstance(entry, str) or "&&&" not in entry:
            continue
        uuid, rank_num = entry.split("&&&", 1)
        uuid = uuid.strip()
        rank_num = rank_num.strip()
        ds = info_by_uuid.get(uuid, {})
        abb = ds.get("abbName") or uuid
        try:
            rank_int = int(rank_num)
        except ValueError:
            rank_int = 0
        rank_field = _RANK_FIELD.get(rank_int)
        rank_text = ds.get(rank_field) if rank_field else rank_num
        custom_parsed.append(
            {"dataset": abb, "rank": rank_text, "raw_rank": rank_num}
        )

    return {
        "official_all": official_all,
        "official_select": official_select,
        "custom": custom_parsed,
    }


def format_rank_summary(data: dict) -> str:
    """把整理后的等级数据压成一行人类可读摘要，供报告/对话直接展示。"""
    parts = []
    official = data.get("official_all") or {}
    if official:
        off = " · ".join(f"{k}={v}" for k, v in official.items())
        parts.append(f"官方: {off}")
    custom = data.get("custom") or []
    if custom:
        cus = " , ".join(f"{c['dataset']}={c['rank']}" for c in custom)
        parts.append(f"自定义: {cus}")
    return " | ".join(parts) if parts else "（无等级数据）"


def query_publication_rank(
    publication_name: str,
    secret_key: str | None = None,
    timeout: float = 15.0,
) -> dict:
    """查询单本期刊的等级/分区。

    返回 dict：
      - 成功:  {"ok": True,  "data": {...}, "summary": "<一行摘要>"}
      - 失败:  {"ok": False, "error": "<原因>", "code"?: int}
    data 结构见 _normalize()。
    """
    key = _resolve_secret_key(secret_key)
    if not key:
        return {
            "ok": False,
            "error": "未提供 EasyScholar 秘钥：请设置环境变量 EASYSCHOLAR_SECRET_KEY，"
                     "或将秘钥写入 gitignored 的 gewu/mcp/.easyscholar_key。",
        }
    name = (publication_name or "").strip()
    if not name:
        return {"ok": False, "error": "publication_name 为空"}

    _throttle()
    params = urllib.parse.urlencode({"secretKey": key, "publicationName": name})
    url = f"{API}?{params}"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "gewu-sciagent/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as exc:  # 网络/超时等
        return {"ok": False, "error": f"请求 EasyScholar 失败: {exc}"}

    try:
        j = json.loads(raw)
    except Exception as exc:
        return {"ok": False, "error": f"响应解析失败: {exc}", "raw": raw[:400]}

    if j.get("code") != 200:
        return {
            "ok": False,
            "error": j.get("msg") or "未知错误",
            "code": j.get("code"),
        }

    normalized = _normalize(j.get("data") or {})
    return {
        "ok": True,
        "data": normalized,
        "summary": format_rank_summary(normalized),
    }


def query_many(publication_names: list[str], secret_key: str | None = None) -> dict:
    """批量查询（保持进程内限速）。返回 {name: result}。"""
    out = {}
    for n in publication_names:
        out[n] = query_publication_rank(n, secret_key=secret_key)
    return out
