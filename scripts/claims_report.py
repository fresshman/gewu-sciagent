#!/usr/bin/env python3
"""D2 引擎的命令行包装：把一份 claims.json 送进 claim_provenance.py，输出逐条核验结果。

为什么不让 Node 自己再判一遍：
  「假绿」就是这么来的 —— 前端以前只看 `source` 字段非空就当「已核」，于是 12 条
  实测 0 条可核的声明在论文库里挂着绿色徽章。两套实现必然漂移，而且漂移方向总是
  更宽松那一边。所以这里只做透传，判定权唯一归引擎。

用法：
  python scripts/claims_report.py <claims.json> [--refs <refs_verified.json>]

退出码：0 正常输出 JSON；2 输入不可用（文件缺失/不是数组），JSON 里带 reason。
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gewu", "mcp"))

import claim_provenance as cp  # noqa: E402


def _load_claims(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict):
        raw = raw.get("claims") or []
    if not isinstance(raw, list):
        raise ValueError("claims.json 既不是数组，也没有 claims 数组")
    return [c for c in raw if isinstance(c, dict)]


def _verified_papers(claims_path: str, explicit: str | None) -> list[str]:
    """paper: 类溯源需要 D1 已核验集合。

    不自动拿的话，已核文献会被判成 paper_unverified —— 那是把「没查」说成「不可信」，
    同样是假状态。所以默认读同目录的 refs_verified.json。
    """
    cand = explicit or os.path.join(os.path.dirname(claims_path), "refs_verified.json")
    if not os.path.exists(cand):
        return []
    try:
        with open(cand, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    items = data.get("items") or data.get("refs") or (data if isinstance(data, list) else [])
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if str(it.get("status", "")).lower() in ("verified", "ok", "pass"):
            for k in ("id", "key", "citekey"):
                if it.get(k):
                    out.append(str(it[k]))
                    break
    return out


def main(argv: list[str]) -> int:
    # Windows 控制台默认 cp936，中文 reason 直接抛 UnicodeEncodeError
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        print(json.dumps({"available": False, "reason": "缺少 claims.json 路径"}, ensure_ascii=False))
        return 2

    claims_path = args[0]
    refs = None
    if "--refs" in argv:
        i = argv.index("--refs")
        if i + 1 < len(argv):
            refs = argv[i + 1]

    if not os.path.exists(claims_path):
        print(json.dumps({"available": False, "reason": f"找不到 {claims_path}"}, ensure_ascii=False))
        return 2

    try:
        claims = _load_claims(claims_path)
    except (OSError, ValueError) as e:
        print(json.dumps({"available": False, "reason": f"读取失败：{e}"}, ensure_ascii=False))
        return 2

    verified = _verified_papers(claims_path, refs)
    rep = cp.verify_claims(claims, verified_papers=verified)
    rep.update({
        "available": True,
        "path": claims_path.replace("\\", "/"),
        "verified_papers": verified,
        "n_with_source": sum(1 for c in claims if c.get("source")),
    })
    print(json.dumps(rep, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
