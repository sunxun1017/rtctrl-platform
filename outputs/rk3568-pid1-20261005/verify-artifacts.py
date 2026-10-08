#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read-only audit of fresh PID1 images; never mount a filesystem or a device."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
LOCKED={
    'image':'e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457',
    'busybox':'514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1',
    'codec':'18fd4744d881e46661d16ad60112f395262b6a6e97ce83f246a4334f6448234c',
    'pty':'5eb5fd9aba8133933dce602d5e0dbd3acf5f1829f700615dc77a67b5f1d0cbda',
}

def sha(data): return hashlib.sha256(data).hexdigest()
def reject(message): raise ValueError(message)
def ordinary(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink!=1: reject('Need ordinary unlinked artifact: '+str(path))
    return path.read_bytes()
def run(argv):
    r=subprocess.run(argv,capture_output=True,text=True,timeout=30)
    if r.returncode: reject('Command rejected: '+repr(argv)+'\n'+r.stdout+r.stderr)
    return r.stdout,r.stderr
def debug(image,command):
    out,err=run(['debugfs','-R',command,str(image)])
    if any(x.strip() and not x.startswith('debugfs ') for x in err.splitlines()): reject('debugfs rejected: '+err)
    return out
def elf(data):
    if len(data)<64 or data[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<HH',data,16)!=(2,183): reject('Need static AArch64 ELF')
    off=struct.unpack_from('<Q',data,32)[0];size,count=struct.unpack_from('<HH',data,54)
    if size<56 or off+size*count>len(data): reject('ELF bounds')
    if any(struct.unpack_from('<I',data,off+i*size)[0] in [2,3] for i in range(count)): reject('ELF has dynamic dependencies')

def allocated(data):
    sb=data[1024:2048]
    inode_count=struct.unpack_from('<I',sb,0)[0]
    blocksize=1024<<struct.unpack_from('<I',sb,24)[0]
    ipg=struct.unpack_from('<I',sb,40)[0]
    inodesize=struct.unpack_from('<H',sb,88)[0]
    if blocksize!=4096 or not 128<=inodesize<=1024 or not 1<=inode_count<=4096 or not ipg: reject('Unexpected ext4 geometry')
    result=[]
    for inode in range(1,inode_count+1):
        group,index=divmod(inode-1,ipg)
        descriptor=blocksize+group*32
        bitmap=struct.unpack_from('<I',data,descriptor+4)[0]*blocksize
        table=struct.unpack_from('<I',data,descriptor+8)[0]*blocksize
        if bitmap+index//8>=len(data) or table+(index+1)*inodesize>len(data): reject('inode/bitmap bounds')
        if data[bitmap+index//8]&(1<<(index%8)):
            pos=table+index*inodesize
            uid=struct.unpack_from('<H',data,pos+2)[0]|struct.unpack_from('<H',data,pos+120)[0]<<16
            gid=struct.unpack_from('<H',data,pos+24)[0]|struct.unpack_from('<H',data,pos+122)[0]<<16
            if uid or gid: reject(f'non-root inode {inode}: {uid}:{gid}')
            result.append(inode)
    return result

def inventory(image):
    result={};queue=['/'];visited=set()
    while queue:
        directory=queue.pop()
        if directory in visited: reject('ext4 directory cycle')
        visited.add(directory)
        for line in debug(image,'ls -p -l '+directory).splitlines():
            if not line.strip(): continue
            fields=line.split('/')
            if len(fields)<7 or not fields[1].isdigit(): reject('ext4 directory syntax')
            inode,mode,uid,gid,name=fields[1:6]
            if inode=='0' and not name: continue
            if name=='..': continue
            if name=='.':
                if directory!='/': continue
                path='/'
            else:
                if not re.fullmatch(r'[A-Za-z0-9_.\[\]+-]+',name): reject('ext4 unsafe name')
                path=directory.rstrip('/')+'/'+name
            if path in result: reject('duplicate path')
            item={'inode':int(inode),'mode':int(mode,8),'uid':int(uid),'gid':int(gid)}
            if item['uid'] or item['gid']: reject('non-root inode '+path)
            result[path]=item
            if name!='.' and stat.S_ISDIR(item['mode']): queue.append(path)
    if len({x['inode'] for x in result.values()})!=len(result): reject('Unexpected ext4 hard links')
    return result

def cpio(data,applets,expected_pid1,expected_rootfs):
    raw=gzip.GzipFile(fileobj=io.BytesIO(data)).read(8*1024*1024+1)
    if len(raw)>8*1024*1024: reject('CPIO size limit')
    members={};offset=0
    while True:
        if offset+110>len(raw) or raw[offset:offset+6]!=b'070701': reject('CPIO signature/bounds')
        fields=[int(raw[offset+6+i*8:offset+14+i*8],16) for i in range(13)]
        offset+=110
        if not 1<=fields[11]<=256 or offset+fields[11]>len(raw): reject('CPIO name bounds')
        name=raw[offset:offset+fields[11]-1].decode()
        if raw[offset+fields[11]-1]: reject('CPIO name terminator')
        offset=(offset+fields[11]+3)&~3
        if offset+fields[6]>len(raw): reject('CPIO content bounds')
        content=raw[offset:offset+fields[6]];offset=(offset+fields[6]+3)&~3
        if fields[2] or fields[3]: reject('non-root CPIO '+name)
        if name=='TRAILER!!!':
            if any(raw[offset:]): reject('CPIO trailer extra data')
            break
        if name in members: reject('CPIO duplicate member')
        members[name]=(fields,content)
    directories={'.','bin','dev','dev/pts','etc','etc/rtctrl','proc','sys','tmp','run','newroot','backing-cache'}
    expected=directories|{'init','bin/busybox','etc/rtctrl/manifest','dev/console','dev/null'}|{'bin/'+x for x in applets}
    if set(members)!=expected: reject('CPIO whitelist mismatch')
    for name,(fields,content) in members.items():
        mode=fields[1]
        if name in directories:
            if mode!=stat.S_IFDIR|(0o1777 if name=='tmp' else 0o755) or content: reject('CPIO directory mode')
        elif name.startswith('bin/') and name!='bin/busybox':
            if mode!=stat.S_IFLNK|0o777 or content!=b'busybox': reject('CPIO applet link')
        elif name=='dev/console':
            if mode!=stat.S_IFCHR|0o600 or fields[9:11]!=[5,1] or content: reject('console device identity')
        elif name=='dev/null':
            if mode!=stat.S_IFCHR|0o666 or fields[9:11]!=[1,3] or content: reject('null device identity')
        elif name in {'init','bin/busybox'}:
            if mode!=stat.S_IFREG|0o755: reject('CPIO executable mode')
            elf(content)
        elif mode!=stat.S_IFREG|0o600: reject('CPIO manifest mode')
    if sha(members['init'][1])!=expected_pid1: reject('CPIO PID1 SHA')
    if sha(members['bin/busybox'][1])!=LOCKED['busybox']: reject('BusyBox SHA')
    text=members['etc/rtctrl/manifest'][1].decode()
    wanted='RTCTRL_PID1_V1\n'+''.join(k+'='+v+'\n' for k,v in [('image',LOCKED['image']),('busybox',LOCKED['busybox']),('pid1',expected_pid1),('rootfs',expected_rootfs),('codec',LOCKED['codec']),('pty',LOCKED['pty'])])
    if text!=wanted: reject('CPIO boot manifest binding')
    return {name:{'mode':fields[1],'uid':fields[2],'gid':fields[3],'sha256':sha(content),'bytes':len(content)} for name,(fields,content) in members.items()}

def verify(folder,out):
    folder=Path(folder).resolve();out=Path(out).resolve()
    if not folder.is_relative_to(HERE/'build') or not out.is_relative_to(HERE/'build') or not re.fullmatch(r'[A-Za-z0-9_./-]+',str(out)): reject('Own simple paths only')
    out.mkdir(parents=True,exist_ok=False)
    report=json.loads(ordinary(folder/'manifest.json'))
    program=ordinary(folder/'pid1');elf(program)
    image=ordinary(folder/'rootfs-pid1.ext4')
    if len(image)!=16*1024*1024: reject('rootfs must be 16 MiB')
    sb=image[1024:2048]
    if struct.unpack_from('<H',sb,56)[0]!=0xef53 or struct.unpack_from('<H',sb,58)[0]!=1 or struct.unpack_from('<I',sb,96)[0]&4: reject('dirty rootfs / needs_recovery')
    if struct.unpack_from('<I',sb,96)[0]&0x80: reject('64bit rootfs outside v1')
    inodes=allocated(image)
    initrd=ordinary(folder/'initramfs-pid1.cpio.gz')
    if len(initrd)>6*1024*1024: reject('initrd size limit')
    applets=(ROOT/'outputs/rk3568-persistent-linux-20261003/busybox-applets.txt').read_text().splitlines()
    if len(applets)!=52: reject('Wrong fixed applet count')
    members=cpio(initrd,applets,sha(program),sha(image))
    for name,data in [('pid1',program),('rootfs-pid1.ext4',image),('initramfs-pid1.cpio.gz',initrd)]:
        metadata=report['artifacts'][name]
        if metadata['sha256']!=sha(data) or metadata['bytes']!=len(data): reject('artifact SHA/size '+name)
    for key,digest in report['source_sha256'].items():
        p=(ROOT/key).resolve()
        if not p.is_relative_to(ROOT) or sha(ordinary(p))!=digest: reject('source changed '+key)
    for inode in inodes:
        text=debug(folder/'rootfs-pid1.ext4','stat <'+str(inode)+'>')
        match=re.search(r'User:\s*(\d+)\s+Group:\s*(\d+)',text)
        if not match or match.groups()!=('0','0'): reject('non-root inode via debugfs '+str(inode))
    found=inventory(folder/'rootfs-pid1.ext4')
    expected={'/'+k:v for k,v in report['rootfs_entries'].items()}
    expected.update({'/':{'type':'directory','mode':0o755},'/lost+found':{'type':'directory','mode':0o700}})
    if set(found)!=set(expected): reject('rootfs whitelist mismatch')
    exports=out/'exports';exports.mkdir()
    for name,item in expected.items():
        types={'directory':stat.S_IFDIR,'file':stat.S_IFREG,'symlink':stat.S_IFLNK}
        if found[name]['mode']!=types[item['type']]|item['mode']: reject('rootfs type/mode '+name)
        if item['type']=='file':
            target=exports/name.strip('/')
            target.parent.mkdir(parents=True,exist_ok=True)
            debug(folder/'rootfs-pid1.ext4','dump '+name+' '+str(target))
            data=ordinary(target)
            if len(data)!=item['bytes'] or sha(data)!=item['sha256']: reject('rootfs payload '+name)
            if data.startswith(b'\x7fELF'): elf(data);target.chmod(0o755)
        elif item['type']=='symlink':
            match=re.search(r'Fast link dest: "(.*)"',debug(folder/'rootfs-pid1.ext4','stat '+name))
            if not match or match[1]!=item['target']: reject('rootfs link target '+name)
    for name,digest in [('bin/pid1',sha(program)),('bin/busybox',LOCKED['busybox']),('usr/bin/codec-test',LOCKED['codec']),('usr/bin/pty-test',LOCKED['pty'])]:
        if sha(ordinary(exports/name))!=digest: reject('rootfs ELF binding '+name)
    output,errors=run(['e2fsck','-fn',str(folder/'rootfs-pid1.ext4')])
    (out/'e2fsck.log').write_text(output+errors)
    qemu=ROOT/'.deps/qemu-user/root/usr/bin/qemu-aarch64-static'
    software={}
    for name in ['usr/bin/codec-test','usr/bin/pty-test']:
        stdout,stderr=run([str(qemu),str(exports/name)])
        software[name]={'exit':0,'stdout':stdout,'stderr':stderr}
    actual,errors=run([str(qemu),str(exports/'bin/busybox'),'--list'])
    if actual.splitlines()!=applets: reject('Actual BusyBox inventory')
    evidence={'status':'PID1_ARTIFACTS_VERIFIED','board_tested':False,'mount_or_pivot_executed':False,'allocated_inode_count':len(inodes),'all_allocated_inodes_uid_gid_zero':True,'rootfs_path_count':len(found),'cpio_member_count':len(members),'ordinary_artifact_sha256':{name:sha(data) for name,data in [('pid1',program),('rootfs-pid1.ext4',image),('initramfs-pid1.cpio.gz',initrd)]},'qemu_software':software,'auditor_sha256':sha(Path(__file__).read_bytes())}
    (out/'audit.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence,indent=2))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--production',required=True)
    p.add_argument('--out',required=True)
    a=p.parse_args()
    try: verify(a.production,a.out)
    except (ValueError,OSError,KeyError,UnicodeError,struct.error) as error: p.exit(1,'PID1_ARTIFACTS_REJECTED: '+str(error)+'\n')

if __name__=='__main__': main()
