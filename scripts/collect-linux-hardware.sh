#!/bin/sh
# Passive Linux hardware inventory. Run with Android /system/bin/sh or
# Linux sh. Only cat, mkdir, pwd, readlink, rm, grep, and uname are needed.
# Source trees must be trusted and stable while this script runs (no sandbox
# against concurrent path replacement). No device node is opened.
set -u
umask 077
tab=$(printf '\t')

usage() {
    printf 'Usage: sh %s [--root ROOT] OUTPUT_DIR\n' "$0" >&2
    printf 'Exit: 0 complete; 1 saved with missing/skipped/failed items; 2 usage/output error.\n' >&2
    exit 2
}

die() {
    printf '%s\n' "$*" >&2
    exit 2
}

root=/
offline=no
if [ "${1-}" = --root ]; then
    [ "$#" -ge 3 ] && [ -n "$2" ] || usage
    root=$2
    offline=yes
    shift 2
fi
[ "$#" -eq 1 ] && [ -n "$1" ] || usage
[ "$1" != --help ] || usage
root=$(CDPATH= cd -P "$root" 2>&1 && pwd -P) || die "Cannot open source root: $root"
case "$root" in /dev|/dev/*) die 'Source root must not be under /dev.' ;; esac
prefix=$root
[ "$prefix" != / ] || prefix=

# Resolve the output parent before creating anything, so /dev and source
# pseudo-filesystem aliases cannot be used as output locations.
case "$1" in /*) requested=$1 ;; *) requested=$PWD/$1 ;; esac
case "$requested" in */) die 'Output must name a directory without a trailing slash.' ;; esac
parent=${requested%/*}
[ -n "$parent" ] || parent=/
name=${requested##*/}
[ "$name" != . ] && [ "$name" != .. ] || die 'Invalid output directory.'
parent=$(CDPATH= cd -P "$parent" 2>&1 && pwd -P) || die 'Output parent must already exist.'
out=$parent/$name
case "$out" in
    /dev|/dev/*|/proc|/proc/*|/sys|/sys/*|"$prefix"/dev|"$prefix"/dev/*|"$prefix"/proc|"$prefix"/proc/*|"$prefix"/sys|"$prefix"/sys/*)
        die 'Output must be outside device and kernel metadata trees.' ;;
esac
[ ! -L "$out" ] || die 'Refusing a symlink output directory.'
if [ -e "$out" ]; then
    [ -d "$out" ] && [ -r "$out" ] && [ -w "$out" ] && [ -x "$out" ] || die 'Output is not an accessible directory.'
    for entry in "$out"/* "$out"/.[!.]* "$out"/..?*; do
        if [ -e "$entry" ] || [ -L "$entry" ]; then
            die 'Refusing to overwrite a nonempty output directory.'
        fi
    done
else
    mkdir "$out" || die 'Cannot create output directory.'
fi
printf 'status\tsource\tdestination\tdetail\n' > "$out/status.tsv" || die 'Cannot write status file.'
: > "$out/errors.log" || die 'Cannot write error log.'

record() {
    printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" >> "$out/status.tsv" || die 'Cannot save collection status.'
}

# readlink -f exists in Android toybox and GNU coreutils. Restrict resolved
# paths to the requested root's proc/sys namespace before reading contents.
resolve_source() {
    resolved=$(readlink -f "$prefix$1" 2>> "$out/errors.log") || {
        record missing "$1" - 'absent or inaccessible path'
        return 1
    }
    case "$resolved" in
        "$prefix"/proc/*|"$prefix"/sys/*) ;;
        *) record unsafe "$1" - 'resolved outside source proc/sys trees'; return 1 ;;
    esac
}

copy_file() (
    source=$1
    destination=$2
    if [ -L "$prefix$source" ]; then
        record unsafe "$source" "$destination" 'file symlink skipped'
        exit 0
    fi
    resolve_source "$source" || exit 0
    if [ ! -e "$resolved" ]; then
        record missing "$source" "$destination" 'not present'
    elif [ ! -f "$resolved" ]; then
        record unsafe "$source" "$destination" 'not a regular file'
    elif [ ! -r "$resolved" ]; then
        record error "$source" "$destination" 'not readable'
    elif mkdir -p "$out/${destination%/*}" 2>> "$out/errors.log" &&
            cat "$resolved" > "$out/$destination" 2>> "$out/errors.log"; then
        record ok "$source" "$destination" 'copied'
    else
        rm -f "$out/$destination"
        record error "$source" "$destination" 'copy failed; see errors.log'
    fi
)

# No tar/cp recursive traversal: skip all symlinks, FIFOs and device nodes.
# A recursive subshell keeps loop variables independent at every depth.
copy_tree() (
    source=$1
    destination=$2
    if [ ! -r "$source" ] || [ ! -x "$source" ]; then
        record error "${source#"$prefix"}" "$destination" 'directory not readable/searchable'
        exit 0
    fi
    mkdir -p "$out/$destination" 2>> "$out/errors.log" || {
        record error "${source#"$prefix"}" "$destination" 'cannot create destination'
        exit 0
    }
    record ok "${source#"$prefix"}" "$destination" 'directory visited'
    for entry in "$source"/* "$source"/.[!.]* "$source"/..?*; do
        [ -e "$entry" ] || [ -L "$entry" ] || continue
        leaf=${entry##*/}
        case "$leaf" in
            *"$tab"*|*'
