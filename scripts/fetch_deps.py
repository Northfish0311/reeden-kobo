#!/usr/bin/env python3
"""Download pinned Debian bullseye ARMHF runtime packages, verifying Packages SHA256."""
import concurrent.futures, hashlib, json, lzma, pathlib, subprocess, urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
CACHE=ROOT.parent/'deps'
CACHE.mkdir(parents=True,exist_ok=True)
manifest=json.loads((ROOT/'vendor/debian-runtime-manifest.json').read_text())
dest=ROOT/'build/debian-runtime';dest.mkdir(parents=True,exist_ok=True)
def fetch(d):
    name=d['name'];p=CACHE/pathlib.Path(d['url']).name
    if not p.exists():
        urllib.request.urlretrieve(d['url'],p)
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['sha256']:raise RuntimeError('checksum mismatch: '+name)
    staging=ROOT/'build/debs'/name;staging.mkdir(parents=True,exist_ok=True)
    subprocess.run(['ar','-x',str(p.resolve())],cwd=staging,check=True,capture_output=True)
    data=next(staging.glob('data.tar.*'))
    subprocess.run(['tar','-xf',str(data),'-C',str(dest)],check=True)
    return d
# Keep extraction sequential: multiple packages can share directory metadata.
manifest=[fetch(d) for d in manifest]
(ROOT/'vendor/debian-runtime-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Verified and extracted',len(manifest),'ARMHF packages')
