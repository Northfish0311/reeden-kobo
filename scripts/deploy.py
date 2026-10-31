#!/usr/bin/env python3
"""SSH install with checksums; intentionally contains NO app-launch command."""
import argparse,datetime,pathlib,subprocess,tarfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--host',required=True);p.add_argument('--port',default='2222');p.add_argument('--known-hosts',required=True);p.add_argument('--identity');p.add_argument('--password-auth',action='store_true');a=p.parse_args()
ssh=['ssh','-p',a.port,'-o','ConnectTimeout=8','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(pathlib.Path(a.known_hosts).resolve())]
if a.identity:ssh+=['-i',a.identity]
if a.password_auth:ssh+=['-o','PreferredAuthentications=password','-o','PubkeyAuthentication=no','-o','NumberOfPasswordPrompts=1']
target='root@'+a.host
ssh_read=ssh+['-n',target]
ssh+=[target]
stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S');remote='/mnt/onboard/.adds/.reeden-kobo-stage-'+stamp
archive=ROOT/'build'/('transfer-'+stamp+'.tar.gz')
with tarfile.open(archive,'w:gz',compresslevel=6) as t:
    for path in sorted((ROOT/'package').iterdir()):t.add(path,arcname=path.name,recursive=True)
check='test ! -e /mnt/onboard/.adds/reeden-kobo && test ! -e /mnt/onboard/.adds/nm/reeden-kobo && test -d /mnt/onboard/.adds/nm'
subprocess.run(ssh_read+[check],check=True)
subprocess.run(ssh_read+['mkdir '+remote],check=True)
with archive.open('rb') as f:subprocess.run(ssh+['tar -xzf - -C '+remote],stdin=f,check=True)
result=subprocess.run(ssh_read+['sh '+remote+'/install.sh'],text=True,capture_output=True)
(ROOT/'build/deploy-result.txt').write_text(result.stdout+result.stderr)
print(result.stdout+result.stderr,end='');result.check_returncode();print('No first launch was performed.')
