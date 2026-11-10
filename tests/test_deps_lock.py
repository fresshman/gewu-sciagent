"""依赖版本锁测试。

锁最容易变成摆设的两种方式：
  1. 锁里写的是区间（`numpy>=1.26`）—— 那根本不是锁；
  2. 改了 requirements.txt 却不重生成锁 —— 锁与实际装的东西脱钩（「假锁定」）。
本文件分别用 `test_every_line_is_pinned` 与 `test_lock_is_not_stale` 盯住这两条。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import lock_deps as L  # noqa: E402

LOCK = os.path.join(ROOT, "requirements.lock.txt")
REQ = os.path.join(ROOT, "requirements.txt")


def test_lock_exists():
    assert os.path.isfile(LOCK), "缺 requirements.lock.txt：跑 python scripts/lock_deps.py"


def test_every_line_is_pinned():
    """锁里每一行都必须 `name==version`；出现区间或裸包名就是假锁。"""
    bad = []
    with open(LOCK, encoding="utf-8") as f:
        for i, raw in enumerate(f, 1):
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            if "==" not in line:
                bad.append(f"{i}: {line}")
    assert bad == [], f"这些行不是精确版本：{bad}"


def test_all_top_level_requirements_are_pinned():
    tops = L.parse_requirements(REQ)
    assert len(tops) >= 8, "requirements.txt 解析异常（顶层依赖太少）"
    lock = L.parse_lock(LOCK)
    missing = [t["name"] for t in tops if t["key"] not in lock]
    assert missing == [], f"顶层依赖未锁：{missing}"


def test_lock_is_not_stale():
    """requirements.txt 的哈希必须与锁里记录的一致 —— 改了依赖没重生成锁就失败。"""
    import hashlib
    want = hashlib.sha256(open(REQ, "rb").read()).hexdigest()
    meta = L.lock_meta(LOCK)
    assert meta.get("requirements.txt sha256") == want, (
        "锁已过期：requirements.txt 变了但锁没重生成。请跑 python scripts/lock_deps.py"
    )


def test_lock_satisfies_documented_constraints():
    """mcp 必须 <2（2.x 移除了 FastMCP，导入即失败）。这类约束要真的被锁满足。"""
    lock = L.parse_lock(LOCK)
    tops = {t["key"]: t for t in L.parse_requirements(REQ)}
    assert "mcp" in tops and tops["mcp"]["spec"], "requirements.txt 里 mcp 应带版本约束"
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version
    assert SpecifierSet(tops["mcp"]["spec"]).contains(Version(lock["mcp"])), (
        f"锁里 mcp=={lock['mcp']} 不满足 {tops['mcp']['spec']}"
    )


def test_check_reports_no_static_problem():
    """check() 的静态部分（覆盖/格式/过期）必须干净；环境漂移只算警告。"""
    L._warnings.clear()
    assert L.check(strict_env=False) == []
    # 环境漂移必须是警告而非静默：本机若与锁一致则警告为空，这里只断言类型
    assert isinstance(L._warnings, list)


def test_missing_lock_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOCK", str(tmp_path / "nope.txt"))
    problems = L.check()
    assert problems and "不存在" in problems[0]


def test_stale_lock_is_detected(tmp_path, monkeypatch):
    """把锁头哈希改成别的值，check 必须报「锁已过期」。"""
    text = open(LOCK, encoding="utf-8").read()
    fake = text.replace(L.lock_meta(LOCK)["requirements.txt sha256"], "0" * 64)
    p = tmp_path / "lock.txt"
    p.write_text(fake, encoding="utf-8")
    monkeypatch.setattr(L, "LOCK", str(p))
    problems = L.check()
    assert any("锁已过期" in x for x in problems)


@pytest.mark.parametrize("raw,expect", [
    ("PyMuPDF==2.1", "pymupdf"),
    ("scikit_learn==1.9", "scikit-learn"),
    ("numpy==2.5", "numpy"),
])
def test_name_normalization(raw, expect):
    assert L.normalize(raw.split("==")[0]) == expect


def test_requirements_parser_ignores_comments_and_options():
    tops = L.parse_requirements(REQ)
    assert all(t["raw"] and not t["raw"].startswith("#") for t in tops)
    assert all("[" not in t["key"] for t in tops)
