"""tectonic 获取脚本（``scripts/fetch_tectonic.py``）的逻辑测试。

分成两类：
* **纯逻辑**（资产选择、digest 解析、期望值来源决策、哈希校验、解压）——不联网、不装东西，
  始终可跑，保证「校验到底有没有做」这件事本身被验证过；
* **联网安装**——挂 ``needs_network``，默认跳过，避免把 CI/评委机器拖进 20 MB 下载。
  真跑一次的命令写在文件末尾注释里。
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import fetch_tectonic as F  # noqa: E402


# --------------------------------------------------------------------------
# 资产选择：不支持的组合必须报错，不能猜一个下载
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "plat,machine,expect",
    [
        ("win32", "AMD64", "x86_64-pc-windows-msvc.zip"),
        ("darwin", "x86_64", "x86_64-apple-darwin.tar.gz"),
        ("darwin", "arm64", "aarch64-apple-darwin.tar.gz"),
        ("linux", "x86_64", "x86_64-unknown-linux-musl.tar.gz"),
        ("linux", "aarch64", "aarch64-unknown-linux-musl.tar.gz"),
    ],
)
def test_select_asset_per_platform(plat: str, machine: str, expect: str) -> None:
    got = F.select_asset("0.17.0", plat=plat, machine=machine)
    assert got == f"tectonic-0.17.0-{expect}"


def test_select_asset_strips_v_prefix() -> None:
    assert "0.17.0" in F.select_asset("v0.17.0", plat="linux", machine="x86_64")
    assert "v0.17" not in F.select_asset("v0.17.0", plat="linux", machine="x86_64")


@pytest.mark.parametrize(
    "plat,machine",
    [("win32", "aarch64"), ("darwin", "riscv64"), ("linux", "s390x"), ("freebsd", "x86_64")],
)
def test_select_asset_rejects_unsupported(plat: str, machine: str) -> None:
    with pytest.raises(F.FetchError):
        F.select_asset("0.17.0", plat=plat, machine=machine)


# --------------------------------------------------------------------------
# digest 解析：宁可返回 None 也不猜
# --------------------------------------------------------------------------
def test_parse_digest_ok() -> None:
    v = "f" * 64
    assert F.parse_digest(f"sha256:{v}") == v
    assert F.parse_digest(f"SHA256:{v.upper()}") == v
    # 裸 64 位 hex 无歧义（SHA-512 为 128 位、SHA-1 为 40 位），应接受
    assert F.parse_digest(v) == v


@pytest.mark.parametrize(
    "raw",
    [None, "", "sha256:", "md5:" + "a" * 32, "sha256:abc", "sha256:" + "g" * 64,
     "sha512:" + "a" * 128, "a" * 40],
)
def test_parse_digest_rejects_bad(raw) -> None:
    assert F.parse_digest(raw) is None


def test_resolve_expected_refuses_silent_downgrade() -> None:
    """API 给了值但解析不了时必须报错，不能悄悄用钉住表冒充校验通过。"""
    with pytest.raises(F.FetchError) as ei:
        F.resolve_expected("md5:" + "a" * 32, next(iter(F.PINNED_DIGESTS)))
    assert "无法识别" in str(ei.value)


# --------------------------------------------------------------------------
# 期望值来源决策：优先级与「拿不到就拒绝」
# --------------------------------------------------------------------------
def test_resolve_expected_priority() -> None:
    api = "a" * 64
    usr = "b" * 64
    pinned_name = next(iter(F.PINNED_DIGESTS))

    # 用户显式 > API > 钉住
    assert F.resolve_expected(api, pinned_name, explicit=usr)["source"] == "user"
    assert F.resolve_expected(api, pinned_name)["source"] == "github_api_digest"
    assert F.resolve_expected(None, pinned_name)["source"] == "pinned"
    assert F.resolve_expected(None, "unknown-asset.zip")["source"] == "none"
    assert F.resolve_expected(None, "unknown-asset.zip")["sha256"] is None


def test_resolve_expected_rejects_bad_explicit() -> None:
    with pytest.raises(F.FetchError):
        F.resolve_expected(None, "x.zip", explicit="not-a-hash")


def test_resolve_expected_note_is_honest() -> None:
    """两种来源都必须自我说明可信度，不能让人误读为「发布方已担保」。"""
    api = F.resolve_expected("c" * 64, "x.zip")
    assert api["source"] == "github_api_digest"
    assert "不是签名" in api["note"], "同源 digest 必须声明不等于签名"

    pin = F.resolve_expected(None, next(iter(F.PINNED_DIGESTS)))
    assert pin["source"] == "pinned"
    assert "非第三方独立验证" in pin["note"], "钉住表不得被描述为独立验证"


# --------------------------------------------------------------------------
# 文件校验
# --------------------------------------------------------------------------
def _write(p: Path, data: bytes) -> str:
    p.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_verify_file_pass_and_record(tmp_path: Path) -> None:
    p = tmp_path / "a.bin"
    sha = _write(p, b"hello tectonic")
    r = F.verify_file(p, sha, expected_size=p.stat().st_size)
    assert r == {"verified": True, "sha256": sha, "bytes": p.stat().st_size}


def test_verify_file_mismatch_raises_with_both_values(tmp_path: Path) -> None:
    p = tmp_path / "a.bin"
    actual = _write(p, b"hello")
    with pytest.raises(F.FetchError) as ei:
        F.verify_file(p, "0" * 64)
    msg = str(ei.value)
    assert "0" * 64 in msg and actual in msg, "报错必须同时给出期望值与实际值"


def test_verify_file_size_mismatch_raises(tmp_path: Path) -> None:
    p = tmp_path / "a.bin"
    sha = _write(p, b"hello")
    with pytest.raises(F.FetchError) as ei:
        F.verify_file(p, sha, expected_size=999)
    assert "大小不符" in str(ei.value)


def test_verify_file_without_expected_is_explicitly_unverified(tmp_path: Path) -> None:
    p = tmp_path / "a.bin"
    _write(p, b"hello")
    r = F.verify_file(p, None)
    assert r["verified"] is False, "没有期望值时不得声称已校验"


# --------------------------------------------------------------------------
# 解压：只取那一个可执行文件
# --------------------------------------------------------------------------
def test_extract_binary_from_zip(tmp_path: Path) -> None:
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("tectonic-0.17.0/tectonic.exe", b"BINARY")
        zf.writestr("tectonic-0.17.0/README.md", b"docs")
    assert F.extract_binary(z) == b"BINARY"


def test_extract_binary_from_targz(tmp_path: Path) -> None:
    t = tmp_path / "a.tar.gz"
    with tarfile.open(t, "w:gz") as tf:
        data = b"BINARY"
        info = tarfile.TarInfo("tectonic-0.17.0/tectonic")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    assert F.extract_binary(t) == b"BINARY"


def test_extract_binary_missing_raises(tmp_path: Path) -> None:
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("something.txt", b"x")
    with pytest.raises(F.FetchError):
        F.extract_binary(z)


def test_extract_binary_rejects_non_archive(tmp_path: Path) -> None:
    p = tmp_path / "a.bin"
    p.write_bytes(b"not an archive")
    with pytest.raises(F.FetchError):
        F.extract_binary(p)


# --------------------------------------------------------------------------
# 安装位置与 --check-only
# --------------------------------------------------------------------------
def test_default_dest_matches_engine_probe_contract() -> None:
    """安装目录必须落在 latex_build 的常见探测路径内，否则装完也探测不到。"""
    from gewu import latex_build

    dest = F.default_dest()
    assert dest.name == "tools" and dest.parent.name == "gewu"
    if sys.platform.startswith("win"):
        probed = latex_build._expand(r"%LOCALAPPDATA%\gewu\tools\tectonic.exe")
        assert str(dest / "tectonic.exe") == probed


def test_check_only_does_not_touch_disk(tmp_path: Path) -> None:
    r = F.run(version=None, dest=tmp_path / "nope", force=False, allow_unverified=False,
              expect_sha256=None, archive=None, timeout=5, check_only=True, quiet=True)
    assert r["action"] == "check"
    assert r["exists"] is False
    assert not (tmp_path / "nope").exists()


def test_main_refuses_when_no_checksum_available(tmp_path: Path, capsys) -> None:
    """无版本、无显式校验值的本地包：必须退出码 1，且不留下二进制。"""
    z = tmp_path / "renamed.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("tectonic.exe", b"x" * 2048)
    dest = tmp_path / "inst"
    rc = F.main(["--archive", str(z), "--dest", str(dest), "--quiet"])
    assert rc == 1
    assert not (dest / "tectonic.exe").exists()
    assert "无法获得可校验的 sha256" in capsys.readouterr().err


def test_main_json_reports_error(tmp_path: Path, capsys) -> None:
    z = tmp_path / "renamed.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("tectonic.exe", b"x" * 2048)
    rc = F.main(["--archive", str(z), "--dest", str(tmp_path / "i"), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1 and out["ok"] is False and "无法获得" in out["error"]


def test_main_missing_archive_fails(tmp_path: Path, capsys) -> None:
    rc = F.main(["--archive", str(tmp_path / "absent.zip"), "--dest", str(tmp_path / "i"),
                 "--expect-sha256", "a" * 64, "--quiet"])
    assert rc == 1
    assert "不存在" in capsys.readouterr().err


# --------------------------------------------------------------------------
# 联网安装（默认跳过）
# --------------------------------------------------------------------------
@pytest.mark.skipif(
    not __import__("os").environ.get("GEWU_TEST_FETCH"),
    reason="联网安装会下载 20 MB 二进制；设 GEWU_TEST_FETCH=1 才跑（真实验证见 docs/verification/2026-11-09-pdf-pipeline.md）",
)
def test_real_fetch_installs_and_verifies(tmp_path: Path) -> None:
    r = F.run(version="0.17.0", dest=tmp_path / "tools", force=False, allow_unverified=False,
              expect_sha256=None, archive=None, timeout=180, check_only=False, quiet=True)
    assert r["ok"] and r["action"] == "installed"
    assert r["integrity"]["verified"] is True
    assert r["integrity"]["source"] in ("github_api_digest", "pinned")
    assert Path(r["exe"]).is_file()
    assert "0.17.0" in r["version_output"]
