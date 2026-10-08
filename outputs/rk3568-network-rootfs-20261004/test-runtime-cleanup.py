#!/usr/bin/env python3
"""Execute the real cleanup shell fragments with mocked hardware operations."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def extract(source, variable_start, end_comment):
    """Keep the original variable assignments, cleanup, and exit trap verbatim."""
    start = source.index(variable_start)
    cleanup_start = source.index("cleanup() {\n", start)
    exit_start = source.index("on_exit() {\n", cleanup_start)
    trap_end = source.index(end_comment, exit_start)
    return {
        "variables": source[start:cleanup_start],
        "cleanup": source[cleanup_start:exit_start],
        "exit_trap": source[exit_start:trap_end],
    }


MOCKS = r'''
log() {
    printf '%s\n' "$*" >&3
}
sync() {
    log sync
}
umount() {
    log "umount $*"
    if [ "$fail_umount_once" = 1 ] && [ "$1" = "$fail_target" ]; then
        fail_umount_once=0
        return 1
    fi
    return 0
}
losetup() {
    log "losetup $*"
    case "$1" in
        -a)
            if [ "$leftover" = 1 ]; then
                printf '/dev/loop77: mock ordinary-file attachment\n'
            fi
            ;;
        -d)
            test "$2" = /dev/loop77
            ;;
        *) return 99 ;;
    esac
}
rm() {
    log "rm $*"
    test "$1" = -f
    test "$2" = "$ram_tmp/rtctrl-rootfs-ram-probe"
    if [ "$fail_rm_once" = 1 ]; then
        fail_rm_once=0
        return 1
    fi
    command /bin/rm -f "$2"
}
chroot() {
    log "chroot probe"
    # The real probe snippet must call this exact chroot operation.
    test "$1" = "$point"
    test "$2" = /bin/sh
    test "$3" = -c
    printf partial-probe > "$ram_tmp/rtctrl-rootfs-ram-probe"
    return 9
}
mount() {
    log "UNEXPECTED_MOUNT $*"
    return 99
}
'''

ROOT_FLAGS = r'''
root_mounted=1
dev_mounted=1
pts_mounted=1
proc_mounted=1
sys_mounted=1
tmp_mounted=1
loop=/dev/loop77
'''

REPORT_ROOT = r'''
report_flags() {
    printf '%s_FLAGS=%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "$1" "$probe_owned" "$tmp_mounted" "$pts_mounted" "$sys_mounted" \
        "$proc_mounted" "$dev_mounted" "$root_mounted" "$loop"
}
attempt() {
    if cleanup; then
        result=0
    else
        result=$?
    fi
    printf '%s_EXIT=%s\n' "$1" "$result"
    report_flags "$1"
}
'''


def execute(work, name, fragment, body, backing="owned", trap=""):
    folder = work / name
    folder.mkdir()
    point = folder / "point"
    ram_tmp = folder / "ram"
    point.mkdir()
    ram_tmp.mkdir()
    image = folder / "ordinary-rootfs.img"
    image.write_bytes(b"not mounted: test fixture only")
    sys_class = folder / "mock-sys-class-block"
    loop_folder = sys_class / "loop77/loop"
    loop_folder.mkdir(parents=True)
    (loop_folder / "backing_file").write_text(str(image) if backing == "owned" else "/unowned-ordinary-file")
    prefix = (
        "#!/bin/sh\nset -eu\n"
        "exec 3> " + shlex.quote(str(folder / "trace.txt")) + "\n"
        "point=" + shlex.quote(str(point)) + "\n"
        "ram_tmp=" + shlex.quote(str(ram_tmp)) + "\n"
        "image=" + shlex.quote(str(image)) + "\n"
        "fail_target=\nfail_umount_once=0\nfail_rm_once=0\nleftover=0\n"
    )
    transformed = fragment["cleanup"].replace("/sys/class/block", str(sys_class))
    script = prefix + MOCKS + fragment["variables"] + transformed + REPORT_ROOT + trap + body
    script_path = folder / "exercise.sh"
    script_path.write_text(script)
    result = subprocess.run(["/bin/sh", str(script_path)], capture_output=True, text=True, timeout=10)
    trace = (folder / "trace.txt").read_text().splitlines()
    trace = [line.replace(str(point), "POINT").replace(str(ram_tmp), "RAM") for line in trace]
    stdout = result.stdout.replace(str(point), "POINT").replace(str(ram_tmp), "RAM")
    if result.stderr:
        raise AssertionError(name + " unexpected stderr: " + result.stderr)
    return {
        "name": name, "exit_code": result.returncode, "commands": trace,
        "stdout": stdout, "probe_remains": (ram_tmp / "rtctrl-rootfs-ram-probe").exists(),
        "sys_path_replacements": fragment["cleanup"].count("/sys/class/block"),
    }


def require(result, exit_code, commands, snippets=(), probe=False):
    assert result["exit_code"] == exit_code, result
    assert result["commands"] == commands, result
    assert result["probe_remains"] == probe, result
    for snippet in snippets:
        assert snippet in result["stdout"], result
    return result


def main():
    root_source = (HERE / "rootfs-check.sh").read_text()
    linux_source = (HERE / "linux-rootfs-check.sh").read_text()
    root = extract(root_source, "loop=\nroot_mounted=0\n", "# Read-only at both loop")
    linux = extract(linux_source, "cache_mounted=0\npts_mounted=0\n", "test -z \"$(grep ' /dev/pts '")
    probe_start = root_source.index('test ! -e "$ram_tmp/rtctrl-rootfs-ram-probe"')
    probe_end = root_source.index("\ncleanup\n", probe_start)
    probe_fragment = root_source[probe_start:probe_end] + "\n"
    build = HERE / "build"
    if build.is_symlink() or not build.is_dir():
        raise ValueError("Need the existing ordinary build directory")
    results = []
    children = ["umount POINT/tmp", "umount POINT/dev/pts", "umount POINT/sys", "umount POINT/proc"]
    parent = ["umount POINT/dev", "sync", "umount POINT", "losetup -d /dev/loop77"]
    with tempfile.TemporaryDirectory(prefix="runtime-cleanup-", dir=build) as temporary:
        work = Path(temporary)
        result = execute(work, "child-first-failure", root, ROOT_FLAGS + r'''
probe_owned=1
printf owned-probe > "$ram_tmp/rtctrl-rootfs-ram-probe"
fail_target="$point/tmp"
fail_umount_once=1
log FIRST_ATTEMPT
attempt FIRST
log RETRY_ATTEMPT
attempt RETRY
''')
        results.append(require(result, 0,
            ["FIRST_ATTEMPT", "rm -f RAM/rtctrl-rootfs-ram-probe"] + children +
            ["RETRY_ATTEMPT", "umount POINT/tmp"] + parent,
            ["FIRST_EXIT=1", "FIRST_FLAGS=0,1,0,0,0,1,1,/dev/loop77",
             "RETRY_EXIT=0", "RETRY_FLAGS=0,0,0,0,0,0,0,"]))
        result = execute(work, "probe-remove-first-failure", root, ROOT_FLAGS + r'''
probe_owned=1
printf owned-probe > "$ram_tmp/rtctrl-rootfs-ram-probe"
fail_rm_once=1
log FIRST_ATTEMPT
attempt FIRST
test -f "$ram_tmp/rtctrl-rootfs-ram-probe"
log RETRY_ATTEMPT
attempt RETRY
''')
        results.append(require(result, 0,
            ["FIRST_ATTEMPT", "rm -f RAM/rtctrl-rootfs-ram-probe"] + children +
            ["RETRY_ATTEMPT", "rm -f RAM/rtctrl-rootfs-ram-probe"] + parent,
            ["FIRST_EXIT=1", "FIRST_FLAGS=1,0,0,0,0,1,1,/dev/loop77",
             "RETRY_EXIT=0", "RETRY_FLAGS=0,0,0,0,0,0,0,"]))
        result = execute(work, "probe-create-failure-exit-trap", root,
                         ROOT_FLAGS + probe_fragment, trap=root["exit_trap"])
        results.append(require(result, 9,
            ["chroot probe", "rm -f RAM/rtctrl-rootfs-ram-probe"] + children + parent,
            ["ROOTFS_MOUNTS_RELEASED"]))
        result = execute(work, "loop-backing-mismatch", root, ROOT_FLAGS + "attempt FIRST\n", backing="unowned")
        results.append(require(result, 0, children + parent[:-1],
            ["LOOP_OWNERSHIP_MISMATCH", "FIRST_EXIT=1",
             "FIRST_FLAGS=0,0,0,0,0,0,0,/dev/loop77"]))
        result = execute(work, "linux-wrapper-leftover-loop", linux, r'''
cache_mounted=1
pts_mounted=1
leftover=1
if cleanup; then
    status=0
else
    status=$?
fi
printf 'FIRST_EXIT=%s\nFLAGS=%s,%s\n' "$status" "$cache_mounted" "$pts_mounted"
''')
        results.append(require(result, 0, ["losetup -a"],
            ["LOOP_STILL_ATTACHED_STAY_IN_LINUX", "FIRST_EXIT=1", "FLAGS=1,1"]))
        result = execute(work, "linux-wrapper-child-failure-exit-trap", linux, r'''
cache_mounted=1
pts_mounted=1
leftover=1
false
''', trap=linux["exit_trap"])
        results.append(require(result, 1, ["losetup -a"], ["LOOP_STILL_ATTACHED_STAY_IN_LINUX"]))
        result = execute(work, "linux-wrapper-clean-loop-list", linux, r'''
cache_mounted=1
pts_mounted=1
cleanup
printf 'FLAGS=%s,%s\n' "$cache_mounted" "$pts_mounted"
''')
        results.append(require(result, 0, ["losetup -a", "sync", "umount /mnt/cache", "umount /dev/pts"], ["FLAGS=0,0"]))
    # Avoid reporting evidence for source that was edited during the checks.
    assert (HERE / "rootfs-check.sh").read_text() == root_source
    assert (HERE / "linux-rootfs-check.sh").read_text() == linux_source
    summary = {
        "status": "RUNTIME_CLEANUP_HOST_TESTS_PASSED", "checks": len(results),
        "sources": {"rootfs-check.sh": digest(root_source), "linux-rootfs-check.sh": digest(linux_source)},
        "extracted_fragments": {
            "rootfs_cleanup_sha256": digest(root["cleanup"]),
            "rootfs_exit_trap_sha256": digest(root["exit_trap"]),
            "rootfs_probe_sha256": digest(probe_fragment),
            "linux_wrapper_cleanup_sha256": digest(linux["cleanup"]),
        },
        "transformations": ["Only /sys/class/block in the rootfs cleanup copy is replaced with a temporary ordinary directory"],
        "mocked_operations": ["umount", "sync", "losetup", "chroot", "rm"],
        "real_mount_device_or_chroot_operations": False,
        "board_tested": False, "results": results,
    }
    destination = build / "runtime-cleanup-result.json"
    with destination.open("x") as stream:
        json.dump(summary, stream, indent=2)
        stream.write("\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
