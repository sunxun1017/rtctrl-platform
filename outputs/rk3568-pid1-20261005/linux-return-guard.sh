#!/bin/sh
# Independent checks after native PID1 has returned to its RAM island.
set -eu
test "$#" = 0
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(sha256sum /proc/1/exe)" = '249cc1cfd87cbddc8618e81e6b8fd742526de78fd964d4a4b3b59b8a7d76368b  /proc/1/exe'
test "$(readlink -f /proc/1/exe)" = /bin/pid1
test "$(hexdump -v -e '1/1 "%02x"' /proc/1/cmdline)" = 2f2e72616d2d72657475726e2f62696e2f706964310072657475726e00
uid_fields=$(grep '^Uid:' /proc/self/status)
set -- $uid_fields
test "$#" = 5
test "$2:$3:$4:$5" = 0:0:0:0
modules=$(cat /proc/modules)
test -z "$modules"
loops=$(losetup -a)
test -z "$loops"
mounts=$(cat /proc/mounts)
root_seen=0
dev_seen=0
pts_seen=0
proc_seen=0
sys_seen=0
tmp_seen=0
run_seen=0
while read -r source target kind rest; do
    case "$target:$kind" in
        /:tmpfs) root_seen=$((root_seen + 1)) ;;
        /dev:devtmpfs) dev_seen=$((dev_seen + 1)) ;;
        /dev/pts:devpts) pts_seen=$((pts_seen + 1)) ;;
        /proc:proc) proc_seen=$((proc_seen + 1)) ;;
        /sys:sysfs) sys_seen=$((sys_seen + 1)) ;;
        /tmp:tmpfs) tmp_seen=$((tmp_seen + 1)) ;;
        /run:tmpfs) run_seen=$((run_seen + 1)) ;;
        *) exit 1 ;;
    esac
done <<EOF
$mounts
EOF
test "$root_seen:$dev_seen:$pts_seen:$proc_seen:$sys_seen:$tmp_seen:$run_seen" = 1:1:1:1:1:1:1
test ! -e /sys/class/net/wlan0
test ! -e /dev/McuCom
parent_fields=$(grep '^PPid:' /proc/$$/status)
set -- $parent_fields
test "$#" = 2
parent=$2
test "$parent" -gt 1
ancestor_fields=$(grep '^PPid:' /proc/$parent/status)
set -- $ancestor_fields
test "$#" = 2
test "$2" = 1
for process in /proc/[0-9]*; do
    test -d "$process" || continue
    pid=${process##*/}
    stat_line=$(cat "$process/stat")
    stat_tail=${stat_line##*) }
    set -- $stat_tail
    test "$#" -ge 20
    flags=$7
    if test "$pid" = "$parent"; then
        test "$3" = "$parent"
        test "$4" = "$parent"
    fi
    if test "$pid" != 1 && test $((flags & 2097152)) = 0; then
        case "$pid" in
            "$parent"|"$$") ;;
            *) exit 1 ;;
        esac
        test "$(sha256sum "$process/exe")" = "514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1  $process/exe"
    fi
    stdio_seen=0
    for fd in "$process"/fd/*; do
        test -L "$fd" || continue
        if test "$pid" = 1; then
            case "${fd##*/}" in
                0|1|2) ;;
                *) exit 1 ;;
            esac
        fi
        target=$(readlink "$fd")
        if test "$pid" = 1; then
            test "$target" = /dev/console
            stdio_seen=$((stdio_seen + 1))
        fi
        case "$target" in
            /dev/console|/dev/ttyFIQ0)
                case "${fd##*/}" in
                    0|1|2) ;;
                    *) exit 1 ;;
                esac
                ;;
            /tmp/pid1-return-guard.sh)
                test "$pid" = "$$"
                test "${fd##*/}" = 10
                ;;
            /dev/tty)
                test "$pid" = "$parent"
                test "${fd##*/}" = 10
                test "$(stat -L -c '%F:%t:%T' "$fd")" = 'character special file:5:0'
                ;;
            *) exit 1 ;;
        esac
    done
    if test "$pid" = 1; then
        test "$stdio_seen" = 3
    fi
done
test "$(hexdump -v -e '1/1 "%02x"' /sys/module/firmware_class/parameters/path)" = 0a
printf '%s\n' "$mounts"
echo PID1_INDEPENDENT_RAM_ONLY_RETURN_READY
