#!/usr/bin/env python3
"""MIT. Execute actual main, interpose syscall boundaries only; fresh evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
QEMU = ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static'
DRIVER = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/types.h>
#include <unistd.h>
extern int pid1_main(int, char **);
static jmp_buf done;
pid_t __wrap_getpid(void) { return getenv("NOT_PID1") ? 42 : 1; }
uid_t __wrap_getuid(void) { return 0; }
int __wrap_mount(const char *s, const char *t, const char *f,
                 unsigned long flags, const void *d) {
    fprintf(stderr, "CALL mount %s %s %s %lu %s\n", s?s:"-", t,
            f?f:"-", flags, d?(const char *)d:"-");
    errno=EPERM; return -1;
}
ssize_t __wrap_read(int fd, void *buf, size_t n) {
    if(fd == 0) { (void)buf; (void)n; longjmp(done, 1); }
    extern ssize_t __real_read(int,void *,size_t);
    return __real_read(fd,buf,n);
}
int __wrap_poll(void *p, unsigned long n, int timeout) {
    (void)p;(void)n;(void)timeout; longjmp(done, 1);
}
int main(int argc, char **argv) {
    if(setjmp(done)) { puts("OBSERVED_PID1_ALIVE"); return 0; }
    int rc=pid1_main(argc,argv);
    printf("OBSERVED_MAIN_RETURN %d\n",rc);
    return 0;
}
'''

def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, timeout=30, **kw)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--out', required=True)
    p.add_argument('--target', choices=['host','aarch64'], default='host')
    p.add_argument('--baseline', action='store_true')
    p.add_argument('--lifecycle', action='store_true')
    p.add_argument('--session-only', action='store_true')
    p.add_argument('--review-only', action='store_true')
    p.add_argument('--applet-only', action='store_true')
    a=p.parse_args()
    out=Path(a.out).resolve()
    if not out.is_relative_to(HERE / 'build'):
        p.error('Output must be inside this new directory build/')
    out.mkdir(parents=True, exist_ok=False)
    src=HERE / 'pid1.c'
    test_sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if a.baseline:
        src=out / 'missing-pid1.c'
        src.write_text('int main(int argc, char **argv) {(void)argc;(void)argv;return 0;}\n')
    cc='gcc' if a.target=='host' else 'aarch64-linux-gnu-gcc'
    headers=out/'headers/linux'
    headers.mkdir(parents=True)
    uapi=(ROOT/'third_party/linux-rk3588/include/uapi/linux/loop.h').read_bytes()
    (headers/'loop.h').write_bytes(uapi)
    source_sha=hashlib.sha256(src.read_bytes()).hexdigest()
    (out/'source-input.c').write_bytes(src.read_bytes())
    (out/'test-pid1.input.py').write_bytes(Path(__file__).read_bytes())
    (out/'driver.c').write_text((HERE/'test-syscalls.c').read_text() if a.lifecycle else DRIVER)
    wraps=['getpid','getuid','mount','read','poll']
    if a.lifecycle:
        wraps=['getpid','getuid','open','__open_2','fstat','stat','statfs','read','write','lseek','close','fcntl','dup2','sigaction','uname','mount','mkdir','unlink','symlink','fsync','chdir','chroot','syscall','umount2','ioctl','opendir','readdir','closedir','waitpid','execve','fork','pipe2','poll','setsid','kill','_exit']
    commands=[
        [cc,'-std=c11','-Wall','-Wextra','-Werror','-O2','-I'+str(headers.parent),'-Dmain=pid1_main','-c',str(src),'-o',str(out/'main.o')],
        [cc,'-std=c11','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-O2','-I'+str(headers.parent),'-static',str(out/'driver.c'),str(out/'main.o')]+['-Wl,--wrap='+x for x in wraps]+['-o',str(out/'test-pid1')],
    ]
    for cmd in commands:
        r=run(cmd)
        if r.returncode:
            (out/'compile-error.txt').write_text(r.stdout+r.stderr)
            raise RuntimeError(r.stderr)
    runner=[] if a.target=='host' else [str(QEMU)]
    cases=[
        ('pid1_bad_cli_stays_rescue',[],{},'OBSERVED_PID1_ALIVE', 'LINUX_PID1_RAM_READY'),
        ('pid1_bootstrap_mount_failure_stays_rescue',['bootstrap'],{},'OBSERVED_PID1_ALIVE','LINUX_PID1_ROOT_READY'),
        ('child_cannot_mount',['bootstrap'],{'NOT_PID1':'1'},'OBSERVED_MAIN_RETURN 2','CALL mount'),
        ('pid1_root_missing_state_stays_rescue',['root'],{},'OBSERVED_PID1_ALIVE','LINUX_PID1_ROOT_READY'),
        ('pid1_return_missing_state_stays_rescue',['return'],{},'OBSERVED_PID1_ALIVE','LINUX_PID1_RAM_READY'),
    ]
    evidence=[]
    if a.lifecycle:
        image_sha='e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457'
        bb_sha='514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1'
        codec_sha='18fd4744d881e46661d16ad60112f395262b6a6e97ce83f246a4334f6448234c'
        pty_sha='5eb5fd9aba8133933dce602d5e0dbd3acf5f1829f700615dc77a67b5f1d0cbda'
        pid1_sha=hashlib.sha256(b'abc').hexdigest()
        rootfs=bytearray(16*1024*1024)
        rootfs[1080:1084]=b'\x53\xef\x01\x00'
        rootfs_sha=hashlib.sha256(rootfs).hexdigest()
        (out/'fixture-rootfs').write_bytes(rootfs)
        bb=ROOT/'outputs/rk3568-rng-network-20261004/build/busybox-module-options/v1/busybox'
        applet_file=ROOT/'outputs/rk3568-persistent-linux-20261003/busybox-applets.txt'
        applet_data=applet_file.read_bytes()
        applet_sha=hashlib.sha256(applet_data).hexdigest()
        if applet_sha!='6e2d74e972829be2fcacb329bcddd2b5d026a138a76031ae1ad9e5b3dd96eedf':
            raise ValueError('Locked applet list changed')
        applets=applet_data.decode().splitlines()
        (out/'busybox-applets.input.txt').write_bytes(applet_data)
        def execute(name, mode='return', scenario='ok', fail_at=0, expected='alive', commands=''):
            fixture=out/name
            fixture.mkdir()
            (fixture/'empty').mkdir()
            (fixture/'island-bin').mkdir()
            (fixture/'abc').write_bytes(b'abc')
            (fixture/'bad').write_bytes(b'wrong')
            (fixture/'dummy').write_bytes(b'dummy')
            (fixture/'rootfs').symlink_to(out/'fixture-rootfs')
            if mode!='bootstrap':
                shutil.copyfile(bb,fixture/'island-bin/busybox')
            hashes=''.join(h+'\0' for h in [image_sha,bb_sha,pid1_sha,rootfs_sha,codec_sha,pty_sha]).encode()
            native_v2='struct mount_record' in src.read_text()
            state=struct.pack('<QQQQQ10I390s2x',0x5254435049443101,os.makedev(179,12),os.makedev(179,12),42,os.makedev(7,2),2 if native_v2 else 1,2 if mode=='root' else 3,63,0,0,0,0,0,1,2,hashes)
            if native_v2:
                saved_mounts=[
                    (0,1,10,1,'rootfs'),(7,2,11,10,'ext4'),(0,4,12,11,'tmpfs'),
                    (179,12,13,10,'ext4'),(0,2,14,10,'devtmpfs'),(0,3,15,14,'devpts'),
                    (0,5,16,10,'proc'),(0,6,17,10,'sysfs'),(0,7,18,10,'tmpfs'),(0,8,19,10,'tmpfs'),
                ]
                state+=b''.join(struct.pack('<QII16s',os.makedev(ma,mi),mid,parent,kind.encode()) for ma,mi,mid,parent,kind in saved_mounts)
                state+=struct.pack('<I4x',1)
            (fixture/'state').write_bytes(state if scenario!='bad-state' else b'broken')
            if scenario in ['state-nonhex','state-wrong-cache','state-wrong-loop','state-no-owner','state-no-mounts','state-duplicate-mount-id','state-mount-type-unterminated','state-wrong-mount-root-device','state-wrong-mount-parent','state-unsafe-ram','state-unmount-before-pivot']:
                mutated=bytearray(state)
                if scenario=='state-nonhex': mutated[80+65*2:80+65*3]=b'z'*65
                if scenario=='state-wrong-cache': struct.pack_into('<Q',mutated,8,os.makedev(8,12))
                if scenario=='state-wrong-loop': struct.pack_into('<Q',mutated,32,os.makedev(7,3))
                if scenario=='state-no-owner': struct.pack_into('<I',mutated,72,0)
                if scenario=='state-no-mounts': struct.pack_into('<I',mutated,792,0)
                if scenario=='state-duplicate-mount-id': struct.pack_into('<I',mutated,640,14)
                if scenario=='state-mount-type-unterminated': mutated[648:664]=b'z'*16
                if scenario=='state-wrong-mount-root-device': struct.pack_into('<Q',mutated,504,os.makedev(8,2))
                if scenario=='state-wrong-mount-parent': struct.pack_into('<I',mutated,644,11)
                if scenario=='state-unsafe-ram': struct.pack_into('<I',mutated,44,4)
                if scenario=='state-unmount-before-pivot': struct.pack_into('<I',mutated,60,1)
                (fixture/'state').write_bytes(mutated)
            (fixture/'manifest').write_text('RTCTRL_PID1_V1\n'+''.join(k+'='+v+'\n' for k,v in zip(['image','busybox','pid1','rootfs','codec','pty'],[image_sha,bb_sha,pid1_sha,rootfs_sha,codec_sha,pty_sha])))
            r=run(runner+[str(out/'test-pid1'),mode],env={**os.environ,'FIXTURE':str(fixture),'SCENARIO':scenario,'FAIL_AT':str(fail_at),'CONSOLE_COMMANDS':commands,'SELF_BINARY':str(out/'test-pid1'),'SELF_LAUNCHER':str(QEMU) if a.target=='aarch64' else ''})
            result=r.stdout+r.stderr
            injected='INJECTED ' in result
            reached='OBSERVED_PID1_ALIVE' in result
            if expected=='root-exec':
                passed='OBSERVED_EXEC /bin/pid1 root' in result
                passed &= 'open /backing-cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4 flags=' in result
                island=fixture/'island-bin'
                links={path.name for path in island.iterdir() if path.is_symlink()}
                passed &= links==set(applets) and all(os.readlink(island/name)=='busybox' for name in links)
                passed &= hashlib.sha256((island/'busybox').read_bytes()).hexdigest()==bb_sha
            elif expected=='island-exec':
                passed='OBSERVED_EXEC /.ram-return/bin/pid1 return' in result
            elif expected=='ram':
                passed='LINUX_PID1_RAM_READY_NO_RESET' in result and reached
                pos=[result.find(x) for x in ['pivot_root . old-root','umount /old-root flags=0','ioctl 0x4c01','umount /backing-cache flags=0']]
                passed &= all(x>=0 for x in pos) and pos==sorted(pos)
            elif expected=='not-pid1':
                passed='OBSERVED_MAIN_RETURN 2' in result and 'CALL ' not in result
            elif expected=='reaped':
                passed='OWNED_SESSION_REAPED pid=123 start=20 status=0' in result and reached and 'pipe2' in result and 'poll' in result
                if commands.startswith(('codec','pty')):
                    passed &= 'SOFTWARE_TEST_PASSED path=/usr/bin/' in result
            elif expected=='software-failed':
                passed=reached and 'PID1_RESCUE first=software test failed' in result and 'SOFTWARE_TEST_PASSED' not in result
            elif expected=='child-exec':
                passed='OBSERVED_EXEC /.ram-return/bin/busybox sh' in result and 'OBSERVED_PID1_ALIVE' not in result and 'read session pipe' in result
            else:
                passed=reached and 'OBSERVED_EXEC ' not in result and 'LINUX_PID1_RAM_READY_NO_RESET' not in result
            if fail_at:
                passed &= injected
            passed &= r.returncode==0
            evidence.append({'name':name,'mode':mode,'scenario':scenario,'injection':fail_at,'passed':bool(passed),'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
            (fixture/'trace.txt').write_text(result)
            return r
        def applet_environment(fixture_name):
            island=out/fixture_name/'island-bin'
            command='for x in "$@"; do command -v "$x" || exit 23; done'
            result=run([str(QEMU),str(island/'busybox'),'sh','-c',command,'sh']+applets,
                       env={**os.environ,'PATH':str(island)})
            locations=result.stdout.splitlines()
            expected=[name if name in {'[','echo','printf','test'} else str(island/name) for name in applets]
            passed=result.returncode==0 and locations==expected
            if passed:
                checksum=run([str(QEMU),str(island/'sha256sum'),str(island/'busybox')])
                passed=checksum.returncode==0 and checksum.stdout.split()[0]==bb_sha
                result.stdout+=checksum.stdout
                result.stderr+=checksum.stderr
            evidence.append({'name':'return-island-real-busybox-shell-lookup-and-sha256sum',
                             'passed':passed,'returncode':result.returncode,
                             'stdout':result.stdout,'stderr':result.stderr})
        for command in ([] if a.review_only or a.applet_only else ['shell','codec','pty']):
            r=execute('session-'+command,'root','no-return',expected='reaped',commands=command+'\n')
            if command=='shell' and not a.baseline:
                start=re.search(r'^CALL (\d+) pipe2',r.stderr,re.M)
                if start:
                    indices=[int(x) for x in re.findall(r'^CALL (\d+) ',r.stderr,re.M) if int(x)>=int(start[1])]
                    for index in indices:
                        execute(f'session-failure-{index:03}','root','no-return',index,commands='shell\n')
        if not a.review_only and not a.applet_only:
            execute('session-child-exec','root','child-branch',expected='child-exec',commands='shell\n')
            execute('session-identity-mismatch','root','session-mismatch',commands='shell\nstop\n')
            execute('session-console-fd0-survives-exec','root','cloexec-console',expected='island-exec')
        for command in ([] if a.review_only or a.applet_only else ['codec','pty']):
            for scenario in ['child-nonzero','child-signal']:
                execute('session-'+command+'-'+scenario,'root',scenario,expected='software-failed',commands=command+'\n')
        if a.applet_only:
            r=execute('applet-bootstrap','bootstrap',expected='root-exec')
            for line in r.stderr.splitlines():
                match=re.match(r'CALL (\d+) symlink busybox /newroot/.ram-return/bin/',line)
                if match:
                    execute('applet-symlink-failure-'+match[1],'bootstrap',fail_at=int(match[1]))
            applet_environment('applet-bootstrap')
        for mode,expected in ([] if a.session_only or a.review_only or a.applet_only else [('bootstrap','root-exec'),('root','island-exec'),('return','ram')]):
            r=execute(mode+'-happy',mode,expected=expected)
            if mode=='bootstrap':
                applet_environment('bootstrap-happy')
            if not a.baseline and r.returncode==0:
                indices=[int(x) for x in re.findall(r'^CALL (\d+) ',r.stderr,re.M)]
                # Fail every observed external operation individually, including bootstrap.
                for index in indices:
                    execute(f'{mode}-failure-{index:03}',mode,fail_at=index)
                if mode=='bootstrap':
                    for line in r.stderr.splitlines():
                        match=re.match(r'CALL (\d+) (.*)',line)
                        if match and (match[2] in ['chdir /newroot','chroot .','chdir /','execve /bin/pid1 root'] or match[2].startswith('mount . / ')):
                            execute(f'bootstrap-resume-{int(match[1]):03}',mode,'resume',int(match[1]),'root-exec')
                if mode=='return':
                    for line in r.stderr.splitlines():
                        match=re.match(r'CALL (\d+) (.*)',line)
                        if match and (match[2].startswith('mount ') or match[2].startswith('umount ') or match[2]=='pivot_root . old-root' or match[2]=='ioctl 0x4c01'):
                            execute(f'return-resume-{int(match[1]):03}',mode,'resume',int(match[1]),'ram')
                    clear=re.search(r'CALL (\d+) ioctl 0x4c01\nCALL (\d+) close',r.stderr)
                    if clear:
                        execute('return-resume-close-after-detach',mode,'resume',int(clear[2]),'ram')
        for scenario in ([] if a.session_only or a.review_only or a.applet_only else ['not-pid1','not-root','bad-state','bad-island-fs','bad-pid1-sha','bad-loop-device','bad-loop-inode','bad-loop-flags','bad-loop-rdevice','bad-loop-encryption','wrong-exe-device','state-nonhex','state-wrong-cache','state-wrong-loop','state-no-owner','unknown-user','extra-fd','extra-mount','read-error']):
            execute('return-'+scenario,'return',scenario,expected='not-pid1' if scenario=='not-pid1' else 'alive')
        for scenario in ([] if a.session_only or a.review_only or a.applet_only else ['bad-root-device','wrong-exe-device','bad-pid1-sha','bad-busybox-sha','file-uid','unknown-user','extra-fd','extra-mount']):
            execute('root-'+scenario,'root',scenario)
        for scenario in ([] if a.session_only or a.review_only or a.applet_only else ['bad-release','bad-cache-partname','bad-cache-size','bad-cache-major','bad-cache-fstat','bad-cache-bytes','loop-inuse','bad-loop-flags']):
            execute('bootstrap-'+scenario,'bootstrap',scenario)
        if not a.session_only and not a.applet_only:
            root=execute('review-root-baseline','root',expected='island-exec')
            match=re.search(r'^CALL (\d+) execve /\.ram-return/bin/pid1 return$',root.stderr,re.M)
            if match:
                execute('review-exec-island-failure-resume','root','exec-resume',int(match[1]),'ram')
            else:
                evidence.append({'name':'review-exec-island-failure-resume','passed':False,'reason':'baseline did not reach island exec'})
            root_lines=root.stderr.splitlines()
            saves=[i for i,line in enumerate(root_lines) if 'open /.ram-return/state flags=' in line]
            if saves:
                for line in root_lines[saves[-1]:]:
                    save=re.match(r'CALL (\d+) (.*)',line)
                    if save and save[2].startswith('execve '):
                        break
                    if save:
                        execute('review-RETURN-state-persist-resume-'+save[1],'root','exec-resume',int(save[1]),'ram')
            execute('review-return-invalid-exe-cannot-resume','return','wrong-exe-device',commands='resume\n')
            execute('review-return-invalid-island-cannot-resume','return','bad-island-fs',commands='resume\n')
            for scenario in ['duplicate-devpts','wrong-mount-id','wrong-mount-parent','wrong-mount-device','wrong-mount-fs']:
                execute('review-'+scenario,'return',scenario)
            normal=execute('review-return-baseline','return',expected='ram')
            match=re.search(r'^CALL (\d+) umount /old-root flags=0$',normal.stderr,re.M)
            if match:
                execute('review-postpivot-new-mount-blocks-resume','return','postpivot-extra',int(match[1]))
            else:
                evidence.append({'name':'review-postpivot-new-mount-blocks-resume','passed':False,'reason':'baseline did not reach old-root umount'})
            if not a.review_only:
                for scenario in ['state-no-mounts','state-duplicate-mount-id','state-mount-type-unterminated','state-wrong-mount-root-device','state-wrong-mount-parent','state-unsafe-ram','state-unmount-before-pivot']:
                    execute('review-invalid-state-resume-'+scenario,'return',scenario,commands='resume\n')
                cache_seen=False
                for line in normal.stderr.splitlines():
                    match=re.match(r'CALL (\d+) (.*)',line)
                    if match and match[2]=='umount /backing-cache flags=0':
                        cache_seen=True
                    elif cache_seen and match:
                        execute('review-final-RAM-resume-'+match[1],'return','resume',int(match[1]),'ram')
        cases=[]
    for name,args,environment,want,forbidden in cases:
        r=run(runner+[str(out/'test-pid1')]+args,env={**os.environ,**environment})
        text=r.stdout+r.stderr
        passed=r.returncode==0 and want in text and forbidden not in text
        evidence.append({'name':name,'passed':passed,'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
    if source_sha!=hashlib.sha256(src.read_bytes()).hexdigest(): raise RuntimeError('Source changed during tests')
    if test_sha!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(): raise RuntimeError('Test runner changed during tests')
    report={'target':a.target,'baseline':a.baseline,'lifecycle':a.lifecycle,'session_only':a.session_only,'review_only':a.review_only,'applet_only':a.applet_only,'total':len(evidence),'passed':sum(x['passed'] for x in evidence),'cases':evidence,'commands':commands,'source_sha':source_sha,'test_sha':test_sha,'binary_sha':hashlib.sha256((out/'test-pid1').read_bytes()).hexdigest(),'driver_sha':hashlib.sha256((out/'driver.c').read_bytes()).hexdigest(),'uapi_sha':hashlib.sha256(uapi).hexdigest(),'applet_sha':applet_sha if a.lifecycle else None}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f"{report['passed']}/{report['total']} {a.target}; {out}")
    return 0 if report['passed']==report['total'] else 1

if __name__=='__main__':
    sys.exit(main())
