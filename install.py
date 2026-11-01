#!/usr/bin/env python3
"""Reeden Kobo (0.7.2) One-Click Builder & Installer.

Combines the verified MIT Kobo compatibility layer with the user's unmodified
official Reeden Kindle 1.43.1+780 or 1.43.2+791 core and pinned Debian Bullseye ARMHF runtime
packages, then installs to a Kobo Clara Colour (393) via USB or SSH (or outputs
a verified local package directory).

100% Python 3 standard library; works on macOS, Windows, and Linux without
requiring Zig, fontTools, ar, or external tar binaries.
"""
import argparse
import datetime
import hashlib
import io
import json
import os
import pathlib
import platform
import shutil
import ssl
import subprocess
import sys
if sys.version_info < (3, 10):
    sys.exit('需要 Python 3.10 或更新版本，请升级 Python 后重新运行安装器。')
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
SUPPORTED_CORES = {
    '1.43.2+791': {
        'libflutter_engine.so': '854a11f2f649eeab245279f2b5b2c6db2df4f68ba2b28aa3e111ce834058bb9e',
        'libapp.so': 'daf57297da3db5293ced3f12c708d80c1fce18141da15e3b504070dd702b599a',
    },
    '1.43.1+780': {
        'libflutter_engine.so': '8eca49cb5a50573f61668706a99807e3987902b37c311d982872d31fd09e4f37',
        'libapp.so': '6662907460efb82361eb7c3bdffcb83735bda381f6d98445d61e00e10bc6930e',
    },
}
OFFICIAL_LATEST_URL = 'https://download.reeden.app/Reeden/latest/Reeden-kindle.zip'
PORT_VERSION = '0.7.2-experimental'
SUPPORTED_PRODUCT = '393'


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def copy_regular(src: pathlib.Path, dst: pathlib.Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src.resolve(), dst)


