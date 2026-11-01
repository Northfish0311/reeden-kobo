#!/usr/bin/env python3
"""USB 卸载 Reeden Kobo；默认保留完整备份，--purge 删除当前安装及其阅读数据。"""
import argparse
import datetime
import pathlib
import shutil
import sys
import uuid

if sys.version_info < (3, 10):
    sys.exit('需要 Python 3.10 或更新版本，请升级 Python 后重新运行卸载器。')

import install as installer


def checked_child(mount: pathlib.Path, relative: str) -> pathlib.Path:
    """Reject redirection out of the device and symlinked application/menu paths."""
    path = mount
    for part in pathlib.PurePosixPath(relative).parts:
        path = path / part
        if path.is_symlink():
            raise RuntimeError(f'路径含符号链接，为保护其他文件已取消卸载：{path}')
    return path


def uninstall_usb(mount: pathlib.Path, purge: bool = False) -> pathlib.Path | None:
    mount = mount.resolve()
    product, firmware = installer.parse_kobo_product(mount)
    if product != installer.SUPPORTED_PRODUCT:
        raise RuntimeError(f'机型不匹配：{product}（固件 {firmware}），仅支持 Clara Colour（393）。未修改设备。')
    app = checked_child(mount, '.adds/reeden-kobo')
    entry = checked_child(mount, '.adds/nm/reeden-kobo')
    if not app.exists():
        if entry.exists():
            raise RuntimeError('未找到应用目录但存在同名菜单，无法确认归属，未改动。请检查自定义菜单。')
        print('当前未安装 Reeden Kobo；未修改文件。历史备份目录保持不动。')
        return None
    if not app.is_dir():
        raise RuntimeError('应用路径不是目录，已取消卸载。')
    if (app / 'state/active').exists():
        raise RuntimeError('Reeden 会话锁仍存在。请先退出 Reeden；必要时重启回 Kobo 主界面，再连接 USB。未修改设备。')

    # The installed manifest is not trusted as a list of paths to delete.
    # Move only the fixed app directory, and remove only its unmodified menu.
    own_menu = checked_child(mount, '.adds/reeden-kobo/nickelmenu.conf')
    remove_menu = (entry.is_file() and own_menu.is_file()
                   and entry.read_bytes().replace(b'\r\n', b'\n') == own_menu.read_bytes().replace(b'\r\n', b'\n'))
    if entry.exists() and not remove_menu:
        print(f'提示：同名菜单已自定义，保留原文件，请手动移除其中 Reeden 项：{entry}')
    if entry.parent.is_dir():
        for other in sorted(entry.parent.iterdir()):
            if other != entry and other.is_file() and not other.is_symlink():
                if b'/mnt/onboard/.adds/reeden-kobo/' in other.read_bytes():
                    print(f'提示：自定义菜单 {other.name} 引用本应用，文件保留；卸载后请手动移除相关项。')

    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = app.with_name(f'reeden-kobo-uninstalled-{stamp}-{uuid.uuid4().hex[:8]}')
    app.rename(backup)
    try:
        if remove_menu:
            entry.unlink()
    except OSError as exc:
        try:
            backup.rename(app)
        except OSError as rollback_error:
            raise RuntimeError(f'菜单移除失败且无法恢复原路径。全部应用数据仍位于 {backup}，请勿删除。') from rollback_error
        raise RuntimeError('菜单移除失败，已恢复原安装与数据，请检查磁盘后重试。') from exc

    if purge:
        try:
            shutil.rmtree(backup)
        except OSError as exc:
            raise RuntimeError(f'当前安装已移出原路径，但删除未完成；剩余文件位于 {backup}。请检查磁盘后手动处理。') from exc
        print('已删除当前 Reeden Kobo 安装及其中的书籍、笔记、进度和诊断密钥。')
        print('以前的升级/卸载备份、电脑缓存及自定义菜单未删除。')
    else:
        print(f'已停用当前安装，完整应用、书籍、笔记、进度及诊断密钥保留于：\n{backup}')
        print('备份仍占用设备空间。可将该目录复制到电脑保存，确认后再手动删除；其中含私人数据，请勿公开分享。')
    print('安全弹出 USB 后返回 Kobo 主界面。NickelMenu、KOReader、原生书库及固件未由卸载器改动。')
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--usb', action='store_true', help='自动查找 Kobo USB 盘（默认）')
    mode.add_argument('--kobo-mount', help='手动指定 Kobo USB 根目录，例如 E:\\ 或 /Volumes/KOBOeReader')
    parser.add_argument('--purge', action='store_true', help='删除当前安装及其中的全部阅读数据；不删除历史备份')
    parser.add_argument('--yes', action='store_true', help='跳过确认；仅在明确了解所选模式时使用')
    args = parser.parse_args()
    if args.kobo_mount:
        mount = pathlib.Path(args.kobo_mount).expanduser().resolve()
    else:
        mounts = installer.detect_kobo_usb_mounts()
        if not mounts and sys.stdin.isatty():
            input('先退出 Reeden，用 USB 连接 Kobo 并在屏幕点「连接」，电脑出现 KOBOeReader 盘后按回车…')
            mounts = installer.detect_kobo_usb_mounts()
        mount = installer.choose_kobo_usb_mount(mounts)
    # Check the device before asking the user to confirm the operation.
    product, _ = installer.parse_kobo_product(mount)
    if product != installer.SUPPORTED_PRODUCT:
        raise RuntimeError('机型不匹配，仅支持 Clara Colour（393），未修改设备。')
    print(f'目标设备：{mount}')
    print('请先退出 Reeden；若开启过 Reeden SSH，请先重启 Kobo，再连接 USB 卸载。')
    if not args.yes:
        if not sys.stdin.isatty():
            raise RuntimeError('非交互模式未执行卸载；请明确传入 --yes。')
        if not args.purge:
            choice = input('卸载方式：[1] 保留完整备份（默认） [2] 删除当前安装及阅读数据：').strip()
            if choice == '2':
                args.purge = True
            elif choice not in ('', '1'):
                print('已取消，未修改文件。')
                return 0
        if args.purge:
            answer = input('将删除当前应用及其书籍、笔记、进度！输入 DELETE REEDEN 确认：')
            if answer != 'DELETE REEDEN':
                print('已取消，未修改文件。')
                return 0
        else:
            answer = input('移除启动入口并保留完整备份？按回车继续，输入 n 取消：').strip().lower()
            if answer not in ('', 'y', 'yes'):
                print('已取消，未修改文件。')
                return 0
    uninstall_usb(mount, args.purge)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'\n卸载未完成：{exc}', file=sys.stderr)
        sys.exit(1)
