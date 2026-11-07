"""Read synthetic suspend logs; no real USB volume or Kobo is used."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import standby_report as report

STAMP = 'Sat Nov  7 22:40:12 CST 2026'


def phase(name, at, pid=42):
    return f'[power] phase={name} uptime={at} pid={pid} {STAMP}'


def result(*events):
    return report.recent_attempts([phase('preparing', 100), *events])[-1].describe()


class StandbyReportTest(unittest.TestCase):
    def test_guard_is_not_evidence_of_attached_usb(self):
        reason = result('[power] charging: retaining screen lock without kernel suspend',
                        '[power] helper exiting=3 ' + STAMP)
        self.assertIn('未请求内核休眠', reason)
        self.assertIn('不证明当时插着 USB', reason)

    def test_preparation_failures(self):
        self.assertIn('等待显示空闲超时', result('[power] display did not become idle'))
        self.assertIn('闹钟保护', result('[power] existing alarm: suspend cancelled'))
        self.assertIn('准备阶段退出', result('[power] helper exiting=4 ' + STAMP))

    def test_short_and_long_intervals_are_not_current_draw(self):
        for seconds in (2, 8 * 3600):
            with self.subTest(seconds=seconds):
                reason = result('[power] entering mem ' + STAMP, phase('suspended', 120),
                                phase('resuming', 120 + seconds), '[power] mem returned=0 ' + STAMP)
                self.assertIn(f'相隔约 {seconds} 秒', reason)

    def test_error_missing_return_and_bad_clock(self):
        self.assertIn('返回错误 1', result('[power] entering mem ' + STAMP, '[power] mem returned=1 ' + STAMP))
        self.assertIn('没有返回结果', result('[power] entering mem ' + STAMP))
        self.assertIn('没有同一次请求可用的前后时间', result('[power] entering mem ' + STAMP,
                      phase('suspended', 120), phase('resuming', 80), '[power] mem returned=0 ' + STAMP))

    def test_unrelated_helpers_never_supply_a_return(self):
        self.assertIn('没有返回结果', result('[power] entering mem ' + STAMP, phase('suspended', 120),
                      phase('resuming', 144, pid=43), '[power] mem returned=0 ' + STAMP))
        attempts = report.recent_attempts([phase('preparing', 300, pid) for pid in range(6)])
        self.assertEqual([a.pid for a in attempts], ['3', '4', '5'])

    def test_bounded_tail_and_partial_first_line(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'power.log'
            path.write_bytes((phase('preparing', 10) + '\n').encode() + b'x' * report.TAIL_LIMIT
                             + ('\n' + phase('preparing', 100) + '\n[power] display did not become idle\n').encode())
            lines = report.log_report(path)
            self.assertEqual(len(lines), 1)
            self.assertIn('等待显示空闲超时', lines[0])

    def test_no_data_does_not_imply_no_sleep(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'power.log'
            self.assertIn('不能判断', report.log_report(log)[0])
            log.write_text('unrelated message\n', encoding='utf-8')
            self.assertIn('不证明', report.log_report(log)[0])

    def test_device_check_is_read_only_and_redacted(self):
        with tempfile.TemporaryDirectory() as temp:
            mount = Path(temp)
            app = mount / '.adds/reeden-kobo'
            (mount / '.kobo').mkdir()
            (mount / '.kobo/version').write_text('private-serial,X,4.46.23836,000-393\n')
            (app / 'logs').mkdir(parents=True)
            (app / 'state').mkdir()
            (app / 'logs/power.log').write_text(phase('preparing', 12) + '\nprivate-usermessage\n'
                                                + '[power] existing alarm: suspend cancelled\n')
            (app / 'state/power-test').touch()
            def snapshot():
                return {p.relative_to(mount): (p.stat().st_mtime_ns, p.read_bytes())
                        for p in mount.rglob('*') if p.is_file()}
            before = snapshot()
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(report.main(['--kobo-mount', str(mount)]), 0)
            self.assertIn('测试唤醒闹钟标记', stdout.getvalue())
            self.assertIn(STAMP, stdout.getvalue())
            self.assertNotIn('private-', stdout.getvalue())
            self.assertEqual(snapshot(), before)


if __name__ == '__main__':
    unittest.main()
