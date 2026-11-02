#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('pixels', Path(__file__).resolve().parents[1]/'scripts/analyze-frame-evidence.py')
pixels = importlib.util.module_from_spec(spec); spec.loader.exec_module(pixels)


class PixelEvidenceTest(unittest.TestCase):
    def fixture(self, root, night=False):
        info = dict(schema=1, width=4, height=4, logical_stride=20, fb_stride=28, xoffset=1, yoffset=1,
                    fb_bytes=28*6, red=[0,8], green=[8,8], blue=[16,8], alpha=[24,8],
                    region=[0,0,4,4], hw_inverted=night, old_valid=True)
        target = bytearray([0 if night else 255]*80)
        for x, value in enumerate((0,1,128,255)):
            target[20+x*4:20+x*4+4] = bytes((value,value,value,255))
        old = bytearray([0 if night else 255]*80)
        old[40:44] = bytes((255 if night else 0,)*3+(255,))
        before = bytearray([0x5A]*info['fb_bytes']); fb = bytearray(before)
        for y in range(4):
            for x in range(4):
                b,g,r = target[y*20+x*4:y*20+x*4+3]
                if night:
                    r,g,b = 255-r,255-g,255-b
                struct.pack_into('<I', fb, (y+1)*28+(x+1)*4, r | g<<8 | b<<16 | 255<<24)
        root.mkdir()
        (root/'info.json').write_text(json.dumps(info))
        (root/'result.json').write_text(json.dumps(dict(outcome='complete', pixels_complete=True)))
        for name, raw in [('target.bgra',target),('old.bgra',old),('fb-before.bin',before),('fb-converted.bin',fb),('fb-complete.bin',fb)]:
            (root/name).write_bytes(raw)
        return info, target, before, fb

    def test_day_and_night(self):
        for night in (False,True):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); self.fixture(root/'capture',night)
                report=pixels.analyze(root/'capture',root/'analysis')
                self.assertTrue(report['conversion']['exact_expected_conversion'])
                self.assertTrue(report['framebuffer_unchanged_through_completion'])
                self.assertGreater(report['old_only_ink_candidate_pixels'],0)
                self.assertFalse(report['physical_shadow_proven'])

    def test_conversion_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); info,target,before,fb=self.fixture(root/'capture')
            fb[28*3+4]=128  # Manufacture a gray shadow in the software framebuffer.
            (root/'capture/fb-converted.bin').write_bytes(fb)
            report=pixels.analyze(root/'capture',root/'analysis')
            self.assertFalse(report['conversion']['exact_expected_conversion'])
            self.assertFalse(report['framebuffer_unchanged_through_completion'])

    def test_shadow_already_in_logical_frame(self):
        rgb=bytes([255,255,255]*4+[240,240,240]*4+[255,255,255]*4)
        background,rows=pixels.row_profile(rgb,4,3)
        self.assertEqual(background,255)
        self.assertEqual(rows[1]['longest_faint_run'],4)
        self.assertEqual(rows[2]['faint_pixels'],0)

    def test_channel_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            info,target,before,fb=self.fixture(Path(tmp)/'capture')
            info['red'],info['blue']=[16,8],[0,8]
            target[0:4]=bytes((40,80,160,255));struct.pack_into('<I',fb,32,40|80<<8|160<<16|255<<24)
            self.assertTrue(pixels.conversion_check(target,before,fb,info)['exact_expected_conversion'])
            self.assertEqual(pixels.fb_rgb(fb,info)[:3],bytes((160,80,40)))

    def test_incomplete_and_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); self.fixture(root/'capture')
            (root/'capture/result.json').write_text(json.dumps(dict(outcome='complete-error',pixels_complete=True)))
            with self.assertRaises(ValueError): pixels.analyze(root/'capture',root/'analysis')
            (root/'capture/result.json').write_text(json.dumps(dict(outcome='complete',pixels_complete=True)))
            (root/'capture/fb-converted.bin').write_bytes(b'bad')
            with self.assertRaises(ValueError): pixels.analyze(root/'capture',root/'analysis')


if __name__=='__main__':
    unittest.main()
