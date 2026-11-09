#!/usr/bin/env python3
"""一键获取单文件 LaTeX 引擎 tectonic：下载 → 校验 → 解压 → 安装 → 功能自检。

为什么需要它
------------
`gewu/latex_build.py` 能在有引擎时把 `.tex` 编成 PDF，但**不含获取引擎的能力**：
评委克隆仓库后若本机没有 TeX（Windows 上很常见），只能翻阅已入库的 `docs/paper/*.pdf`，
想自己重编就得手动去 GitHub 找发行包、解压、放到约定目录。本脚本把这段手工流程
压缩成一条命令，并让「下载来的二进制是否可信」这件事**有据可查**，而不是默认相信。

校验策略（如实说明能力边界，不夸大）
------------------------------------
1. 首选 **GitHub Releases API 的 ``asset.digest``**（形如 ``sha256:f61ce5...``）。
   注意：该 digest 与下载包同源于 GitHub，能发现**传输损坏、版本/资产错配、
   资产在发布后被替换**，但它**不是签名**，不构成对「GitHub 账号本身被攻破」的防护。
2. API 不可达（断网、限流）时回退到脚本内的**钉住表** ``PINNED_DIGESTS``。
   该表是采集时的发布方声明值缓存，作用是「断网时仍能拒绝被替换的资产」；
   其中 Windows 包另经本机实下载复算一致。钉住表**不是第三方独立验证**。
3. 两者都拿不到时不静默放行：默认拒绝安装；确需安装须显式 ``--allow-unverified``，
   结果里 ``integrity.verified=false``，并在交付说明中写明。
4. 安装后做**功能自检**：实际执行 ``tectonic --version``，版本号必须与请求版本一致，
   再调用项目自己的 ``find_engine()`` 确认能被探测到——「文件放下了」不等于「能用」。

用法
----
    python scripts/fetch_tectonic.py                  # 装最新版到用户级目录
    python scripts/fetch_tectonic.py --version 0.17.0 # 钉版本（推荐，可复现）
    python scripts/fetch_tectonic.py --check-only     # 只体检，不联网不写入
    python scripts/fetch_tectonic.py --json           # 机器可读结果

退出码：0 成功（含「已存在且可用」）；1 失败（含校验不通过）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

RELEASES_REPO = "tectonic-typesetting/tectonic"
_API_LATEST = f"https://api.github.com/repos/{RELEASES_REPO}/releases/latest"
_API_TAG = f"https://api.github.com/repos/{RELEASES_REPO}/releases/tags/"
_UA = "gewu-fetch-tectonic/1.0 (+https://github.com/FreeBlank)"
_MAX_BYTES = 300 * 1024 * 1024  # 上限，防异常响应把磁盘写满

# 钉住表：断网/限流时的兜底期望值。
# 采集方式 = GitHub Releases API 的 asset.digest 字段（2026-11-09 读取）。
# 仅 windows-msvc 一项另经本机实下载（21,060,223 B）复算一致，
# 其余平台未在本机下载，属「发布方声明值的缓存」，用于防资产被替换，非独立验证。
PINNED_DIGESTS = {
    "tectonic-0.17.0-x86_64-pc-windows-msvc.zip":
        "f61ce51f0b0ade1015b7de7ef368541c5424e9756ecbd0d7af97d6d48030845f",
    "tectonic-0.17.0-x86_64-pc-windows-gnu.zip":
        "77a0ebba1cc54f6145dbc27377e253c9fffa07eab7c368ff9ef30c2d05557365",
    "tectonic-0.17.0-x86_64-apple-darwin.tar.gz":
        "7c90ef5b6ddb1eb1937e4337add5237b79338e4b9676459fa91187d24d6cdf80",
    "tectonic-0.17.0-aarch64-apple-darwin.tar.gz":
        "a3f1cac7c5678f01661a92212f58480ae3b0634115d880dbc59e2953ded45667",
    "tectonic-0.17.0-x86_64-unknown-linux-musl.tar.gz":
        "8533d07f9ccbd7a65824b9e0459041bca34af1eb33daba48f59215593753a3b7",
    "tectonic-0.17.0-aarch64-unknown-linux-musl.tar.gz":
        "b10954a95404f3ab2328d2fa59a5ebab8e657f893fab096f98be8db7c0c979b8",
}


class FetchError(RuntimeError):
    """获取/校验/安装过程中的可预期失败。"""


# ---------------------------------------------------------------------------
# 纯逻辑部分（不联网、不写盘，便于单测）
# ---------------------------------------------------------------------------

def _norm_arch(machine: str) -> str:
    m = (machine or "").lower()
    if m in ("x86_64", "amd64", "x64"):
        return "x86_64"
    if m in ("aarch64", "arm64"):
        return "aarch64"
    if m in ("armv7l", "armv6l", "arm"):
        return "arm"
    return m


def select_asset(version: str, plat: str | None = None, machine: str | None = None) -> str:
    """按平台选出发行包文件名；不支持的组合明确报错，不猜。"""
    plat = plat or sys.platform
    arch = _norm_arch(machine or platform.machine())
    v = version.lstrip("v")

    if plat.startswith("win"):
        if arch != "x86_64":
            raise FetchError(f"tectonic 未发布 Windows/{arch} 构建，仅提供 x86_64")
        # msvc 版与系统运行库匹配更好；gnu 版作对照存在但默认不用
        return f"tectonic-{v}-x86_64-pc-windows-msvc.zip"
    if plat == "darwin":
        if arch not in ("x86_64", "aarch64"):
            raise FetchError(f"tectonic 未发布 macOS/{arch} 构建")
        return f"tectonic-{v}-{arch}-apple-darwin.tar.gz"
    if plat.startswith("linux"):
        # 选 musl 静态版：不依赖宿主 glibc 版本，跨发行版更稳
        if arch == "x86_64":
            return f"tectonic-{v}-x86_64-unknown-linux-musl.tar.gz"
        if arch == "aarch64":
            return f"tectonic-{v}-aarch64-unknown-linux-musl.tar.gz"
        if arch == "arm":
            return f"tectonic-{v}-arm-unknown-linux-musleabihf.tar.gz"
        raise FetchError(f"tectonic 未发布 Linux/{arch} 构建")
    raise FetchError(f"不支持的平台：{plat}（本脚本只在 win32 / darwin / linux 上给出下载方案）")


def parse_digest(digest_field: str | None) -> str | None:
    """解析 API 的 ``asset.digest``；无法确定算法时返回 None（宁可失败也不猜）。

    接受两种写法：``sha256:<64 hex>`` 与裸 ``<64 hex>``（64 位十六进制只可能对应
    SHA-256——SHA-512 是 128 位、SHA-1 是 40 位，故无歧义）。
    """
    if not digest_field or not isinstance(digest_field, str):
        return None
    raw = digest_field.strip()
    algo, sep, value = raw.partition(":")
    if sep:
        if algo.strip().lower() != "sha256":
            return None
        value = value.strip().lower()
    else:
        value = raw.lower()
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        return None
    return value


def resolve_expected(api_digest: str | None, asset_name: str, *,
                     explicit: str | None = None) -> dict:
    """决定「拿什么来比对」，并标明来源与可信度。

    优先级：用户显式指定 > API digest > 钉住表 > 无（拒绝安装，除非显式豁免）。
    """
    if explicit:
        val = explicit.strip().lower()
        if len(val) != 64 or any(c not in "0123456789abcdef" for c in val):
            raise FetchError(f"--expect-sha256 不是合法 sha256（需 64 位十六进制）：{explicit}")
        return {"sha256": val, "source": "user", "note": "由调用方显式指定"}
    got = parse_digest(api_digest)
    if got:
        return {"sha256": got, "source": "github_api_digest",
                "note": "取自 GitHub Releases API，与下载同源；能防损坏/错配/资产替换，但不是签名"}
    if api_digest:
        # 有值却解析不了：不能悄悄退回钉住表，否则「换了算法」会被当成「校验通过」
        raise FetchError(
            f"GitHub API 返回的 digest 无法识别：{api_digest!r}。"
            "拒绝静默降级到钉住表——请显式给出 --expect-sha256。"
        )
    pinned = PINNED_DIGESTS.get(asset_name)
    if pinned:
        return {"sha256": pinned, "source": "pinned",
                "note": "断网兜底：脚本内钉住的发布方声明值缓存，非第三方独立验证"}
    return {"sha256": None, "source": "none",
            "note": "既无 API digest 也无钉住值，无法校验"}


def verify_file(path: Path, expected_sha: str | None, expected_size: int | None = None) -> dict:
    """校验本地文件；不匹配抛异常（含实际值，便于排查），不返回「大概通过」。"""
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            h.update(chunk)
    actual = h.hexdigest()
    if expected_size is not None and size != expected_size:
        raise FetchError(f"大小不符：期望 {expected_size} B，实际 {size} B（可能未下完或被替换）")
    if expected_sha is None:
        return {"verified": False, "sha256": actual, "bytes": size}
    if actual != expected_sha:
        raise FetchError(
            "sha256 校验失败：\n"
            f"  期望 {expected_sha}\n  实际 {actual}\n"
            "已丢弃该文件，未安装任何二进制。"
        )
    return {"verified": True, "sha256": actual, "bytes": size}


def extract_binary(archive: Path, exe_name: str = "tectonic") -> bytes:
    """从 zip/tar.gz 中取出可执行文件字节。

    刻意不 ``extractall``：只读单个成员并返回字节，避免路径穿越与多余文件落盘。
    """
    targets = {exe_name, f"{exe_name}.exe"}
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if Path(info.filename).name in targets:
                    return zf.read(info)
        raise FetchError(f"压缩包内未找到 {exe_name}：{[i.filename for i in zf.infolist()][:8]}")
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive, mode="r:*") as tf:
            for member in tf.getmembers():
                if member.isfile() and Path(member.name).name in targets:
                    fp = tf.extractfile(member)
                    if fp is None:
                        continue
                    return fp.read()
        raise FetchError(f"压缩包内未找到 {exe_name}")
    raise FetchError(f"既不是 zip 也不是 tar：{archive.name}")


def default_dest() -> Path:
    """与 ``gewu.latex_build._COMMON_ENGINE_PATHS`` 的约定位置保持一致。"""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / "gewu" / "tools"
    return Path.home() / ".gewu" / "tools"


# ---------------------------------------------------------------------------
# 联网部分
# ---------------------------------------------------------------------------

def _fetch_json(url: str, timeout: int) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise FetchError(
                "GitHub API 返回 403：多半是未认证请求被限流（60 次/小时）。"
                "稍后重试，或用 --expect-sha256 显式给出校验值，或改用带本地包的 --archive。"
            ) from e
        raise FetchError(f"GitHub API HTTP {e.code}：{url}") from e
    except urllib.error.URLError as e:
        raise FetchError(f"无法访问 GitHub API（{e.reason}）；如已断网，可用 --archive 指向本地包") from e


def fetch_release(version: str | None, timeout: int = 60) -> dict:
    url = _API_LATEST if not version else _API_TAG + urllib.parse.quote(f"tectonic@{version.lstrip('v')}", safe="")
    return _fetch_json(url, timeout)


def _download(url: str, dest: Path, *, timeout: int, progress) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    h = hashlib.sha256()
    total = 0
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
            declared = resp.headers.get("Content-Length")
            declared_n = int(declared) if declared and declared.isdigit() else None
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_BYTES:
                    raise FetchError(f"下载超过上限 {_MAX_BYTES} B，已中止（疑似异常响应）")
                h.update(chunk)
                f.write(chunk)
                if progress:
                    progress(total, declared_n)
    except urllib.error.HTTPError as e:
        raise FetchError(f"下载失败 HTTP {e.code}：{url}") from e
    except urllib.error.URLError as e:
        raise FetchError(f"下载失败（{e.reason}）：{url}") from e
    return {"sha256": h.hexdigest(), "bytes": total,
            "declared_bytes": declared_n, "duration_s": round(time.time() - t0, 1)}


def _run_version(exe: Path) -> str:
    """实际执行二进制取版本号——安装后的功能自检，而不是只看文件存在。"""
    import subprocess  # 局部导入：纯逻辑单测不需要它

    try:
        proc = subprocess.run([str(exe), "--version"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise FetchError(f"已写入 {exe}，但无法执行：{e}") from e
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        raise FetchError(f"`tectonic --version` 退出码 {proc.returncode}：{out[:300]}")
    return out


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run(*, version: str | None, dest: Path, force: bool, allow_unverified: bool,
        expect_sha256: str | None, archive: Path | None, timeout: int,
        check_only: bool, quiet: bool) -> dict:
    exe_name = "tectonic.exe" if sys.platform.startswith("win") else "tectonic"
    exe_path = dest / exe_name
    log = (lambda *a: None) if quiet else (lambda *a: print(*a, file=sys.stderr))

    if check_only:
        info: dict = {"action": "check", "dest": str(dest), "exe": str(exe_path),
                      "exists": exe_path.is_file()}
        if exe_path.is_file():
            info["version_output"] = _run_version(exe_path)
            info["sha256"] = verify_file(exe_path, None)["sha256"]
        try:
            from gewu.latex_build import find_engine  # noqa: PLC0415
            found = find_engine()
            info["detected"] = {"engine": found[0], "path": found[1]} if found else None
        except Exception as e:  # noqa: BLE001
            info["detected"] = None
            info["detect_error"] = str(e)
        return info

    # 幂等：已存在且版本吻合就不再下载
    if exe_path.is_file() and not force:
        try:
            existing = _run_version(exe_path)
        except FetchError:
            existing = ""
        if version is None or version.lstrip("v") in existing:
            return {"action": "already_present", "ok": True, "exe": str(exe_path),
                    "version_output": existing,
                    "sha256": verify_file(exe_path, None)["sha256"],
                    "integrity": {"verified": None, "source": "existing_install",
                                  "note": "复用已有安装，未重新下载校验"}}

    dest.mkdir(parents=True, exist_ok=True)

    # 1) 元数据：版本号与资产清单
    if archive is not None:
        if not archive.is_file():
            raise FetchError(f"--archive 指向的文件不存在：{archive}")
        rel = {"tag_name": version or "local", "assets": []}
        # 本地包常被改名（tectonic.zip），故按 --version 推出**规范资产名**再撞钉住表；
        # 若文件名本身就在表里（保留原始发布名）则优先用它。
        if version:
            try:
                asset_name = archive.name if archive.name in PINNED_DIGESTS else select_asset(version)
            except FetchError:
                asset_name = archive.name
        else:
            asset_name = archive.name
        download_url = None
        api_digest = None
        api_size = None
        log(f"[1/5] 使用本地包 {archive.name}（跳过联网取元数据，按 {asset_name} 取期望值）")
    else:
        log("[1/5] 读取 GitHub Releases 元数据 ...")
        rel = fetch_release(version, timeout=timeout)
        tag = rel.get("tag_name", "")
        ver = tag.split("@")[-1].lstrip("v") if tag else (version or "")
        asset_name = select_asset(ver or (version or "").lstrip("v"))
        hit = next((a for a in rel.get("assets", []) if a.get("name") == asset_name), None)
        if hit is None:
            names = [a.get("name") for a in rel.get("assets", [])]
            raise FetchError(f"发行版 {tag} 中找不到 {asset_name}；可用资产：{names[:6]}")
        download_url = hit.get("browser_download_url")
        api_digest = hit.get("digest")
        api_size = hit.get("size")
        log(f"      版本 {tag} / 资产 {asset_name} / {api_size} B")

    # 2) 期望值
    expected = resolve_expected(api_digest, asset_name, explicit=expect_sha256)
    if expected["sha256"] is None and not allow_unverified:
        raise FetchError(
            "无法获得可校验的 sha256（API 无 digest、脚本内也无该资产的钉住值）。\n"
            "为避免装作「已校验」，默认中止。三条出路：\n"
            "  1) 指定版本：--version 0.17.0（钉住表覆盖该版本）；\n"
            "  2) 自备校验值：--expect-sha256 <64 位十六进制>；\n"
            "  3) 明确放弃校验：--allow-unverified（结果会标记 verified=false）。"
        )

    # 3) 下载 + 校验
    tmpdir = Path(tempfile.mkdtemp(prefix="gewu-tectonic-"))
    local_archive = archive if archive is not None else tmpdir / asset_name
    try:
        if archive is None:
            log(f"[2/5] 下载 {asset_name} ...")
            last = [0]

            def progress(done: int, total: int | None) -> None:
                mb = done / 1048576
                if total:
                    if mb - last[0] >= 5 or done == total:
                        last[0] = mb
                        log(f"      {mb:.1f}/{total / 1048576:.1f} MB")
                elif mb - last[0] >= 5:
                    last[0] = mb
                    log(f"      {mb:.1f} MB")

            dl = _download(download_url, local_archive, timeout=timeout, progress=progress)
        else:
            dl = {}

        log("[3/5] 校验 sha256 ...")
        v = verify_file(local_archive, expected["sha256"],
                        api_size if (archive is None and expected["source"] == "github_api_digest") else None)
        integrity = {
            "verified": v["verified"],
            "sha256": v["sha256"],
            "expected": expected["sha256"],
            "source": expected["source"],
            "note": expected["note"],
            "signature": "none",  # 如实标注：本项目未做签名验证
        }
        log(f"      {'OK' if v['verified'] else '跳过校验'}  {v['sha256'][:16]}…  {v['bytes']} B")

        # 4) 解压 + 安装
        log("[4/5] 解压并安装 ...")
        blob = extract_binary(local_archive, "tectonic")
        if len(blob) < 1024:
            raise FetchError(f"取出的可执行文件只有 {len(blob)} B，明显不是有效二进制")
        tmp_exe = dest / (exe_name + ".part")
        tmp_exe.write_bytes(blob)
        if not sys.platform.startswith("win"):
            tmp_exe.chmod(tmp_exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(tmp_exe, exe_path)  # 原子替换：不留半个二进制

        # 5) 功能自检
        log("[5/5] 功能自检（实际执行 --version）...")
        version_out = _run_version(exe_path)
        # 版本比对只在「知道期望版本」时进行；本地包未指定版本时不做无意义比对
        if version:
            want = version.lstrip("v")
        else:
            tag = rel.get("tag_name", "")
            want = tag.split("@")[-1].lstrip("v") if "@" in tag else ""
        if want and want not in version_out:
            raise FetchError(f"版本不符：期望含 {want}，实际输出 {version_out!r}")
        log(f"      {version_out}")

        detected = None
        try:
            from gewu.latex_build import find_engine  # noqa: PLC0415
            found = find_engine()
            detected = {"engine": found[0], "path": found[1]} if found else None
        except Exception:  # noqa: BLE001
            detected = None

        return {
            "action": "installed",
            "ok": True,
            "exe": str(exe_path),
            "asset": asset_name,
            "bytes": v["bytes"],
            "download": dl,
            "version_output": version_out,
            "integrity": integrity,
            "detected": detected,
            "next": "首次编译需从 CTAN 拉取约 300 MB bundle（实测约 6 分钟），之后编译约 1–2 秒。",
        }
    finally:
        if archive is None:
            shutil.rmtree(tmpdir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="下载并安装单文件 LaTeX 引擎 tectonic（含 sha256 校验与功能自检）",
        epilog="示例：python scripts/fetch_tectonic.py --version 0.17.0",
    )
    ap.add_argument("--version", default=None, help="tectonic 版本，如 0.17.0（默认取最新版；钉版本更可复现）")
    ap.add_argument("--dest", default=None, help="安装目录（默认 %LOCALAPPDATA%\\gewu\\tools 或 ~/.gewu/tools）")
    ap.add_argument("--force", action="store_true", help="已存在也重新下载安装")
    ap.add_argument("--check-only", action="store_true", help="只体检：报现有安装与项目探测结果，不联网不写盘")
    ap.add_argument("--archive", default=None, help="用本地已下载的发行包，不联网（需配 --expect-sha256 或钉住值）")
    ap.add_argument("--expect-sha256", default=None, help="显式给出期望 sha256（64 位十六进制）")
    ap.add_argument("--allow-unverified", action="store_true", help="拿不到校验值也继续（结果标记 verified=false）")
    ap.add_argument("--timeout", type=int, default=180, help="单次网络请求超时秒数（默认 180）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--quiet", action="store_true", help="不打印进度")
    args = ap.parse_args(argv)

    dest = Path(args.dest).expanduser() if args.dest else default_dest()
    archive = Path(args.archive).expanduser().resolve() if args.archive else None

    try:
        r = run(version=args.version, dest=dest, force=args.force,
                allow_unverified=args.allow_unverified, expect_sha256=args.expect_sha256,
                archive=archive, timeout=args.timeout, check_only=args.check_only,
                quiet=args.json or args.quiet)
    except FetchError as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=2))
        else:
            print(f"失败：{e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0

    if r["action"] == "check":
        print(f"安装位置 {r['exe']}")
        print(f"是否存在 {r['exists']}")
        if r.get("version_output"):
            print(f"版本     {r['version_output']}")
        if r.get("detected"):
            print(f"项目探测 {r['detected']['engine']} → {r['detected']['path']}")
        else:
            print("项目探测 未找到引擎（可直接运行本脚本安装）")
        return 0

    if r["action"] == "already_present":
        print(f"已存在且可用：{r['exe']}  ({r['version_output']})")
        print("如需重装：--force")
        return 0

    integ = r["integrity"]
    print(f"已安装 {r['exe']}")
    print(f"  资产     {r['asset']}  ({r['bytes']} B)")
    print(f"  版本     {r['version_output']}")
    print(f"  校验     {'通过' if integ['verified'] else '未校验'}  来源={integ['source']}  {integ['sha256'][:16]}…")
    if integ["source"] == "github_api_digest":
        print("           注：digest 与下载同源于 GitHub，可防损坏/错配/资产替换；不是签名。")
    if r.get("detected"):
        print(f"  项目探测 {r['detected']['engine']} → {r['detected']['path']}")
    else:
        print("  项目探测 仍未找到（检查 GEWU_LATEX_ENGINE 或 PATH）")
    print(f"  下一步   {r['next']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
