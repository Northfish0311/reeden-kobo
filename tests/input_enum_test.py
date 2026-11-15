"""The diagnostic can identify candidates, not prove that evdev was grabbed."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def node(number, bus='0019', power=True):
    keys = '100000 0 0 0' if power else '0'  # KEY_POWER, 32-bit Kobo
    return (f'I: Bus={bus} Vendor=0000 Product=0000 Version=0000\n'
            f'N: Name="test"\nH: Handlers=event{number}\nB: KEY={keys}\n\n')


@unittest.skipIf(os.name == 'nt', 'uses the POSIX diagnostic')
class EnumTest(unittest.TestCase):
    def test_candidates_not_grabs(self):
        cases = [
            (node(0) + node(2), 'event1', 'CANDIDATE event2 '),
            (node(7) + node(4) + node(0), 'event4', 'CANDIDATE event0 '),
            (node(1) + node(3, '0003') + node(32) + node(2, power=False),
             'event1', 'STOP  no eligible KEY_POWER candidate'),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            devices, out = Path(tmp) / 'devices', Path(tmp) / 'report'
            for data, touch, expected in cases:
                with self.subTest(expected=expected):
                    devices.write_text(data, encoding='ascii')
                    env = dict(os.environ, REEDEN_TOUCH='/dev/input/' + touch,
                               INPUT_ENUM_DEVICES=str(devices), INPUT_ENUM_OUT=str(out))
                    subprocess.run(['sh', str(ROOT / 'tools/kobo-input-enum.sh')],
                                   env=env, capture_output=True, check=True)
                    self.assertIn(expected, out.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
