#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compile a fresh static ELF and build/audit fresh ordinary image files only."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import uuid
import zlib

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SIZE=16*1024*1024
LOCKED={
    'image':('outputs/rk3568-rcu-reset-20261004/Image','e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457'),
    'busybox':('outputs/rk3568-rng-network-20261004/build/busybox-module-options/v1/busybox','514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1'),
    'codec':('outputs/rk3568-mcu-baseline-20261003/private/source-tests/rtctrl_patchx_codec_test','18fd4744d881e46661d16ad60112f395262b6a6e97ce83f246a4334f6448234c'),
    'pty':('outputs/rk3568-mcu-baseline-20261003/private/source-tests/rtctrl_patchx_pty_test','5eb5fd9aba8133933dce602d5e0dbd3acf5f1829f700615dc77a67b5f1d0cbda'),
    'config':('outputs/rk3568-rcu-reset-20261004/kernel.config','1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912'),
    'applets':('outputs/rk3568-persistent-linux-20261003/busybox-applets.txt','6e2d74e972829be2fcacb329bcddd2b5d026a138a76031ae1ad9e5b3dd96eedf'),
    'busybox_config':('outputs/rk3568-rng-network-20261004/build/busybox-module-options/v1/busybox-1.36.1/.config','a7855725b2cf093f69174c760ec180e8762f744b537795806196757b0a2d901d'),
    'busybox_archive':('.deps/busybox-firstboot/busybox-1.36.1.tar.bz2','b8cc24c9574d809e7279c3be349795c5d5ceb6fdf19ca709f80cde50e47de314'),
}
DIRECTORIES=['bin','dev','dev/pts','etc','etc/rtctrl','proc','sys','tmp','run','usr','usr/bin','usr/share','usr/share/licenses','.ram-return','.backing-cache']

def sha(data): return hashlib.sha256(data).hexdigest()
def run(argv, **kw):
    r=subprocess.run(argv,capture_output=True,text=True,**kw)
    if r.returncode:
        raise RuntimeError('Command failed: '+repr(argv)+'\n'+r.stdout+r.stderr)
    return r.stdout+r.stderr

def read_input(path, expected=None):
    p=ROOT/path
    if p.is_symlink() or not p.is_file(): raise ValueError('Need ordinary input: '+path)
    data=p.read_bytes()
    if expected and sha(data)!=expected: raise ValueError('Locked SHA mismatch: '+path)
    return data

