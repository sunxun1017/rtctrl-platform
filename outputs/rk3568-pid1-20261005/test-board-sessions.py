#!/usr/bin/env python3
"""Read-only session audit plus real BusyBox shell with redirected proc fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import struct
import subprocess
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BB = ROOT / 'outputs/rk3568-rng-network-20261004/build/busybox-module-options/v1/busybox'
QEMU = ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static'
PID = 'f24b86829560b963782b676d9f9a7c41cedab447587c2b6522489cedfb6f124c'
BBSHA = '514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1'
READY = 'PID1_INDEPENDENT_RAM_ONLY_RETURN_READY'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--session-version', default='v1')
    args = parser.parse_args()
    if not args.version.startswith('v') or not args.version[1:].isdigit() or args.version[1:].startswith('0'):
        parser.error('version must be vN')
    if not args.session_version.startswith('v') or not args.session_version[1:].isdigit() or args.session_version[1:].startswith('0'):
        parser.error('session-version must be vN')
    output = HERE / 'build' / ('board-review-' + args.version)
    output.mkdir(exist_ok=False)
    source = (HERE / 'linux-return-guard.sh').read_text()
    (output / 'linux-return-guard.input.sh').write_text(source)
    manifest = json.loads((HERE / ('board-manifest-' + args.session_version + '.json')).read_text())
    pid_sha = manifest['artifacts']['pid1']['sha256']
    checks = []
    def check(name, condition, detail=None):
        checks.append(dict(name=name, passed=bool(condition), **({'detail': detail} if detail else {})))
    check('guard bound by session manifest', sha(HERE / 'linux-return-guard.sh') == manifest['return_guard_sha256'])
    check('exact 52-applet BusyBox SHA', sha(BB) == BBSHA)
    applets = subprocess.check_output([str(QEMU), str(BB), '--list'], text=True).splitlines()
    check('guard commands available in exact BusyBox', len(applets) == 52 and all(x in applets for x in ['grep','cat','hexdump','losetup','sha256sum','readlink','uname','sh','test','printf','stat']))
    for name, expected in manifest['sessions'].items():
        path = HERE / name
        data = json.loads(path.read_text())
        check('session SHA ' + name, sha(path) == expected)
        check('printable serial ASCII ' + name, all(all(32 <= ord(c) <= 126 for c in row['command']) for row in data))
    payload = ROOT / manifest['payload']
    for name, expected in manifest['files'].items():
        check('payload SHA ' + name, sha(payload / name) == expected)
    image = ROOT / 'outputs/rk3568-rcu-reset-20261004/Image'
    check('fixed old Image path and SHA', sha(image) == 'e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457' and manifest['image_cached_path'] == '/cache/rtctrl-rcu-reset-20261004/Image')
    production_paths = [path for path in (HERE / 'build').glob('production-v*/manifest.json')
                        if sha(path) == manifest['production_manifest_sha256']]
    check('production manifest SHA', len(production_paths) == 1)
    if len(production_paths) != 1:
        raise ValueError('Frozen production manifest is missing or ambiguous')
    production = json.loads(production_paths[0].read_text())
    check('unique new cache rootfs path', manifest['rootfs_path'] in ['/cache/rtctrl-pid1-20261005/rootfs-pid1.ext4', '/cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4'] and manifest['rootfs_path'] == production['cache_fixed_paths']['rootfs'])
    cache_path = manifest['rootfs_path'][len('/cache'):].rsplit('/', 1)[0]
    offset, memory = struct.unpack_from('<QQ', image.read_bytes(), 8)
    check('Image memory ends before DTB', offset == 0 and memory == 35389440 and 0x400000 + memory == 0x25c0000 and 0x25c0000 < 0x3000000)
    check('resized DTB ends before initrd', 0x3000000 + 162414 + 0x10000 < 0x4000000)
    load = json.loads((HERE / ('pid1-load-' + args.session_version + '.json')).read_text())
    for index, name, address, path in [(0,'Image',0x400000,'/rtctrl-rcu-reset-20261004/Image'),(2,'uart.dtb',0x3000000,cache_path+'/uart.dtb'),(4,'initramfs-pid1.cpio.gz',0x4000000,cache_path+'/initramfs-pid1.cpio.gz')]:
        artifact = image if name == 'Image' else payload / name
        size = artifact.stat().st_size
        crc = f'{zlib.crc32(artifact.read_bytes()):08x}'
        check('load and CRC exact bytes ' + name, load[index]['command'] == f'ext4load mmc 0:c {address:x} {path}' and load[index]['expect'] == f'{size} bytes read' and load[index+1]['command'] == f'crc32 {address:x} {size:x}' and load[index+1]['expect'] == '==> ' + crc)
    for name in ['prepare-android.sh','linux-return-guard.sh']:
        subprocess.run([str(QEMU),str(BB),'sh','-n',str(HERE/name)],check=True)
    mounts = 'tmpfs / tmpfs rw 0 0\ndevtmpfs /dev devtmpfs rw 0 0\ndevpts /dev/pts devpts rw 0 0\nproc /proc proc rw 0 0\nsysfs /sys sysfs rw 0 0\ntmpfs /tmp tmpfs rw 0 0\ntmpfs /run tmpfs rw 0 0\n'
    scenarios = [
        ('valid RAM baseline', {}, True),
        ('owned shell stdio accepted', {'fd':('/dev/console','0')}, True),
        ('owned shell controlling terminal accepted', {'fd':('/dev/tty','10')}, True),
        ('controlling terminal wrong FD rejected', {'fd':('/dev/tty','4')}, False),
        ('guard controlling terminal rejected', {'guard_fd':('/dev/tty','10')}, False),
        ('PID1 controlling terminal rejected', {'pid_fd':('/dev/tty','10')}, False),
        ('controlling terminal non-device rejected', {'fd':('/dev/tty','10'),'tty_stat':'regular file:0:0'}, False),
        ('controlling terminal wrong device rejected', {'fd':('/dev/tty','10'),'tty_stat':'character special file:5:1'}, False),
        ('controlling terminal stat error rejected', {'fd':('/dev/tty','10'),'tty_stat_error':True}, False),
        ('shell wrong session rejected', {'parent_session':'201'}, False),
        ('shell wrong process group rejected', {'parent_group':'201'}, False),
        ('owned guard script descriptor accepted', {'guard_fd':('/tmp/pid1-return-guard.sh','10')}, True),
        ('guard unknown script descriptor rejected', {'guard_fd':('/tmp/other.sh','10')}, False),
        ('guard script wrong descriptor rejected', {'guard_fd':('/tmp/pid1-return-guard.sh','11')}, False),
        ('guard socket descriptor rejected', {'guard_fd':('socket:[777]','4')}, False),
        ('wrong PID1 SHA rejected', {'pid_sha':'0'*64}, False),
        ('wrong PID1 executable path rejected', {'exe':'/old-root/bin/pid1'}, False),
        ('wrong PID1 argv rejected', {'argv':'00'}, False),
        ('modules present rejected', {'modules':'bad 1 0 - Live 0x0\n'}, False),
        ('bound loop rejected', {'loops':'/dev/loop0: [179:12]:1 (rootfs.ext4)\n'}, False),
        ('ext4 cache mount rejected', {'mounts':mounts+'/dev/mmcblk0p12 /backing-cache ext4 ro 0 0\n'}, False),
        ('non-RAM root rejected', {'mounts':mounts.replace('tmpfs / tmpfs','rootfs / rootfs')}, False),
        ('wrong devpts target rejected', {'mounts':mounts.replace('devpts /dev/pts','devpts /wrong')}, False),
        ('wrong shell parent rejected', {'ancestor':'2'}, False),
        ('foreign user process rejected', {'foreign':True}, False),
        ('non-BusyBox shell rejected', {'bb_sha':'0'*64}, False),
        ('hardware device FD rejected', {'fd':('/dev/mmcblk0p12','4')}, False),
        ('extra console FD rejected', {'fd':('/dev/console','4')}, False),
        ('extra PID1 socket FD must reject', {'pid_fd':('socket:[777]','4')}, False),
        ('extra PID1 regular-file FD must reject', {'pid_fd':('/tmp/leaked','4')}, False),
        ('duplicate devpts mount must reject', {'mounts':mounts+'devpts /dev/pts devpts rw 0 0\n'}, False),
        ('duplicate root mount must reject', {'mounts':mounts+'tmpfs / tmpfs rw 0 0\n'}, False),
        ('duplicate tmp mount must reject', {'mounts':mounts+'tmpfs /tmp tmpfs rw 0 0\n'}, False),
        ('missing proc mount rejected', {'mounts':mounts.replace('proc /proc proc rw 0 0\n','')}, False),
        ('wrong virtual mount identity rejected', {'mounts':mounts.replace('sysfs /sys sysfs','proc /sys proc')}, False),
        ('unknown RAM mount rejected', {'mounts':mounts+'tmpfs /unknown tmpfs rw 0 0\n'}, False),
        ('shell extra socket FD rejected', {'fd':('socket:[777]','4')}, False),
        ('shell extra anon_inode FD rejected', {'fd':('anon_inode:[eventfd]','4')}, False),
        ('shell extra regular FD rejected', {'fd':('/tmp/leaked','4')}, False),
        ('PID1 additional stdio target rejected', {'pid_fd':('/tmp/leaked','0')}, False),
        ('PID1 FIQ alias rejected', {'pid_fd':('/dev/ttyFIQ0','0')}, False),
        ('PID1 missing stdin rejected', {'missing_stdin':True}, False),
        ('module read error rejected', {'read_fail':'modules'}, False),
        ('mount read error rejected', {'read_fail':'mounts'}, False),
        ('loop query error rejected', {'loop_fail':True}, False),
        ('FD readlink error rejected', {'readlink_fail':True}, False),
        ('bad uid rejected', {'uid':'1000 1000 1000 1000'}, False),
    ]
    for number,(name,config,want) in enumerate(scenarios):
        d=output/f'case-{number:02d}'; d.mkdir()
        proc=d/'proc'; proc.mkdir()
        for pid in ['1','200','7'] + (['400'] if config.get('foreign') else []):
            (proc/pid/'fd').mkdir(parents=True)
            flags=2097152 if pid=='7' else 0
            group = config.get('parent_group','200') if pid == '200' else '200'
            session = config.get('parent_session','200') if pid == '200' else '200'
            (proc/pid/'stat').write_text(f'{pid} (fixture) S 1 {group} {session} 0 0 {flags} '+'0 '*13+'1\n')
        for target,fd in [('/dev/console','0'),('/dev/console','1'),('/dev/console','2')]:
            (proc/'1'/'fd'/fd).symlink_to(target)
        if config.get('missing_stdin'):
            (proc/'1'/'fd'/'0').unlink()
        for key,pid in [('pid_fd','1'),('fd','200')]:
            if key in config:
                target,fd=config[key]
                descriptor = proc/pid/'fd'/fd
                if descriptor.is_symlink():
                    descriptor.unlink()
                descriptor.symlink_to(target)
        for file,value in [('modules',config.get('modules','')),('mounts',config.get('mounts',mounts)),('loops',config.get('loops',''))]:
            (proc/file).write_text(value)
        translated=source.replace('/proc/',str(proc)+'/').replace('/sys/class/net/wlan0',str(d/'sys/wlan0')).replace('/dev/McuCom',str(d/'dev/McuCom')).replace('/sys/module/firmware_class/parameters/path',str(d/'sys/firmware_path'))
        prefix=f'''mkdir -p {shlex.quote(str(proc))}/$$/fd
printf '%s\\n' '$$ (guard) S 200 200 200 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1' > {shlex.quote(str(proc))}/$$/stat
uname() {{ printf '%s\\n' 5.10.160-rt89-g9f9e9d18574d-dirty; }}
sha256sum() {{
 case "$1" in
  {shlex.quote(str(proc/'1/exe'))}) printf '%s  %s\\n' {shlex.quote(config.get('pid_sha',pid_sha))} "$1" ;;
  *) printf '%s  %s\\n' {shlex.quote(config.get('bb_sha',BBSHA))} "$1" ;;
 esac
}}
readlink() {{ if test "$1" = -f; then printf '%s\\n' {shlex.quote(config.get('exe','/bin/pid1'))}; else {('return 97' if config.get('readlink_fail') else '/usr/bin/readlink "$@"')}; fi; }}
hexdump() {{ case "$*" in *cmdline) printf '%s' {shlex.quote(config.get('argv','2f2e72616d2d72657475726e2f62696e2f706964310072657475726e00'))} ;; *) printf '%s' 0a ;; esac; }}
grep() {{
 case "$1" in
  '^Uid:') printf 'Uid: %s\\n' {shlex.quote(config.get('uid','0 0 0 0'))} ;;
  '^PPid:') case "$2" in */200/status) printf 'PPid: %s\\n' {shlex.quote(config.get('ancestor','1'))} ;; *) printf 'PPid: 200\\n' ;; esac ;;
  *) return 97 ;;
 esac
}}
cat() {{
    if test "$1" = {shlex.quote(str(proc/config.get('read_fail','never')))}; then return 97; fi
    /usr/bin/cat "$@"
}}
stat() {{
    if test {shlex.quote(str(config.get('tty_stat_error',False)))} = True; then return 97; fi
    if test {shlex.quote(str(config.get('tty_stat','')))} != ''; then printf '%s\\n' {shlex.quote(str(config.get('tty_stat','')))}; else /usr/bin/stat "$@"; fi
}}
losetup() {{ {('return 97' if config.get('loop_fail') else '/usr/bin/cat ' + shlex.quote(str(proc/'loops')))}; }}
'''
        if config.get('guard_fd'):
            target,fd=config['guard_fd']
            prefix += f'/usr/bin/ln -s {shlex.quote(target)} {shlex.quote(str(proc))}/$$/fd/{fd}\n'
        script=d/'guard-fixture.sh'; script.write_text(prefix+translated)
        run=subprocess.run([str(QEMU),str(BB),'sh',str(script.resolve())],capture_output=True,text=True,timeout=15)
        (d/'stdout').write_text(run.stdout);(d/'stderr').write_text(run.stderr)
        ready=run.returncode==0 and READY in run.stdout.splitlines()
        check(name,ready==want,dict(returncode=run.returncode,ready=ready,expected_ready=want,fixture_sha256=sha(script)))
    check('review leaves guard unchanged', (HERE/'linux-return-guard.sh').read_text()==source)
    receipt=dict(total=len(checks),passed=sum(c['passed'] for c in checks),failed=sum(not c['passed'] for c in checks),checks=checks,guard_sha256=sha(HERE/'linux-return-guard.sh'),test_sha256=sha(Path(__file__)),board_tested=False,boundary='Exact BusyBox shell; proc/sys/existence paths redirected and external observations mocked. No hardware mount, native PID1 or reboot execution.')
    (output/'results.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:receipt[k] for k in ['total','passed','failed']}))
    print(json.dumps([c for c in checks if not c['passed']],indent=2))
    return bool(receipt['failed'])


if __name__=='__main__':
    raise SystemExit(main())
