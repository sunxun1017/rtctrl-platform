#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tamper real ordinary images; require independent auditor to reject them."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

HERE=Path(__file__).resolve().parent

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def inode_offset(data,inode):
    sb=data[1024:2048]
    blocksize=1024<<struct.unpack_from('<I',sb,24)[0]
    ipg=struct.unpack_from('<I',sb,40)[0]
    size=struct.unpack_from('<H',sb,88)[0]
    group,index=divmod(inode-1,ipg)
    table=struct.unpack_from('<I',data,blocksize+group*32+8)[0]
    return table*blocksize+index*size

def cpio_positions(raw):
    offset=0
    while True:
        header=offset
        fields=[int(raw[offset+6+i*8:offset+14+i*8],16) for i in range(13)]
        name_start=offset+110
        name=bytes(raw[name_start:name_start+fields[11]-1]).decode()
        offset=(name_start+fields[11]+3)&~3
        data_start=offset
        offset=(offset+fields[6]+3)&~3
        yield name,header,name_start,data_start,fields
        if name=='TRAILER!!!': break

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--production',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--baseline',action='store_true')
    a=p.parse_args()
    source=Path(a.production).resolve();out=Path(a.out).resolve()
    if not source.is_relative_to(HERE/'build') or not out.is_relative_to(HERE/'build'): p.error('Own ordinary files only')
    out.mkdir(parents=True,exist_ok=False)
    auditor=HERE/'verify-artifacts.py'
    if a.baseline:
        auditor=out/'missing-auditor.py'
        auditor.write_text('print("PID1_ARTIFACTS_VERIFIED")\n')
    names=['clean','corrupt-rootfs','reserved-inode-uid','file-inode-gid','dirty-rootfs','needs-recovery','wrong-elf-machine','symlink-image','cpio-nonroot','cpio-unapproved-member','cpio-wrong-console','cpio-corrupt-busybox']
    cases=[]
    for name in names:
        folder=out/name;folder.mkdir()
        for file in ['pid1','rootfs-pid1.ext4','initramfs-pid1.cpio.gz','manifest.json']:
            shutil.copyfile(source/file,folder/file)
        manifest=json.loads((folder/'manifest.json').read_text())
        if name=='corrupt-rootfs':
            path=folder/'rootfs-pid1.ext4';data=bytearray(path.read_bytes());data[12345]^=0x80;path.write_bytes(data)
        if name in ['reserved-inode-uid','file-inode-gid','dirty-rootfs','needs-recovery']:
            path=folder/'rootfs-pid1.ext4';data=bytearray(path.read_bytes())
            if name=='reserved-inode-uid': struct.pack_into('<H',data,inode_offset(data,1)+2,1000)
            if name=='file-inode-gid': struct.pack_into('<H',data,inode_offset(data,12)+24,1000)
            if name=='dirty-rootfs': struct.pack_into('<H',data,1082,2)
            if name=='needs-recovery': struct.pack_into('<I',data,1120,struct.unpack_from('<I',data,1120)[0]|4)
            path.write_bytes(data);manifest['artifacts'][path.name]['sha256']=digest(path)
        if name=='wrong-elf-machine':
            path=folder/'pid1';data=bytearray(path.read_bytes());struct.pack_into('<H',data,18,62);path.write_bytes(data);manifest['artifacts'][path.name]['sha256']=digest(path)
        if name=='symlink-image':
            path=folder/'rootfs-pid1.ext4';path.unlink();path.symlink_to(source/path.name)
        if name.startswith('cpio-'):
            path=folder/'initramfs-pid1.cpio.gz';raw=bytearray(gzip.decompress(path.read_bytes()))
            for member,header,name_start,data_start,fields in cpio_positions(raw):
                if name=='cpio-nonroot' and member=='bin/busybox': raw[header+22:header+30]=b'000003e8'
                if name=='cpio-unapproved-member' and member=='bin/ip': raw[name_start:name_start+6]=b'bin/xx'
                if name=='cpio-wrong-console' and member=='dev/console': raw[header+78:header+86]=b'000000b3'
                if name=='cpio-corrupt-busybox' and member=='bin/busybox': raw[data_start+100]^=0x80
            path.write_bytes(gzip.compress(raw,compresslevel=9,mtime=0));manifest['artifacts'][path.name].update(sha256=digest(path),bytes=path.stat().st_size)
        (folder/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        r=subprocess.run([sys.executable,str(auditor),'--production',str(folder),'--out',str(folder/'audit')],capture_output=True,text=True,timeout=30)
        passed=(r.returncode==0 and 'PID1_ARTIFACTS_VERIFIED' in r.stdout) if name=='clean' else r.returncode!=0
        expected={'reserved-inode-uid':'non-root inode','file-inode-gid':'non-root inode','dirty-rootfs':'dirty rootfs','needs-recovery':'dirty rootfs','wrong-elf-machine':'AArch64 ELF','cpio-nonroot':'non-root CPIO','cpio-unapproved-member':'CPIO whitelist','cpio-wrong-console':'console device','cpio-corrupt-busybox':'BusyBox SHA'}
        if name in expected and not a.baseline: passed &= expected[name] in r.stderr
        cases.append({'name':name,'passed':bool(passed),'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
    report={'baseline':a.baseline,'total':len(cases),'passed':sum(x['passed'] for x in cases),'cases':cases,'auditor_sha':digest(auditor)}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f"{report['passed']}/{report['total']} artifact integrity")
    return 0 if report['passed']==report['total'] else 1

if __name__=='__main__': sys.exit(main())
