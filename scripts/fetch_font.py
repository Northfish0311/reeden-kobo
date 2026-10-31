#!/usr/bin/env python3
import hashlib,json,pathlib,urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
d=json.loads((ROOT/'vendor/font-manifest.json').read_text());dest=ROOT.parent/'deps/NotoSansCJKsc-Regular.otf';dest.parent.mkdir(parents=True,exist_ok=True)
if not dest.exists():urllib.request.urlretrieve(d['url'],dest)
assert hashlib.sha256(dest.read_bytes()).hexdigest()==d['sha256'],'Font checksum mismatch'
print('Verified Noto Sans CJK SC Regular')
