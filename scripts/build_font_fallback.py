#!/usr/bin/env python3
"""Build the Kobo UI fallback using fontTools 4.68.0 (SIL OFL sources).

Usage: python build_font_fallback.py NotoSansSC-wght.ttf NotoSansMath-Regular.ttf output.ttf
CJK input: https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf
The Math input comes from the unchanged official Reeden assets.
"""
from copy import deepcopy
from pathlib import Path
import hashlib, json, sys, tempfile
from fontTools.merge import Merger
from fontTools.ttLib import TTFont, newTable
from fontTools.varLib.instancer import instantiateVariableFont

def checked(path, digest):
    path = Path(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, f'Unexpected input: {path}'
    return TTFont(path)

cjk = checked(sys.argv[1], 'a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da')
math = checked(sys.argv[2], 'b4a1dfdbfa13b4755e5eac20cb25c1d17ed5a745ceb89639595e8cf45a2b1e07')
cjk = instantiateVariableFont(cjk, {'wght': 400}, inplace=False)
assert cjk['head'].unitsPerEm == math['head'].unitsPerEm == 1000
expected = set(cjk.getBestCmap()) | set(math.getBestCmap())
# The merger requires vertical metrics in both inputs. Math has none; give
# its glyphs an em advance and the CJK vertical origin without altering hmtx.
math['vhea'] = deepcopy(cjk['vhea'])
math['vhea'].numberOfVMetrics = len(math.getGlyphOrder())
math['vmtx'] = newTable('vmtx')
math['vmtx'].metrics = {g: (1000, 880 - getattr(math['glyf'][g], 'yMax', 0)) for g in math.getGlyphOrder()}
with tempfile.TemporaryDirectory() as tmp:
    a, b = Path(tmp) / 'cjk.ttf', Path(tmp) / 'math.ttf'
    cjk.save(a); math.save(b)
    merged = Merger().merge([str(a), str(b)])
for name_id, value in [(1, 'Kobo CJK Math'), (2, 'Regular'), (4, 'Kobo CJK Math Regular'),
                       (6, 'KoboCJKMath-Regular'), (16, 'Kobo CJK Math'), (17, 'Regular')]:
    for platform, encoding, language in [(3, 1, 0x409), (1, 0, 0)]:
        merged['name'].setName(value, name_id, platform, encoding, language)
output = Path(sys.argv[3]); output.parent.mkdir(parents=True, exist_ok=True)
merged.save(output)
loaded = TTFont(output)
assert expected <= set(loaded.getBestCmap()), 'Unicode coverage lost'
assert 'MATH' in loaded and 'GSUB' in loaded and 'GPOS' in loaded
print(json.dumps({'file': str(output), 'unicode': len(loaded.getBestCmap()),
                  'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}))
