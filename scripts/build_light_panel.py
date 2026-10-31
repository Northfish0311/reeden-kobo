#!/usr/bin/env python3
"""Build the fixed-size Clara Colour control row and its UI anchor masks.

The reference is a read-only capture of Reeden 1.43.1's Chinese display panel.
Only the three label masks are embedded; no book pixels are retained.
"""
from pathlib import Path
import argparse
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--reference', required=True)
p.add_argument('--preview-directory', required=True)
a = p.parse_args()
reference = Image.open(a.reference).convert('RGB')
assert reference.size == (1072, 1448)
preview = Path(a.preview_directory)
preview.mkdir(parents=True, exist_ok=True)
font_path = ROOT / 'build/KoboCJKMath-Regular.ttf'
scale = 2

def text(draw, xy, value, size, fill):
    font = ImageFont.truetype(str(font_path), size * scale)
    box = font.getbbox(value)
    x = xy[0] * scale - (box[2] - box[0]) / 2 - box[0]
    y = xy[1] * scale - (box[3] - box[1]) / 2 - box[1]
    draw.text((x, y), value, font=font, fill=fill)

def box(coords):
    return tuple(int(v * scale) for v in coords)

def row(level):
    im = Image.new('L', (1072 * scale, 88 * scale), 255)
    d = ImageDraw.Draw(im)
    text(d, (64, 36), '冷暖', 32, 0)
    for x in (148, 1004):
        d.ellipse(box((x - 35, 1, x + 35, 71)), fill=255, outline=0, width=2 * scale)
        d.line(box((x - 11, 36, x + 11, 36)), fill=0, width=3 * scale)
    d.line(box((1004, 25, 1004, 47)), fill=0, width=3 * scale)
    # Match the existing panel's pill, segments and circular numeric thumb.
    pill = box((200, 1, 952, 71))
    mask = Image.new('L', im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(pill, 36 * scale, fill=255)
    thumb = 236 + level * 68
    fill = Image.new('L', im.size, 255)
    ImageDraw.Draw(fill).rectangle(box((200, 1, thumb, 71)), fill=0)
    im.paste(fill, (0, 0), mask)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(pill, 36 * scale, outline=0, width=2 * scale)
    for i in range(1, 10):
        x = 236 + i * 68
        d.line(box((x, 3, x, 69)), fill=255 if x < thumb else 0, width=2 * scale)
    text(d, (236, 36), '冷', 28, 255 if level > 0 else 0)
    text(d, (916, 36), '暖', 28, 255 if level == 10 else 0)
    d.ellipse(box((thumb - 32, 4, thumb + 32, 68)), fill=255, outline=0, width=2 * scale)
    text(d, (thumb, 36), str(level * 10), 30, 0)
    return im.resize((1072, 88), Image.Resampling.LANCZOS)

blob = bytearray()
offsets = [0]
for level in range(11):
    im = row(level)
    im.save(preview / f'warmth-{level * 10:03}.png')
    raw = im.tobytes()
    i = 0
    while i < len(raw):
        end = i + 1
        while end < len(raw) and raw[end] == raw[i] and end - i < 65535:
            end += 1
        count = end - i
        blob.extend((count & 255, count >> 8, raw[i]))
        i = end
    offsets.append(len(blob))

masks = []
for top in (536, 624, 712):
    bits = [max(reference.getpixel((x, y))) < 128
            for y in range(top, top + 64) for x in range(30, 96)]
    packed = bytearray((len(bits) + 7) // 8)
    for i, bit in enumerate(bits):
        if bit:
            packed[i // 8] |= 1 << (7 - i % 8)
    masks.append(packed)

def array(name, values, kind='uint8_t'):
    lines = [','.join(map(str, values[i:i + 32])) for i in range(0, len(values), 32)]
    return f'static const {kind} {name}[]={{\n' + ',\n'.join(lines) + '\n};\n'

header = '#pragma once\n#include <stdint.h>\n'
header += array('light_row_offsets', offsets, 'uint32_t')
header += array('light_row_rle', blob)
for i, mask in enumerate(masks):
    header += array(f'light_label_{i}', mask)
(ROOT / 'src/light_panel_art.h').write_text(header)

# A review rendering uses exactly the layout that the runtime compositor uses.
im = reference.copy()
im.paste(reference.crop((0, 264, 1072, 620)), (0, 176))
im.paste(row(2).convert('RGB'), (0, 532))
im.save(preview / 'panel-preview.png')
print(f'Built 11 control states, {len(blob)} compressed bytes, and 3 label-only anchors')