'*) record unsafe "${source#"$prefix"}" "$destination" 'control character in filename'; continue ;;
        esac
        if [ -L "$entry" ]; then
            record skipped "${entry#"$prefix"}" "$destination/$leaf" 'device-tree symlink skipped'
        elif [ -d "$entry" ]; then
            copy_tree "$entry" "$destination/$leaf" || exit 2
        else
            copy_file "${entry#"$prefix"}" "$destination/$leaf" || exit 2
        fi
    done
)

collect_bus() (
    bus=$1
    path=/sys/bus/$bus/devices
    resolve_source "$path" || exit 0
    if [ ! -d "$resolved" ]; then
        record missing "$path" - 'bus directory absent'
        exit 0
    fi
    if [ ! -r "$resolved" ] || [ ! -x "$resolved" ]; then
        record error "$path" - 'bus directory not readable/searchable'
        exit 0
    fi
    found=no
    for entry in "$resolved"/*; do
        [ -e "$entry" ] || [ -L "$entry" ] || continue
        found=yes
        leaf=${entry##*/}
        case "$leaf" in *[!A-Za-z0-9._:+@-]*) record unsafe "$path" - 'unsupported device name'; continue ;; esac
        resolve_source "${entry#"$prefix"}" || continue
        [ -d "$resolved" ] || { record unsafe "$path/$leaf" - 'not a device directory'; continue; }
        device=$resolved
        if [ "$bus" = usb ]; then
            for attribute in idVendor idProduct bDeviceClass product; do
                copy_file "${device#"$prefix"}/$attribute" "$bus/$leaf/$attribute" || exit 2
            done
        else
            copy_file "${device#"$prefix"}/modalias" "$bus/$leaf/modalias" || exit 2
            # Driver binding is link text only; never traverse its target.
            if [ -L "$device/driver" ]; then
                if mkdir -p "$out/$bus/$leaf" 2>> "$out/errors.log" &&
                        readlink "$device/driver" > "$out/$bus/$leaf/driver" 2>> "$out/errors.log"; then
                    record ok "$path/$leaf/driver" "$bus/$leaf/driver" 'link text only'
                else
                    rm -f "$out/$bus/$leaf/driver"
                    record error "$path/$leaf/driver" - 'readlink failed'
                fi
            else
                record missing "$path/$leaf/driver" - 'no driver link'
            fi
        fi
    done
    [ "$found" = yes ] || record missing "$path" - 'no bus entries'
)

printf 'Saving hardware metadata locally to %s. Nothing is uploaded.\n' "$out"
printf 'Raw device trees may contain serial numbers or MAC addresses; review before sharing.\n'
if [ "$offline" = yes ]; then
    record offline uname - 'host uname omitted; target kernel version is in proc/version if available'
elif uname -a > "$out/uname.txt" 2>> "$out/errors.log"; then
    record ok uname uname.txt 'running kernel'
else
    record error uname uname.txt 'uname failed'
fi

# Top-level copies use ./ to retain a parent component for copy_file.
# Every subshell boundary propagates fatal output/status failures. Missing
# source metadata is recorded and returns normally so collection can continue.
copy_file /sys/firmware/fdt ./fdt.dtb || exit 2
copy_file /proc/config.gz ./config.gz || exit 2
for item in version asound/cards asound/pcm bus/input/devices; do
    copy_file "/proc/$item" "proc/$item" || exit 2
done

tree_found=no
for candidate in /sys/firmware/devicetree/base /proc/device-tree; do
    if resolve_source "$candidate" && [ -d "$resolved" ]; then
        copy_tree "$resolved" devicetree || exit 2
        tree_found=yes
        break
    fi
done
[ "$tree_found" = yes ] || record missing device-tree devicetree 'neither supported device-tree path is available'
for bus in usb i2c spi; do
    collect_bus "$bus" || exit 2
done

grep -Eq '^(missing|error|unsafe|skipped)[[:space:]]' "$out/status.tsv"
summary_status=$?
case "$summary_status" in
    0)
        printf 'Snapshot is incomplete. Review status.tsv and errors.log for missing or failed items.\n'
        exit 1 ;;
    1)
        printf 'All requested metadata was copied; see status.tsv.\n' ;;
    *)
        die 'Cannot check collection status; snapshot completeness is unknown.' ;;
esac