def copy_lf_script(src: pathlib.Path, dst: pathlib.Path, mode: int = 0o755) -> None:
    """Copy a shell script while normalizing CRLF -> LF (Windows autocrlf safety)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    raw = src.resolve().read_bytes().replace(b'\r\n', b'\n')
    dst.write_bytes(raw)
    dst.chmod(mode)


def cleanup_appledouble(root_dir: pathlib.Path) -> None:
    """Remove macOS AppleDouble (._*) metadata files created on FAT32 volumes."""
    if not root_dir.exists():
        return
    if root_dir.is_file():
        if root_dir.name.startswith('._'):
            root_dir.unlink(missing_ok=True)
        return
    for p in list(root_dir.rglob('._*')):
        if p.is_file():
            p.unlink(missing_ok=True)


def copytree_fat32_safe(src: pathlib.Path, dst: pathlib.Path) -> None:
    """Copy directory contents using copyfile (omitting macOS xattrs on FAT32)."""
    shutil.copytree(src, dst, copy_function=shutil.copyfile, dirs_exist_ok=True)
    cleanup_appledouble(dst)


def verify_prebuilt(root: pathlib.Path) -> pathlib.Path:
    prebuilt = root / 'prebuilt'
    manifest = prebuilt / 'PREBUILT_SHA256SUMS'
    if not manifest.is_file():
        raise RuntimeError(f'缺少预编译清单: {manifest}')
    for line in manifest.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        digest, rel_str = line.split('  ', 1)
        rel = pathlib.PurePosixPath(rel_str)
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError(f'不安全的预编译路径: {rel_str}')
        target = prebuilt.joinpath(*rel.parts)
        if not target.is_file():
            raise FileNotFoundError(f'缺少预编译文件: {target}')
        if sha256_file(target) != digest:
            raise ValueError(f'预编译文件哈希不匹配: {rel_str}')
    return prebuilt


def find_core_dir_in(base: pathlib.Path) -> pathlib.Path | None:
    candidates = [
        base,
        base / 'reeden' / 'reeden',
        base / 'reeden',
    ]
    for cand in candidates:
        if (cand / 'lib' / 'libflutter_engine.so').is_file() and (cand / 'lib' / 'libapp.so').is_file():
            return cand
    return None


def auto_discover_official_input(root: pathlib.Path) -> pathlib.Path | None:
    env_core = os.environ.get('REEDEN_OFFICIAL_CORE', '').strip()
    if env_core:
        p = pathlib.Path(env_core).expanduser()
        if p.exists():
            return p
    home = pathlib.Path.home()
    cwd = pathlib.Path.cwd()
    search_paths = [
        root / 'Reeden-kindle.zip',
        cwd / 'Reeden-kindle.zip',
        root / 'cache' / 'Reeden-kindle.zip',
        root / 'reeden' / 'reeden',
        cwd / 'reeden' / 'reeden',
        home / 'Downloads' / 'Reeden-kindle.zip',
        home / 'Downloads' / 'reeden' / 'reeden',
        home / 'Desktop' / 'Reeden-kindle.zip',
    ]
    for p in search_paths:
        if p.exists():
            return p
    # Also match browser-renamed downloads such as "Reeden-kindle (1).zip"
    for folder in (root, cwd, home / 'Downloads', home / 'Desktop'):
        if not folder.is_dir():
            continue
        try:
            for item in sorted(folder.iterdir()):
                low = item.name.lower()
                if item.is_file() and low.startswith('reeden') and 'kindle' in low and low.endswith('.zip'):
                    return item
        except OSError:
            continue
    return None


def clean_dragged_path(raw: str) -> pathlib.Path:
    s = raw.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1]
    elif platform.system() != 'Windows':
        s = s.replace('\\ ', ' ')
    return pathlib.Path(s).expanduser()


def resolve_official_core(user_arg: str | None, temp_root: pathlib.Path, auto_download: bool = False) -> tuple[pathlib.Path, str]:
    target: pathlib.Path | None = None
    if user_arg:
        target = pathlib.Path(user_arg).expanduser().resolve()
    else:
        target = auto_discover_official_input(ROOT)
        if target is not None:
            print(f'[1/4] 自动发现官方包: {target}')
        elif auto_download:
            cache_zip = ROOT / 'cache' / 'Reeden-kindle.zip'
            cache_zip.parent.mkdir(parents=True, exist_ok=True)
            print(f'[1/4] 正在从 Reeden 官网下载最新安装包 ({OFFICIAL_LATEST_URL}) ...')
            req = urllib.request.Request(OFFICIAL_LATEST_URL, headers={'User-Agent': 'reeden-kobo-installer/0.7.2'})
            with open_url_with_cert_fallback(req, timeout=180) as resp, cache_zip.open('wb') as out:
                shutil.copyfileobj(resp, out)
            target = cache_zip
        elif sys.stdin.isatty():
            print('\n未在当前目录或「下载」目录自动找到 Reeden-kindle.zip。')
            print('支持官方版本：1.43.2+791 或 1.43.1+780（白名单以本安装器为准）')
            entered = input('请将 Reeden-kindle.zip 拖入此窗口并按回车（直接按回车则自动从官网下载最新包）: ').strip()
            if entered:
                target = clean_dragged_path(entered).resolve()
            else:
                cache_zip = ROOT / 'cache' / 'Reeden-kindle.zip'
                cache_zip.parent.mkdir(parents=True, exist_ok=True)
                print(f'[1/4] 正在从 Reeden 官网下载最新安装包 ({OFFICIAL_LATEST_URL}) ...')
                req = urllib.request.Request(OFFICIAL_LATEST_URL, headers={'User-Agent': 'reeden-kobo-installer/0.7.2'})
                with open_url_with_cert_fallback(req, timeout=180) as resp, cache_zip.open('wb') as out:
                    shutil.copyfileobj(resp, out)
                target = cache_zip
    if target is None or not target.exists():
        raise FileNotFoundError(
            '未找到官方 Reeden Kindle 安装包 (支持 1.43.2+791 或 1.43.1+780)。请将 Reeden-kindle.zip 放在同目录或系统「下载」文件夹，'
            '或通过 --official-core 指定路径（也可加 --download-official 自动从官网下载）。'
        )
    if target.is_file() and zipfile.is_zipfile(target):
        extract_dir = temp_root / 'official-extracted'
        print(f'[1/4] 正在解压官方安装包 {target.name} ...')
        with zipfile.ZipFile(target, 'r') as zf:
            zf.extractall(extract_dir)
        core_dir = find_core_dir_in(extract_dir)
    else:
        core_dir = find_core_dir_in(target)
    if core_dir is None:
        raise ValueError(f'在 {target} 中未找到包含 data/ 与 lib/ 的官方 reeden/reeden 目录')

    actual_hashes = {}
    for name in ('libflutter_engine.so', 'libapp.so'):
        lib_path = core_dir / 'lib' / name
        if not lib_path.is_file():
            raise FileNotFoundError(f'缺少官方核心文件: {lib_path}')
        actual_hashes[name] = sha256_file(lib_path)

    matched_version = next(
        (ver for ver, expected in SUPPORTED_CORES.items() if actual_hashes == expected),
        None,
    )
    if matched_version is None:
        supported_str = ' / '.join(SUPPORTED_CORES.keys())
        raise ValueError(
            f'官方核心版本不在已验证白名单内 (当前支持: {supported_str})。\n'
            f'实测 libflutter_engine.so={actual_hashes["libflutter_engine.so"][:12]}..., '
            f'libapp.so={actual_hashes["libapp.so"][:12]}...'
        )
    for rel in ('data/flutter_assets', 'lib/glibc', 'licenses'):
        if not (core_dir / rel).is_dir():
            raise FileNotFoundError(f'缺少官方子目录: {core_dir / rel}')
    print(f'[1/4] 官方 Reeden {matched_version} 核心 SHA-256 校验通过（原字节未修改）')
    return core_dir, matched_version


def open_url_with_cert_fallback(req: urllib.request.Request, timeout: int = 60):
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError) and pathlib.Path('/etc/ssl/cert.pem').is_file():
            ctx = ssl.create_default_context(cafile='/etc/ssl/cert.pem')
            return urllib.request.urlopen(req, timeout=timeout, context=ctx)
        raise


def download_verified(url: str, sha256: str, cache_dir: pathlib.Path, alt_dirs: list[pathlib.Path]) -> pathlib.Path:
    filename = pathlib.Path(url).name
    for d in [cache_dir, *alt_dirs]:
        cand = d / filename
        if cand.is_file() and sha256_file(cand) == sha256:
            return cand
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / filename
    print(f'      下载依赖: {filename} ...')
    req = urllib.request.Request(url, headers={'User-Agent': 'reeden-kobo-installer/0.7.2'})
    with open_url_with_cert_fallback(req, timeout=60) as resp, dest.open('wb') as out:
        shutil.copyfileobj(resp, out)
    if sha256_file(dest) != sha256:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f'下载文件哈希校验失败: {filename}')
    return dest


def extract_deb_pure(deb_path: pathlib.Path, dest_dir: pathlib.Path) -> None:
    data = deb_path.read_bytes()
    if not data.startswith(b'!<arch>\n'):
        raise ValueError(f'非法的 deb/ar 归档文件: {deb_path}')
    pos = 8
    data_payload = None
    while pos + 60 <= len(data):
        hdr = data[pos:pos + 60]
        name = hdr[0:16].decode('ascii', errors='replace').strip()
        size = int(hdr[48:58].decode('ascii').strip())
        pos += 60
        body = data[pos:pos + size]
        pos += size + (size % 2)
        if name.endswith('/'):
            name = name[:-1]
        if name.startswith('data.tar'):
            data_payload = body
            break
    if data_payload is None:
        raise ValueError(f'未在 {deb_path} 中找到 data.tar.*')

    symlinks = []
    with tarfile.open(fileobj=io.BytesIO(data_payload), mode='r:*') as tf:
        for member in tf.getmembers():
            rel = pathlib.PurePosixPath(member.name)
            parts = [p for p in rel.parts if p not in ('', '.')]
            if not parts or '..' in parts:
                continue
            target = dest_dir.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(member) as src:
                    target.write_bytes(src.read())
            elif member.issym() or member.islnk():
                symlinks.append((target, member.linkname, member.issym()))

    for _ in range(4):
        remaining = []
        for target, linkname, is_sym in symlinks:
            link_rel = pathlib.PurePosixPath(linkname)
            if is_sym and not link_rel.is_absolute():
                src_path = (target.parent / pathlib.Path(*link_rel.parts)).resolve()
            else:
                parts = [p for p in link_rel.parts if p not in ('', '/', '.')]
                src_path = dest_dir.joinpath(*parts).resolve()
            if src_path.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, target)
            else:
                remaining.append((target, linkname, is_sym))
        if not remaining:
            break
        symlinks = remaining


def assemble_package(
    core_dir: pathlib.Path,
    official_version: str,
    prebuilt_dir: pathlib.Path,
    dest: pathlib.Path,
    temp_root: pathlib.Path,
) -> int:
    cache_dir = ROOT / 'cache'
    alt_dirs = [ROOT.parent / 'deps']
    deb_manifest = json.loads((ROOT / 'vendor/debian-runtime-manifest.json').read_text(encoding='utf-8'))
    font_manifest = json.loads((ROOT / 'vendor/font-manifest.json').read_text(encoding='utf-8'))

    print('[2/4] 正在准备并校验 Debian Bullseye ARMHF 运行库与开源字体 ...')
    deps_root = temp_root / 'debian-runtime'
    deps_root.mkdir(parents=True, exist_ok=True)
    for item in deb_manifest:
        deb_file = download_verified(item['url'], item['sha256'], cache_dir, alt_dirs)
        extract_deb_pure(deb_file, deps_root)
    cjk_font = download_verified(font_manifest['url'], font_manifest['sha256'], cache_dir, alt_dirs)

    print('[3/4] 正在组装完整运行包 (无符号链接，适配 FAT32 分区) ...')
    for d in [
        'bin', 'lib', 'runtime', 'fonts', 'certs', 'checks', 'licenses',
        'docs', 'state', 'logs', 'userdata', 'storage/books', 'storage/documents',
        'storage/screenshots', 'cache',
    ]:
        (dest / d).mkdir(parents=True, exist_ok=True)

    # 1. Official core (byte-for-byte unchanged)
    for src in (core_dir / 'lib').glob('*.so*'):
        copy_regular(src, dest / 'core/lib' / src.name)
    shutil.copytree(core_dir / 'data', dest / 'core/data', dirs_exist_ok=True)
    for src in (core_dir / 'lib/glibc').iterdir():
        if src.is_file():
            copy_regular(src, dest / 'runtime' / src.name)
    shutil.copytree(core_dir / 'licenses', dest / 'licenses/official', dirs_exist_ok=True)
    copy_regular(core_dir / 'THIRD_PARTY_NOTICES.txt', dest / 'licenses/official/THIRD_PARTY_NOTICES.txt')

    # 2. UI assets overlay (CJK + Math fallback font)
    shutil.copytree(core_dir / 'data/flutter_assets', dest / 'ui-assets', dirs_exist_ok=True)
    copy_regular(
        prebuilt_dir / 'fonts/KoboCJKMath-Regular.ttf',
        dest / 'ui-assets/assets/fonts/KoboCJKMath-Regular.ttf',
    )
    font_manifest_path = dest / 'ui-assets/FontManifest.json'
    families = json.loads(font_manifest_path.read_text(encoding='utf-8'))
    for family in families:
        if family.get('family') == 'NotoSansMath':
            family['fonts'] = [{'asset': 'assets/fonts/KoboCJKMath-Regular.ttf'}]
    font_manifest_path.write_text(json.dumps(families, separators=(',', ':')) + '\n', encoding='utf-8', newline='\n')

    # 3. Debian ARMHF runtime & CA certificates
    for tree in [deps_root / 'lib/arm-linux-gnueabihf', deps_root / 'usr/lib/arm-linux-gnueabihf']:
        for src in tree.glob('*.so*'):
            copy_regular(src, dest / 'lib' / src.name)
    for stem in ['gio', 'glib', 'gobject', 'gmodule', 'gthread']:
        copy_regular(dest / f'lib/lib{stem}-2.0.so.0', dest / f'lib/lib{stem}-2.0.so')
    for src in (deps_root / 'usr/share/doc').glob('*/copyright'):
        copy_regular(src, dest / 'licenses/debian' / f'{src.parent.name}-copyright')
    certificates = sorted((deps_root / 'usr/share/ca-certificates/mozilla').glob('*.crt'))
    if len(certificates) < 100:
        raise RuntimeError('缺少 Mozilla 公共根证书集合')
    (dest / 'certs/ca-certificates.crt').write_bytes(b'\n'.join(x.read_bytes() for x in certificates))

    # 4. Prebuilt Kobo adapter binaries & LF-normalized shell scripts
    copy_regular(prebuilt_dir / 'bin/fb-guard', dest / 'bin/fb-guard')
    copy_regular(prebuilt_dir / 'bin/reeden-kindle', dest / 'bin/reeden-kindle')
    copy_regular(prebuilt_dir / 'lib/libreeden_kobo_compat.so', dest / 'lib/libreeden_kobo_compat.so')
    for src in sorted((prebuilt_dir / 'checks').iterdir()):
        if src.is_file():
            copy_regular(src, dest / 'checks' / src.name)
    for name in [
        'run.sh', 'session.sh', 'recover.sh', 'guardian.sh',
        'native-session.sh', 'power.sh', 'precheck.sh', 'reeden-ssh.sh',
        'uninstall.sh', 'install.sh', 'verify.sh',
    ]:
        copy_lf_script(ROOT / 'scripts' / name, dest / name, 0o755)
    for name in ['lipc-get-prop', 'lipc-set-prop']:
        copy_lf_script(ROOT / 'scripts' / name, dest / 'bin' / name, 0o755)

    # 5. Fonts, licenses, docs, NickelMenu config, build-info, SHA256SUMS
    copy_regular(ROOT / 'LICENSE', dest / 'licenses/adapter-MIT-LICENSE')
    copy_regular(cjk_font, dest / 'fonts/NotoSansCJKsc-Regular.otf')
    for src in sorted((ROOT / 'vendor').glob('*LICENSE*')):
        copy_regular(src, dest / 'licenses' / src.name)
    copy_regular(ROOT / 'vendor/debian-runtime-manifest.json', dest / 'licenses/debian-runtime-manifest.json')
    for src in sorted((ROOT / 'docs').rglob('*')):
        if src.is_file():
            copy_regular(src, dest / 'docs' / src.relative_to(ROOT / 'docs'))
    for group in ('bin', 'runtime', 'checks'):
        for src in (dest / group).iterdir():
            if src.is_file():
                src.chmod(0o755)

    copy_lf_script(ROOT / 'scripts/nickelmenu.conf', dest / 'nickelmenu.conf', 0o644)
    info = {
        'port_version': PORT_VERSION,
        'official_version': official_version,
        'model': 'Kobo Clara Colour (393)',
        'firmware': '4.46.23836',
        'first_launch': 'NOT_PERFORMED',
        'official_core_unmodified': True,
        'ui_assets_overlay': True,
        'font_sha256': sha256_file(dest / 'fonts/NotoSansCJKsc-Regular.otf'),
    }
    (dest / 'build-info.json').write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8', newline='\n')

    cleanup_appledouble(dest)
    files = sorted(x for x in dest.rglob('*') if x.is_file() and x.name != 'SHA256SUMS')
    sums_text = ''.join(f'{sha256_file(x)}  {x.relative_to(dest).as_posix()}\n' for x in files)
    (dest / 'SHA256SUMS').write_text(sums_text, encoding='utf-8', newline='\n')
    return len(files)


def detect_kobo_usb_mounts() -> list[pathlib.Path]:
    found = []
    sys_name = platform.system()
    candidates = []
    if sys_name == 'Darwin':
        vol = pathlib.Path('/Volumes')
        if vol.is_dir():
            candidates.extend(sorted(vol.iterdir()))
    elif sys_name == 'Windows':
        for letter in 'DEFGHIJKLMNOPQRSTUVWXYZ':
            candidates.append(pathlib.Path(f'{letter}:\\'))
    else:
        for base in (pathlib.Path('/media'), pathlib.Path('/run/media'), pathlib.Path('/mnt')):
            if base.is_dir():
                for child in sorted(base.iterdir()):
                    candidates.append(child)
                    if child.is_dir():
                        try:
                            candidates.extend(sorted(child.iterdir()))
                        except PermissionError:
                            pass
    seen = set()
    for cand in candidates:
        try:
            ver = cand / '.kobo' / 'version'
            if ver.is_file():
                resolved = cand.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    found.append(resolved)
        except OSError:
            continue
    return found


def parse_kobo_product(mount: pathlib.Path) -> tuple[str, str]:
    ver_file = mount / '.kobo' / 'version'
    if not ver_file.is_file():
        raise FileNotFoundError(f'未在 {mount} 找到 .kobo/version，请确认路径为 Kobo 根目录')
    raw = ver_file.read_text(encoding='utf-8', errors='replace').strip()
    parts = [p.strip() for p in raw.split(',')]
    firmware = parts[2] if len(parts) > 2 else 'unknown'
    last = parts[-1] if parts else ''
    product = last[-3:] if len(last) >= 3 else last
    return product, firmware


def install_to_usb_mount(pkg_dir: pathlib.Path, mount: pathlib.Path, allow_upgrade: bool) -> None:
    product, firmware = parse_kobo_product(mount)
    if product != SUPPORTED_PRODUCT:
        raise RuntimeError(
            f'机型不匹配：检测到 Kobo 产品代码 {product} (固件 {firmware})，'
            f'当前版本仅支持 Kobo Clara Colour (产品代码 {SUPPORTED_PRODUCT})。未对设备做任何修改。'
        )
    nm_dir = mount / '.adds' / 'nm'
    if not nm_dir.is_dir():
        raise RuntimeError(
            f'未检测到 NickelMenu 目录 ({nm_dir})。\n'
            '请先为 Kobo 安装 NickelMenu (https://pgaskin.net/NickelMenu/)，安装脚本未对设备做任何更改。'
        )
    dest = mount / '.adds' / 'reeden-kobo'
    entry = nm_dir / 'reeden-kobo'
    if entry.exists() and not dest.exists() and not allow_upgrade:
        raise RuntimeError('已有同名 NickelMenu 配置，未覆盖；请检查后使用 --upgrade。')
    if dest.exists():
        if not allow_upgrade:
            raise RuntimeError(
                f'检测到已存在安装目录 {dest}。如需保留书库与阅读进度升级，请加上 --upgrade 参数。'
            )
        if (dest / 'state' / 'active').exists():
            raise RuntimeError('检测到 Reeden 会话锁 state/active 仍存在，请先正常退出 Reeden 再升级。')

    keeps = ('userdata', 'storage', 'diagnostics/ssh')
    needed = sum(p.stat().st_size for p in pkg_dir.rglob('*') if p.is_file())
    for keep in keeps:
        if (dest / keep).is_dir():
            needed += sum(p.stat().st_size for p in (dest / keep).rglob('*') if p.is_file())
    if shutil.disk_usage(mount).free < needed + 16 * 1024 * 1024:
        raise RuntimeError('Kobo 剩余空间不足以安全安装并保留旧版备份，未改动原安装。')
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    stage = pathlib.Path(tempfile.mkdtemp(prefix='.reeden-kobo-stage-', dir=mount / '.adds'))
    menu_stage = None
    backup = None
    promoted = False
    try:
        menu_fd, menu_name = tempfile.mkstemp(prefix='.reeden-kobo-menu-', dir=nm_dir)
        os.close(menu_fd)
        menu_stage = pathlib.Path(menu_name)
        print(f'[4/4] 正在复制文件到 Kobo ({mount}) ...')
        copytree_fat32_safe(pkg_dir, stage)
        sums_lines = (stage / 'SHA256SUMS').read_text(encoding='utf-8').splitlines()
        print(f'      正在校验 Kobo 磁盘上的全部 {len(sums_lines)} 个安装文件 SHA-256 ...')
        for line in sums_lines:
            if not line.strip():
                continue
            digest, rel_str = line.split('  ', 1)
            rel = pathlib.PurePosixPath(rel_str)
            if rel.is_absolute() or '..' in rel.parts:
                raise ValueError(f'不安全的安装路径: {rel_str}')
            if sha256_file(stage.joinpath(*rel.parts)) != digest:
                raise RuntimeError(f'USB 写入校验失败: {rel_str}')
        # The old installation remains at its original path throughout copying.
        for keep in keeps:
            if (dest / keep).is_dir():
                copytree_fat32_safe(dest / keep, stage / keep)
        shutil.copyfile(stage / 'nickelmenu.conf', menu_stage)
        cleanup_appledouble(stage)
        if dest.exists():
            backup = mount / '.adds' / f'reeden-kobo-backup-{stamp}-{stage.name.rsplit("-", 1)[-1]}'
            dest.rename(backup)
        stage.rename(dest)
        promoted = True
        # Replace the menu only after promotion, in the same filesystem.
        os.replace(menu_stage, entry)
    except BaseException:
        try:
            if promoted:
                dest.rename(stage)
            if backup is not None and backup.exists():
                backup.rename(dest)
        except OSError as rollback_error:
            raise RuntimeError(f'自动恢复失败；旧版数据保留在 {backup}，新版位于 {dest if promoted else stage}。请勿删除这些目录。') from rollback_error
        shutil.rmtree(stage, ignore_errors=True)
        raise
    finally:
        if menu_stage is not None:
            try:
                menu_stage.unlink(missing_ok=True)
            except OSError:
                print(f'提示：临时菜单文件未能清理: {menu_stage}')
    try:
        cleanup_appledouble(nm_dir / '._reeden-kobo')
    except OSError:
        print('提示：安装已完成，macOS 元数据文件需在弹出前手动清理。')
    if backup is not None:
        print(f'✅ USB 一键升级完成！原阅读进度、笔记、冷暖光设置和书库已保留（旧版备份于 {backup.name}）。')
    else:
        print(f'✅ USB 一键安装完成！所有 {len(sums_lines)} 个文件已在 Kobo 磁盘上通过 SHA-256 校验。')
    print('👉 下一步：安全弹出 Kobo USB 盘，回到 Kobo 原生主界面，点击右下角 NickelMenu →「Reeden Kobo (test)」即可启动。')


def install_via_ssh(
    pkg_dir: pathlib.Path,
    host: str,
    port: str,
    allow_upgrade: bool,
    known_hosts: str | None,
    identity: str | None,
    password_auth: bool,
    temp_root: pathlib.Path,
) -> None:
    ssh_base = ['ssh', '-p', str(port), '-o', 'ConnectTimeout=10']
    if known_hosts:
        ssh_base += [
            '-o', 'StrictHostKeyChecking=yes',
            '-o', f'UserKnownHostsFile={pathlib.Path(known_hosts).expanduser().resolve()}',
        ]
    else:
        ssh_base += ['-o', 'StrictHostKeyChecking=accept-new']
    if identity:
        ssh_base += ['-i', str(pathlib.Path(identity).expanduser().resolve())]
    if password_auth:
        ssh_base += [
            '-o', 'PreferredAuthentications=password',
            '-o', 'PubkeyAuthentication=no',
            '-o', 'NumberOfPasswordPrompts=1',
        ]
    target = host if '@' in host else f'root@{host}'
    ssh_read = ssh_base + ['-n', target]
    ssh_stream = ssh_base + [target]

    # Pre-check remote device state before packing/streaming 78MB archive
    probe_cmd = (
        'if [ ! -d /mnt/onboard/.adds/nm ]; then echo ERR_NO_NM; '
        'elif [ -d /mnt/onboard/.adds/reeden-kobo/state/active ]; then echo ERR_ACTIVE; '
        'elif [ -e /mnt/onboard/.adds/reeden-kobo ] || [ -e /mnt/onboard/.adds/nm/reeden-kobo ]; then echo HAS_EXISTING; '
        'else echo READY_FRESH; fi'
    )
    probe = subprocess.run(ssh_read + [probe_cmd], text=True, capture_output=True, check=True)
    state_lines = [ln.strip() for ln in probe.stdout.splitlines() if ln.strip() in ('ERR_NO_NM', 'ERR_ACTIVE', 'HAS_EXISTING', 'READY_FRESH')]
    remote_state = state_lines[-1] if state_lines else 'UNKNOWN'
    if remote_state == 'ERR_NO_NM':
        raise RuntimeError('Kobo 上未检测到 NickelMenu (/mnt/onboard/.adds/nm)，请先安装 NickelMenu。')
    if remote_state == 'ERR_ACTIVE':
        raise RuntimeError('检测到 Kobo 上 Reeden 正在运行（state/active 存在）。请先在 Kobo 上同时按住左上角+右上角 2 秒退出 Reeden，再执行升级。')
    if remote_state == 'HAS_EXISTING' and not allow_upgrade:
        raise RuntimeError('检测到 Kobo 上已安装旧版 reeden-kobo。如需保留书库与阅读进度升级，请加上 --upgrade 参数。')

    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    remote_stage = f'/mnt/onboard/.adds/.reeden-kobo-stage-{stamp}'
    archive = temp_root / f'transfer-{stamp}.tar.gz'
    print(f'[4/4] 正在打包并经由 SSH ({target}:{port}) 推送到 Kobo ...')
    with tarfile.open(archive, 'w:gz', compresslevel=6) as tf:
        for path in sorted(pkg_dir.iterdir()):
            tf.add(path, arcname=path.name, recursive=True)

    subprocess.run(ssh_read + [f'mkdir {remote_stage}'], check=True)
    with archive.open('rb') as f:
        subprocess.run(ssh_stream + [f'tar -xzf - -C {remote_stage}'], stdin=f, check=True)
    install_cmd = f'sh {remote_stage}/install.sh' + (' --upgrade' if allow_upgrade else '')
    result = subprocess.run(ssh_read + [install_cmd], text=True, capture_output=True)
    print(result.stdout + result.stderr, end='')
    result.check_returncode()
    print('✅ SSH 一键安装完成（未自动启动应用）。请回到 Kobo 原生主界面，从 NickelMenu 点击「Reeden Kobo (test)」启动。')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--official-core',
        help='官方 Reeden 安装包路径 (支持 1.43.2+791 或 1.43.1+780；支持直接传 Reeden-kindle.zip 或解压后的 reeden/reeden 目录；省略时自动搜索)',
    )
    parser.add_argument(
        '--download-official',
        action='store_true',
        help='若本地未找到官方包，自动从 Reeden 官网下载最新 Reeden-kindle.zip 并校验',
    )
    parser.add_argument(
        '--output',
        help='在电脑本地输出完整 package 目录的路径（如传此参数且未指定 --usb / --ssh，则仅在本地生成安装包）',
    )
    parser.add_argument(
        '--usb',
        action='store_true',
        help='自动查找通过 USB 挂载的 KoboClaraColour (KOBOeReader) 并直接一键安装',
    )
    parser.add_argument(
        '--kobo-mount',
        help='手动指定 Kobo USB 挂载根目录（例如 /Volumes/KOBOeReader 或 E:\\）并一键安装',
    )
    parser.add_argument('--ssh', metavar='HOST', help='通过 Wi-Fi SSH 一键安装到指定 Kobo IP（例如 192.168.1.100）')
    parser.add_argument('--port', default='2222', help='SSH 端口（KOReader SSH 默认为 2222，Reeden 独立 SSH 为 2223）')
    parser.add_argument('--known-hosts', help='可选 SSH known_hosts 文件路径（启用严格主机密钥校验）')
    parser.add_argument('--identity', help='可选 SSH 私钥文件路径')
    parser.add_argument('--password-auth', action='store_true', help='使用 SSH 密码认证')
    parser.add_argument(
        '--upgrade',
        action='store_true',
        help='若设备已安装旧版 reeden-kobo，自动备份旧版并保留 userdata/ 与 storage/ 完成升级',
    )
    args = parser.parse_args()

    prebuilt_dir = verify_prebuilt(ROOT)
    with tempfile.TemporaryDirectory(prefix='reeden-kobo-oneclick-') as tmp:
        temp_root = pathlib.Path(tmp)
        core_dir, official_version = resolve_official_core(
            args.official_core,
            temp_root,
            auto_download=args.download_official,
        )

        # Determine output directory if requested
        if args.output:
            out_dir = pathlib.Path(args.output).expanduser().resolve()
            if out_dir.exists():
                parser.error(f'输出目录已存在，为保护现有文件已拒绝覆盖: {out_dir}')
            pkg_dir = out_dir
        else:
            pkg_dir = temp_root / 'package'

        file_count = assemble_package(core_dir, official_version, prebuilt_dir, pkg_dir, temp_root)
        print(f'      已组出 {file_count} 个已校验文件（加上 SHA256SUMS 共 {file_count + 1} 个文件）。')

        # Explicit CLI mode selection
        if args.kobo_mount:
            mount = pathlib.Path(args.kobo_mount).expanduser().resolve()
            install_to_usb_mount(pkg_dir, mount, allow_upgrade=args.upgrade)
            return 0
        if args.usb:
            mounts = detect_kobo_usb_mounts()
            if not mounts:
                raise RuntimeError('未检测到通过 USB 挂载的 Kobo 设备，请确认 Kobo 已连接电脑并处于 USB 传书模式。')
            install_to_usb_mount(pkg_dir, mounts[0], allow_upgrade=args.upgrade)
            return 0
        if args.ssh:
            install_via_ssh(
                pkg_dir,
                host=args.ssh,
                port=args.port,
                allow_upgrade=args.upgrade,
                known_hosts=args.known_hosts,
                identity=args.identity,
                password_auth=args.password_auth,
                temp_root=temp_root,
            )
            return 0
        if args.output:
            print(f'[4/4] 已在本地生成验证通过的完整安装包: {pkg_dir}（未连接或改动设备）。')
            return 0

        # Interactive one-click flow when run with no mode arguments
        mounts = detect_kobo_usb_mounts()
        if mounts:
            mount = mounts[0]
            has_existing = (mount / '.adds' / 'reeden-kobo').exists()
            mode_label = '保留书库与进度升级' if has_existing else '全新安装'
            if sys.stdin.isatty():
                ans = input(f'\n检测到已通过 USB 挂载的 Kobo ({mount})，按回车立即【{mode_label}】(输入 n 取消): ').strip().lower()
                if ans in ('n', 'no', 'q'):
                    print('已取消设备安装。')
                    return 0
            install_to_usb_mount(pkg_dir, mount, allow_upgrade=True if has_existing else args.upgrade)
            return 0

        if sys.stdin.isatty():
            print('\n当前未检测到 USB 挂载的 Kobo，请选择安装方式：')
            print('  [1] 我现在插上 Kobo USB 数据线，连接后按回车一键安装（推荐，免 SSH）')
            print('  [2] 通过 Wi-Fi SSH 无线一键安装（需在 Kobo 开启 KOReader SSH 或 Reeden SSH）')
            print('  [3] 仅在当前目录生成 package/ 安装包文件夹')
            choice = input('请输入序号 [1/2/3，默认 1]: ').strip() or '1'
            if choice == '1':
                input('请用 USB 线将 Kobo 连接到电脑并点击 Kobo 屏幕上的「连接」，电脑出现 KOBOeReader 盘后按回车...')
                mounts = detect_kobo_usb_mounts()
                if not mounts:
                    raise RuntimeError('仍未检测到 KOBOeReader USB 盘，请确认连接后重试。')
                has_existing = (mounts[0] / '.adds' / 'reeden-kobo').exists()
                install_to_usb_mount(pkg_dir, mounts[0], allow_upgrade=True if has_existing else args.upgrade)
                return 0
            elif choice == '2':
                host = input('请输入 Kobo 的局域网 IP 地址 (如 192.168.1.100): ').strip()
                port = input('请输入 SSH 端口 [KOReader 默认 2222 / Reeden SSH 填 2223]: ').strip() or '2222'
                install_via_ssh(
                    pkg_dir,
                    host=host,
                    port=port,
                    allow_upgrade=True,
                    known_hosts=args.known_hosts,
                    identity=args.identity,
                    password_auth=args.password_auth,
                    temp_root=temp_root,
                )
                return 0

        fallback_out = ROOT / 'package'
        if fallback_out.exists():
            stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
            fallback_out = ROOT / f'package-{stamp}'
        shutil.copytree(pkg_dir, fallback_out)
        print(f'[4/4] 已在本地生成验证通过的完整安装包: {fallback_out}')
        return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'\n❌ 错误: {exc}', file=sys.stderr)
        sys.exit(1)
