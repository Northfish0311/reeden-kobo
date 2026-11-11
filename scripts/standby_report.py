#!/usr/bin/env python3
"""Summarize existing Kobo suspend logs on the computer, without changing the device."""
import argparse
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import sys

PHASE = re.compile(r'^\[power\] phase=(\w+) uptime=(\d{1,18}) pid=(\d{1,10})(?: |$)')
DATE = re.compile(r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) [A-Z][a-z]{2} +\d{1,2} \d\d:\d\d:\d\d [\w+:-]{1,12} \d{4}$')
SUPPLY = r'(Discharging|Charging|Full|NotCharging|Unknown|unknown|unreadable) external=(on|off|unknown|unexposed)'
TAIL_LIMIT = 512 * 1024


@dataclass
class Attempt:
    pid: str
    date: str
    requested: bool = False
    suspended: int | None = None
    resuming: int | None = None
    result: int | None = None
    reason: str = ''
    before_percent: int | None = None
    after_percent: int | None = None

    def describe(self) -> str:
        if not self.requested:
            return self.reason or '没有完整记录表明发起了内核休眠请求。'
        if self.result is None:
            return '记录了休眠请求，但没有返回结果；日志可能不完整。'
        if self.result:
            return f'内核休眠请求返回错误 {self.result}。'
        if self.suspended is not None and self.resuming is not None and self.resuming >= self.suspended:
            seconds = self.resuming - self.suspended
            interval = f'{seconds} 秒'
            if seconds >= 3600:
                interval += f'（{seconds // 3600} 小时 {seconds % 3600 // 60} 分）'
            charge = ''
            if self.before_percent is not None and self.after_percent is not None:
                charge = f' 电池读数 {self.before_percent}% → {self.after_percent}%。'
            return f'休眠请求返回 0，请求前后相隔约 {interval}。{charge}'
        return '休眠请求返回 0，没有同一次请求可用的前后时间。'


def recent_attempts(lines):
    recent = deque(maxlen=3)
    current = None
    for line in lines:
        phase = PHASE.match(line)
        if phase:
            name, uptime, pid = phase.groups()
            if name == 'preparing':
                stamp = DATE.search(line)
                current = Attempt(pid, stamp[0] if stamp else '日期未识别')
                recent.append(current)
            elif current:
                if pid != current.pid:
                    current = None  # Never pair markers from different helpers.
                elif name == 'suspended' and current.requested:
                    current.suspended = int(uptime)
                elif name == 'resuming' and current.suspended is not None:
                    current.resuming = int(uptime)
            continue
        if current is None:
            continue
        if line.startswith('[power] entering mem '):
            current.requested = True
        elif m := re.match(r'^\[power\] mem returned=(\d{1,3})(?: |$)', line):
            if current.requested:
                current.result = int(m[1])
        elif line == '[power] charging: retaining screen lock without kernel suspend':
            current.reason = '电池状态保护：只锁屏，未请求内核休眠。这条旧日志不证明当时插着 USB。'
        elif m := re.fullmatch(r'\[power\] screen-only: supply guard battery=' + SUPPLY, line):
            current.reason = f'供电保护：电池报告 {m[1]}，外部电源读数 {m[2]}，未请求内核休眠。'
        elif m := re.fullmatch(r'\[power\] sample=(before_mem|after_mem) battery=' + SUPPLY + r' capacity=(\d{1,3})', line):
            if int(m[4]) <= 100:
                if m[1] == 'before_mem':
                    current.before_percent = int(m[4])
                elif current.result is not None:
                    current.after_percent = int(m[4])
        elif line == '[power] display did not become idle':
            current.reason = '等待显示空闲超时，未请求内核休眠。'
        elif line == '[power] existing alarm: suspend cancelled':
            current.reason = '测试闹钟保护取消了请求。'
        elif line == '[power] Wi-Fi could not be suspended':
            current.reason = '无线接口未能交还，未请求内核休眠。'
        elif m := re.match(r'^\[power\] helper exiting=(\d{1,3})(?: |$)', line):
            if not current.requested and not current.reason and int(m[1]) != 0:
                current.reason = f'准备阶段退出（代码 {m[1]}），没有记录内核休眠请求。'
            current = None
    return recent


