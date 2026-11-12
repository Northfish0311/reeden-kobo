"""Keep the installer, download instructions and release notes on one version."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTest(unittest.TestCase):
    def test_current_downloads_match_installer(self):
        tree = ast.parse((ROOT / 'install.py').read_text(encoding='utf-8'))
        version = next(ast.literal_eval(n.value) for n in tree.body
                       if isinstance(n, ast.Assign) and any(
                           isinstance(t, ast.Name) and t.id == 'PORT_VERSION' for t in n.targets))
        tag = 'v' + version
        for name in ('README.md', 'docs/安装与卸载.md'):
            with self.subTest(name=name):
                text = (ROOT / name).read_text(encoding='utf-8')
                self.assertIn('releases/tag/' + tag, text)
                self.assertIn(f'Reeden-Kobo-Adapter-{tag}-OneClick.zip', text)
        notes = (ROOT / 'docs' / 'releases' / (tag + '.md')).read_text(encoding='utf-8')
        self.assertIn(f'Reeden-Kobo-Adapter-{tag}-OneClick.zip', notes)
        self.assertIn(f'Reeden-Kobo-{tag}-Source.zip', notes)
        self.assertIn('默认关闭', notes)
        self.assertIn('未完成真实 Kobo', notes)
        for name in ('一键更新-Windows.bat', '一键更新-macOS.command', '一键更新-Linux.sh'):
            self.assertTrue((ROOT / name).is_file(), name)
            self.assertIn(name, notes)


if __name__ == '__main__':
    unittest.main()
