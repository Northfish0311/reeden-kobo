#!/usr/bin/env python3
"""Inspect software pixels. No SSH, image repair, or claim about physical ink.

Python 3.10+, standard library only. Photos need an independently aligned,
exposure-controlled comparison; a screenshot cannot replace that evidence.
"""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path
import struct
import zlib


def png(path, rgb, width, height):
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))
    stride = width * 3
    scan = b''.join(b'\0' + rgb[y * stride:(y + 1) * stride] for y in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress(scan)) + chunk(b'IEND', b''))


def logical_rgb(raw, info):
    w, h, stride = info['width'], info['height'], info['logical_stride']
    if len(raw) != stride * h or stride < w * 4:
        raise ValueError('invalid BGRA length/stride')
    out = bytearray(w * h * 3)
    for y in range(h):
        for x in range(w):
            at = y * stride + x * 4
            out[(y * w + x) * 3:(y * w + x + 1) * 3] = raw[at:at + 3][::-1]
    return out


def fb_rgb(raw, info):
    w, h, stride = info['width'], info['height'], info['fb_stride']
    ox, oy = info['xoffset'], info['yoffset']
    if len(raw) != info['fb_bytes'] or (oy + h) * stride > len(raw) or (ox + w) * 4 > stride:
        raise ValueError('invalid framebuffer length/stride/offset')
    out = bytearray(w * h * 3)
    for y in range(h):
        for x in range(w):
            value = struct.unpack_from('<I', raw, (y + oy) * stride + (x + ox) * 4)[0]
            for c, key in enumerate(('red', 'green', 'blue')):
                offset, length = info[key]
                if not 1 <= length <= 8 or offset < 0 or offset + length > 32:
                    raise ValueError('invalid RGB bitfield')
                channel = (value >> offset) & ((1 << length) - 1)
                channel = channel * 255 // ((1 << length) - 1)
                out[(y * w + x) * 3 + c] = 255 - channel if info['hw_inverted'] else channel
    return out


def conversion_check(target, before, actual, info):
    w, h, stride = info['width'], info['height'], info['fb_stride']
    ox, oy = info['xoffset'], info['yoffset']
    left, top, width, height = info['region']
    if not (0 <= left < w and 0 <= top < h and 0 < width <= w-left and 0 < height <= h-top):
        raise ValueError('invalid updated region')
    expected = bytearray(before)
    for y in range(top, top + height):
        for x in range(left, left + width):
            p = y * info['logical_stride'] + x * 4
            value = 0
            for channel, key in ((target[p+2], 'red'), (target[p+1], 'green'), (target[p], 'blue'), (255, 'alpha')):
                offset, length = info[key]
                if not 0 <= length <= 8 or offset < 0 or offset + length > 32:
                    raise ValueError('invalid bitfield')
                if key != 'alpha' and info['hw_inverted']:
                    channel = 255 - channel
                if length:
                    value |= (channel >> (8-length)) << offset
            struct.pack_into('<I', expected, (y + oy) * stride + (x + ox) * 4, value)
    if len(actual) != len(expected):
        raise ValueError('framebuffer length changed')
    mismatch_bytes = sum(a != b for a, b in zip(actual, expected))
    return {'mismatched_bytes': mismatch_bytes,
            'exact_expected_conversion': mismatch_bytes == 0,
            'checked_bytes_including_padding': len(actual)}


def row_profile(rgb, width, height):
    gray = [(77*rgb[p] + 150*rgb[p+1] + 29*rgb[p+2]) >> 8 for p in range(0, len(rgb), 3)]
    background = collections.Counter(gray).most_common(1)[0][0]
    rows = []
    for y in range(height):
        delta = [abs(v - background) for v in gray[y*width:(y+1)*width]]
        run = longest = 0
        for v in delta:
            run = run + 1 if 1 <= v <= 31 else 0
            longest = max(longest, run)
        rows.append({'y': y, 'non_background': sum(v > 0 for v in delta),
                     'strong_ink': sum(v >= 64 for v in delta),
                     'faint_pixels': sum(1 <= v <= 31 for v in delta),
                     'longest_faint_run': longest, 'contrast_sum': sum(delta)})
    return background, rows


def analyze(capture, output):
    info = json.loads((capture / 'info.json').read_text())
    result = json.loads((capture / 'result.json').read_text())
    if info['schema'] != 1 or result['outcome'] != 'complete' or not result['pixels_complete']:
        raise ValueError('capture incomplete or display transaction failed')
    if not 0 < info['width'] <= 4096 or not 0 < info['height'] <= 4096:
        raise ValueError('invalid dimensions')
    files = {name: (capture / name).read_bytes() for name in
             ('target.bgra', 'fb-before.bin', 'fb-converted.bin', 'fb-complete.bin')}
    if info['old_valid']:
        files['old.bgra'] = (capture / 'old.bgra').read_bytes()
    w, h = info['width'], info['height']
    target = logical_rgb(files['target.bgra'], info)
    visible = fb_rgb(files['fb-converted.bin'], info)
    # Validate completion geometry too, even if bytes compare equal.
    fb_rgb(files['fb-complete.bin'], info)
    output.mkdir(parents=True, exist_ok=False)
    png(output/'target.png', target, w, h)
    png(output/'converted-visible.png', visible, w, h)
    bg, rows = row_profile(target, w, h)
    with (output/'target-rows.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
    if 'old.bgra' in files:
        old = logical_rgb(files['old.bgra'], info)
        png(output/'old.png', old, w, h)
        # Candidate pixels for old-text residuals: old ink where new page is
        # essentially background. This mask alone proves no physical residual.
        mask = bytearray(b'\xff' * (w*h*3)); count = 0
        for p in range(0, len(mask), 3):
            old_g = (77*old[p] + 150*old[p+1] + 29*old[p+2]) >> 8
            new_g = (77*target[p] + 150*target[p+1] + 29*target[p+2]) >> 8
            if abs(old_g-bg) >= 64 and abs(new_g-bg) <= 2:
                mask[p:p+3] = b'\0\0\0'; count += 1
        png(output/'old-only-ink-mask.png', mask, w, h)
    else:
        count = None
    report = {'evidence': 'software-buffers-only', 'physical_shadow_proven': False,
              'conversion': conversion_check(files['target.bgra'], files['fb-before.bin'], files['fb-converted.bin'], info),
              'framebuffer_unchanged_through_completion': files['fb-converted.bin'] == files['fb-complete.bin'],
              'target_background_gray': bg, 'old_only_ink_candidate_pixels': count,
              'target_alpha_histogram': dict(collections.Counter(files['target.bgra'][3:][::4])),
              'hashes': {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
              'limitations': ['Normal antialiasing is gray; faint pixels alone are not a rendering bug.',
                              'Need aligned physical photo and previous-page comparison to classify the shadow.',
                              'A matching conversion does not prove the Flutter target is correct.',
                              'Driver CFA/MDP output buffers and waveform LUT effects are not /dev/fb0 pixels.']}
    (output/'analysis.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = analyze(args.capture, args.output)
    except (ValueError, OSError, KeyError, struct.error) as exc:
        parser.exit(1, f'无法完成像素证据分析：{exc}\n请检查抓取是否完整，并使用新的输出目录。\n')
    print(json.dumps(report, indent=2))