def log_tail(path):
    with path.open('rb') as log:
        offset = max(0, log.seek(0, 2) - TAIL_LIMIT)
        log.seek(offset)
        tail = log.read(TAIL_LIMIT)
    if offset:
        tail = tail.partition(b'\n')[2]  # Ignore a potentially partial first line.
    return tail.decode('utf-8', errors='replace').splitlines()


def log_report(path):
    if not path.is_file():
        return ['未找到 power.log，不能判断该次锁屏。']
    attempts = recent_attempts(log_tail(path))
    if not attempts:
        return ['日志末尾没有可识别的休眠尝试；这不证明设备没有睡过。']
    return [f'{a.date}：{a.describe()}' for a in attempts]


def cover_report(path):
    if not path.is_file():
        return []
    edges = deque(maxlen=4)
    mode = None
    for line in log_tail(path):
        if match := re.fullmatch(r'\[cover\] candidate event\d+ (SW_LID|internal KEY_F1)', line):
            mode = '已识别 ' + match[1]
        elif line == '[cover] no supported internal lid input; power key remains available':
            mode = '未识别到受支持的盖传感器'
        elif line in ('[cover] disabled by user preference',
                      '[cover] extra listener disabled; existing power handling unchanged'):
            mode = '已手动关闭保护盖监听'
        elif match := re.fullmatch(r'\[power\] phase=cover-(closed|opened) wall=(\d{1,10}) mono_ms=\d+', line):
            stamp = datetime.fromtimestamp(int(match[2]), timezone.utc).astimezone()
            edges.append(stamp.isoformat(timespec='seconds') + (' 合盖' if match[1]=='closed' else ' 开盖'))
    if not mode and not edges:
        return []
    return [f'{path.name}：{mode or "模式未知"}；' + ('；'.join(edges) or '没有记录到开合边沿')]


def under_mount(mount, name):
    path = mount / name
    resolved = path.resolve()
    if resolved != path or not resolved.is_relative_to(mount):
        raise ValueError('Kobo 路径发生重定向，已停止检查。')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description='只读查看最近三次有记录的 Kobo 休眠尝试，不联网、不写设备。')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--log', type=Path, help='分析电脑上已复制的 power.log，不需要连接设备')
    group.add_argument('--kobo-mount', type=Path, help='Kobo USB 盘根目录；不指定时自动识别')
    args = parser.parse_args(argv)
    flags = []
    try:
        if args.log is not None:
            log = args.log
        else:
            sys.dont_write_bytecode = True
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from install import choose_kobo_usb_mount, detect_kobo_usb_mounts, parse_kobo_product, SUPPORTED_PRODUCT
            mount = (args.kobo_mount or choose_kobo_usb_mount(detect_kobo_usb_mounts())).resolve()
            under_mount(mount, '.kobo/version')
            if parse_kobo_product(mount)[0] != SUPPORTED_PRODUCT:
                raise ValueError('不是受支持的 Kobo Clara Colour (393)。')
            log = under_mount(mount, '.adds/reeden-kobo/logs/power.log')
            cover_lines = []
            for filename in ('previous.log', 'current.log'):
                cover_lines.extend(cover_report(under_mount(mount, '.adds/reeden-kobo/logs/' + filename)))
            flags.extend(cover_lines or ['没有盖事件记录；旧版没有记录它们，不能据此判断你没有合盖。'])
            for name, label in (('power-screen-only', '只锁屏模式'), ('power-test', '测试唤醒闹钟')):
                if under_mount(mount, f'.adds/reeden-kobo/state/{name}').exists():
                    flags.append(f'当前有{label}标记；不代表此前锁屏时也存在。')
        for line in [*log_report(log), *flags]:
            print(line)
        print('请对照实际锁屏和唤醒时间。以上是脚本尝试记录，不是最低功耗驻留时间或耗电量。')
    except (OSError, RuntimeError, ValueError) as exc:
        print(f'无法完成只读检查：{exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