def elf(data):
    if len(data)<64 or data[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<HH',data,16)!=(2,183):
        raise ValueError('Need static executable AArch64 ELF64')
    phoff=struct.unpack_from('<Q',data,32)[0]
    phsize,phnum=struct.unpack_from('<HH',data,54)
    if phsize<56 or phoff+phsize*phnum>len(data): raise ValueError('ELF program bounds')
    for i in range(phnum):
        kind=struct.unpack_from('<I',data,phoff+phsize*i)[0]
        if kind in (2,3): raise ValueError('Dynamic segment/interpreter is forbidden')

def allocated_inodes(data):
    sb=data[1024:2048]
    u32=lambda n:struct.unpack_from('<I',sb,n)[0]
    count,blocks,first,bpg,ipg=u32(0),u32(4),u32(20),u32(32),u32(40)
    blocksize=1024<<u32(24)
    inode_size=struct.unpack_from('<H',sb,88)[0]
    incompat=u32(96)
    if incompat&0x80: raise ValueError('64bit image is outside v1 audit contract')
    if blocksize!=4096 or inode_size<128 or count>4096: raise ValueError('Unexpected ext4 geometry')
    groups=(blocks-first+bpg-1)//bpg
    table=(2 if blocksize==1024 else 1)*blocksize
    result=[]
    for group in range(groups):
        descriptor=table+group*32
        bitmap,itable=struct.unpack_from('<II',data,descriptor+4)
        for index in range(min(ipg,count-group*ipg)):
            if data[bitmap*blocksize+index//8]&(1<<(index%8)):
                inode=group*ipg+index+1
                offset=itable*blocksize+index*inode_size
                lo_uid=struct.unpack_from('<H',data,offset+2)[0]
                lo_gid=struct.unpack_from('<H',data,offset+24)[0]
                hi_uid,hi_gid=struct.unpack_from('<HH',data,offset+120)
                result.append({'inode':inode,'uid':lo_uid+(hi_uid<<16),'gid':lo_gid+(hi_gid<<16),'mode':struct.unpack_from('<H',data,offset)[0]})
    return result

def pack_cpio(specs):
    archive=bytearray()
    def member(name,item,inode):
        kind=item['type']
        content=item.get('data',item.get('target','').encode())
        permissions=item['mode']
        mode=permissions|({'directory':stat.S_IFDIR,'file':stat.S_IFREG,'symlink':stat.S_IFLNK,'character':stat.S_IFCHR}[kind])
        fields=[inode,mode,0,0,2 if kind=='directory' else 1,1700000000,len(content),0,0,item.get('major',0),item.get('minor',0),len(name.encode())+1,0]
        archive.extend(b'070701'+''.join(f'{n:08x}' for n in fields).encode())
        archive.extend(name.encode()+b'\0')
        archive.extend(b'\0'*(-len(archive)%4))
        archive.extend(content)
        archive.extend(b'\0'*(-len(archive)%4))
    member('.',{'type':'directory','mode':0o755},1)
    for i,(name,item) in enumerate(sorted(specs.items()),2): member(name,item,i)
    member('TRAILER!!!',{'type':'file','mode':0},len(specs)+2)
    return bytes(archive)

def audit_cpio(data,specs):
    raw=gzip.decompress(data);offset=0;found={}
    while True:
        if raw[offset:offset+6]!=b'070701': raise ValueError('newc signature')
        fields=[int(raw[offset+6+i*8:offset+14+i*8],16) for i in range(13)]
        offset+=110
        name=raw[offset:offset+fields[11]-1].decode();offset+=fields[11];offset=(offset+3)&~3
        content=raw[offset:offset+fields[6]];offset+=fields[6];offset=(offset+3)&~3
        if fields[2] or fields[3]: raise ValueError('non-root CPIO member')
        if name=='TRAILER!!!': break
        found[name]={'mode':fields[1],'uid':fields[2],'gid':fields[3],'major':fields[9],'minor':fields[10],'sha256':sha(content),'bytes':len(content)}
        if name in specs:
            want=specs[name].get('data',specs[name].get('target','').encode())
            if content!=want: raise ValueError('CPIO content changed: '+name)
    if set(found)!=set(specs)|{'.'}: raise ValueError('CPIO whitelist mismatch')
    return found

def build(out,test_dirs):
    out=Path(out).resolve()
    if not out.is_relative_to(HERE/'build') or not re.fullmatch(r'[A-Za-z0-9_./-]+',str(out)):
        raise ValueError('Output must be a simple path inside this new build directory')
    out.mkdir(parents=True,exist_ok=False)
    inputs={k:read_input(path,expected) for k,(path,expected) in LOCKED.items()}
    for key in ['busybox','codec','pty']: elf(inputs[key])
    names=inputs['applets'].decode().splitlines()
    if len(names)!=52 or len(set(names))!=52 or {'init','switch_root','pivot_root'}&set(names): raise ValueError('Wrong BusyBox applet inventory')
    reports=[]
    for folder in test_dirs:
        p=Path(folder).resolve()/'results.json'
        if not p.is_relative_to(HERE/'build'): raise ValueError('Test evidence outside own outputs')
        r=json.loads(p.read_text())
        if r['baseline'] or not r.get('lifecycle') or r.get('session_only') or r.get('review_only') or r.get('applet_only') or r['passed']!=r['total'] or r['source_sha']!=sha((HERE/'pid1.c').read_bytes()) or r.get('test_sha')!=sha((HERE/'test-pid1.py').read_bytes()) or r.get('binary_sha')!=sha((p.parent/'test-pid1').read_bytes()) or r.get('driver_sha')!=sha((HERE/'test-syscalls.c').read_bytes()) or r.get('uapi_sha')!=sha(read_input('third_party/linux-rk3588/include/uapi/linux/loop.h')): raise ValueError('Need passing fresh actual lifecycle evidence')
        if r.get('applet_sha')!=sha(inputs['applets']) or sha((p.parent/'busybox-applets.input.txt').read_bytes())!=sha(inputs['applets']):
            raise ValueError('Need locked return-island applet evidence')
        happy=[case for case in r['cases'] if case['name']=='bootstrap-happy']
        lookup=[case for case in r['cases'] if case['name']=='return-island-real-busybox-shell-lookup-and-sha256sum']
        if len(happy)!=1 or len(lookup)!=1 or not happy[0]['passed'] or not lookup[0]['passed']:
            raise ValueError('Need actual main and actual BusyBox return-island evidence')
        called=re.findall(r'^CALL \d+ symlink busybox /newroot/\.ram-return/bin/(.*)$',happy[0]['stderr'],re.M)
        if called!=names: raise ValueError('Native return-island whitelist differs from actual BusyBox')
        island=p.parent/'bootstrap-happy/island-bin'
        if {item.name for item in island.iterdir()}!=set(names)|{'busybox'}:
            raise ValueError('Return-island fixture whitelist changed')
        if sha((island/'busybox').read_bytes())!=LOCKED['busybox'][1]:
            raise ValueError('Return-island fixture BusyBox changed')
        if any(not (island/name).is_symlink() or os.readlink(island/name)!='busybox' for name in names):
            raise ValueError('Return-island fixture applet links changed')
        for name,digest in [('source-input.c',r['source_sha']),('test-pid1.input.py',r['test_sha']),
                            ('driver.c',r['driver_sha']),('headers/linux/loop.h',r['uapi_sha'])]:
            if sha((p.parent/name).read_bytes())!=digest:
                raise ValueError('Test snapshot changed: '+name)
        reports.append({'file':str(p.relative_to(HERE)),'sha256':sha(p.read_bytes()),'target':r['target'],'passed':r['passed'],'total':r['total']})
    if {x['target'] for x in reports}!={'host','aarch64'}: raise ValueError('Host and QEMU actual main evidence required')
    version=run(['aarch64-linux-gnu-gcc','--version'])
    if '11.4.0' not in version.splitlines()[0]: raise ValueError('Compiler is not locked gcc 11.4')
    (out/'compiler.txt').write_text(version)
    (out/'tool-versions.txt').write_text('\n'.join(run([name,'-V']) for name in ['mke2fs','e2fsck','debugfs']))
    headers=out/'headers/linux';headers.mkdir(parents=True)
    locked=read_input('third_party/linux-rk3588/include/uapi/linux/loop.h')
    (headers/'loop.h').write_bytes(locked)
    command=['aarch64-linux-gnu-gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-static','-fno-pie','-no-pie','-fstack-protector-strong','-frandom-seed=rtctrl-pid1-v1','-Wl,--build-id=none','-I'+str(headers.parent),str(HERE/'pid1.c'),'-o',str(out/'pid1')]
    log=run(command,env={**os.environ,'SOURCE_DATE_EPOCH':'1700000000'})
    (out/'compile.log').write_text(log)
    program=(out/'pid1').read_bytes();elf(program)
    hashes={key:LOCKED[key][1] for key in ['image','busybox','codec','pty']};hashes['pid1']=sha(program)
    specs={name:{'type':'directory','mode':0o1777 if name=='tmp' else 0o755} for name in DIRECTORIES}
    files={'bin/pid1':program,'bin/busybox':inputs['busybox'],'usr/bin/codec-test':inputs['codec'],'usr/bin/pty-test':inputs['pty']}
    for name,data in files.items(): specs[name]={'type':'file','mode':0o755,'data':data}
    for name in names:
        if name!='busybox': specs['bin/'+name]={'type':'symlink','mode':0o777,'target':'busybox'}
    for label,path in [('BusyBox','outputs/rk3568-persistent-linux-20261003/busybox-LICENSE'),('rtctrl-platform','LICENSE'),('Linux-syscall-note','third_party/linux-rk3588/LICENSES/exceptions/Linux-syscall-note')]:
        specs['usr/share/licenses/'+label]={'type':'file','mode':0o644,'data':read_input(path)}
    specs['etc/rtctrl/README']={'type':'file','mode':0o644,'data':b'Native PID1 test root. Read-only. No network, audio, MCU or service autostart.\nExit shell before using the native return command. No automatic reset.\n'}
    stage=out/'stage';stage.mkdir()
    for name,item in specs.items():
        path=stage/name
        if item['type']=='directory': path.mkdir();path.chmod(item['mode'])
        elif item['type']=='file': path.write_bytes(item['data']);path.chmod(item['mode'])
        else: path.symlink_to(item['target'])
    for path in [stage]+sorted(stage.rglob('*')):
        os.utime(path,(1700000000,1700000000),follow_symlinks=False)
    image=out/'rootfs-pid1.ext4'
    with image.open('xb') as stream: stream.truncate(SIZE)
    seed=str(uuid.UUID(sha(program)[:32]))
    environment={**os.environ,'E2FSPROGS_FAKE_TIME':'1700000000'}
    format_command=['mke2fs','-t','ext4','-F','-q','-b','4096','-m','0','-L','rtctrl-pid1-ro','-U',seed,'-O','^64bit,^metadata_csum','-E','lazy_itable_init=0,lazy_journal_init=0,hash_seed='+seed,'-d',str(stage),str(image)]
    (out/'format.log').write_text(run(format_command,env=environment))
    allocated=allocated_inodes(image.read_bytes())
    commands=''.join(f'set_inode_field <{x["inode"]}> uid 0\nset_inode_field <{x["inode"]}> gid 0\n' for x in allocated)
    (out/'ownership.debugfs').write_text(commands)
    (out/'ownership.log').write_text(run(['debugfs','-w','-f',str(out/'ownership.debugfs'),str(image)],env=environment))
    inode_audit=allocated_inodes(image.read_bytes())
    if any(x['uid'] or x['gid'] for x in inode_audit): raise ValueError('Allocated inode is not root-owned')
    (out/'inode-audit.json').write_text(json.dumps(inode_audit,indent=2)+'\n')
    (out/'e2fsck.log').write_text(run(['e2fsck','-fn',str(image)]))
    rootdata=image.read_bytes();sb=rootdata[1024:2048]
    if struct.unpack_from('<H',sb,58)[0]!=1 or struct.unpack_from('<I',sb,96)[0]&4: raise ValueError('Root image not clean/no-recovery')
    exports=out/'exports';exports.mkdir()
    exported={}
    for name,data in files.items():
        dest=exports/Path(name).name
        (out/(Path(name).name+'-dump.log')).write_text(run(['debugfs','-R','dump /'+name+' '+str(dest),str(image)]))
        if dest.read_bytes()!=data: raise ValueError('Exported ELF mismatch: '+name)
        elf(dest.read_bytes());exported[name]={'bytes':len(data),'sha256':sha(data)}
    hashes['rootfs']=sha(rootdata)
    manifest='RTCTRL_PID1_V1\n'+''.join(k+'='+hashes[k]+'\n' for k in ['image','busybox','pid1','rootfs','codec','pty'])
    (out/'boot-manifest.txt').write_text(manifest)
    init_specs={name:{'type':'directory','mode':0o1777 if name=='tmp' else 0o755} for name in ['bin','dev','dev/pts','etc','etc/rtctrl','proc','sys','tmp','run','newroot','backing-cache']}
    init_specs['init']={'type':'file','mode':0o755,'data':program}
    init_specs['bin/busybox']={'type':'file','mode':0o755,'data':inputs['busybox']}
    for name in names: init_specs['bin/'+name]={'type':'symlink','mode':0o777,'target':'busybox'}
    init_specs['etc/rtctrl/manifest']={'type':'file','mode':0o600,'data':manifest.encode()}
    init_specs['dev/console']={'type':'character','mode':0o600,'major':5,'minor':1}
    init_specs['dev/null']={'type':'character','mode':0o666,'major':1,'minor':3}
    cpio=pack_cpio(init_specs)
    initrd=gzip.compress(cpio,compresslevel=9,mtime=0)
    if len(initrd)>6*1024*1024: raise ValueError('initrd exceeds 6 MiB staging budget')
    (out/'initramfs-pid1.cpio.gz').write_bytes(initrd)
    cpio_audit=audit_cpio(initrd,init_specs)
    (out/'initramfs-audit.json').write_text(json.dumps(cpio_audit,indent=2)+'\n')
    qemu=ROOT/'.deps/qemu-user/root/usr/bin/qemu-aarch64-static'
    actual_applets=run([str(qemu),str(ROOT/LOCKED['busybox'][0]),'--list']).splitlines()
    if actual_applets!=names: raise ValueError('Actual BusyBox applets differ from locked list')
    qemu_result=subprocess.run([str(qemu),str(out/'pid1'),'bootstrap'],capture_output=True,text=True)
    if qemu_result.returncode!=2: raise ValueError('Production PID1 accepted child invocation')
    (out/'production-qemu-cli.txt').write_text(qemu_result.stdout+qemu_result.stderr)
    entries={name:{k:v for k,v in item.items() if k!='data'}|{'uid':0,'gid':0}|({'sha256':sha(item['data']),'bytes':len(item['data'])} if 'data' in item else {}) for name,item in specs.items()}
    sources={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in [HERE/'pid1.c',HERE/'build-pid1.py',HERE/'test-pid1.py',HERE/'test-syscalls.c',HERE/'PLAN.md',ROOT/'third_party/linux-rk3588/include/uapi/linux/loop.h',ROOT/'third_party/linux-rk3588/drivers/block/loop.c',ROOT/'third_party/linux-rk3588/fs/namespace.c',ROOT/'outputs/rk3568-rng-network-20261004/build-busybox-module-options.py']}
    for name,digest in sources.items():
        target=out/'source-inputs'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((ROOT/name).read_bytes())
        if sha(target.read_bytes())!=digest: raise ValueError('Source changed while freezing '+name)
    report={'schema':1,'board_tested':False,'compiler':version.splitlines()[0],'compile_argv':command,'format_argv':format_command,'source_sha256':sources,'inputs':{k:{'path':p,'sha256':s} for k,(p,s) in LOCKED.items()},'cache_fixed_paths':{'Image':'/cache/rtctrl-rcu-reset-20261004/Image','rootfs':'/cache/rtctrl-pid1-20261005/rootfs-pid1.ext4'},'tests':reports,'artifacts':{name:{'bytes':len(data),'sha256':sha(data),'crc32':f'{zlib.crc32(data)&0xffffffff:08x}'} for name,data in [('pid1',program),('rootfs-pid1.ext4',rootdata),('initramfs-pid1.cpio.gz',initrd)]},'allocated_inode_count':len(inode_audit),'all_allocated_inodes_uid_gid_zero':True,'exported_elf':exported,'rootfs_entries':entries,'initramfs_members':len(cpio_audit),'policy':{'rootfs_readonly_noload':True,'image_file_verified_bootloader_load_not_proven':True,'cache_384_mib':True,'rootfs_limit_mib':16,'initrd_limit_mib':6,'physical_services':[],'automatic_reset':False,'flash':False,'saveenv':False,'deployment_owner_must_be_root':True,'filesystem_mount_board_tested':False}}
    report['return_island_entries']={
        **{name:{'type':'directory','mode':0o755} for name in ['bin','backing-cache','dev','proc','sys','tmp','run','old-root']},
        'bin/pid1':{'type':'file','mode':0o755,'bytes':len(program),'sha256':sha(program)},
        'bin/busybox':{'type':'file','mode':0o755,'bytes':len(inputs['busybox']),'sha256':sha(inputs['busybox'])},
        **{'bin/'+name:{'type':'symlink','target':'busybox'} for name in names}
    }
    report['policy']['return_island_applet_count']=52
    report['policy']['return_island_applet_failure_blocks_root_transition']=True
    report['cache_fixed_paths']['rootfs']='/cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4'
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'output':str(out),'artifacts':report['artifacts'],'allocated_inodes':len(inode_audit)},indent=2))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True)
    parser.add_argument('--tests',action='append',required=True)
    args=parser.parse_args()
    try: build(args.out,args.tests)
    except (OSError,ValueError,RuntimeError) as error: parser.exit(1,'PID1_BUILD_REJECTED: '+str(error)+'\n')

if __name__=='__main__': main()
