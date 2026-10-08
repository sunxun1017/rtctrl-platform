#!/system/bin/sh
# The frozen host candidate-v1 is the complete backup of this one cache file.
set -eu

case "${1-}" in
    --check|--reclaim)
        action=$1
        ;;
    *)
        exit 2
        ;;
esac

test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop ro.build.version.release)" = 11
test "$(getprop sys.boot_completed)" = 1
test "$(realpath /cache)" = /cache
directory=/cache/rtctrl-bootm-ram-20261005-v1
obsolete=$directory/boot-linux-ram-v1.img

check_file()
{
    path=$1
    bytes=$2
    digest=$3
    test -f "$path"
    test ! -L "$path"
    test "$(realpath "$path")" = "$path"
    test "$(stat -c '%u:%g:%h:%s:%F' "$path")" = "0:0:1:$bytes:regular file"
    test "$(sha256sum "$path")" = "$digest  $path"
}

check_protected()
{
    test "$(sha256sum /dev/block/by-name/boot)" = '0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28  /dev/block/by-name/boot'
    test "$(sha256sum /dev/block/by-name/uboot)" = '4758af21c8f5751cc92166baf7a6e4a79c17d0f87ce9bad64a16af91a125447e  /dev/block/by-name/uboot'
    test "$(sha256sum /dev/block/by-name/trust)" = 'bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8  /dev/block/by-name/trust'
    test "$(sha256sum /dev/block/by-name/dtbo)" = '59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d  /dev/block/by-name/dtbo'
    test "$(sha256sum /dev/block/by-name/vbmeta)" = '76ff77959f2451ee3838de5b2d90a0e21017345cac4f7ce56c9da7a630edc752  /dev/block/by-name/vbmeta'
    check_file /cache/rtctrl-source-userspace-20261004/rootfs.ext4 67108864 4fcebae566d889072954b2f5b220474fe9accd75bbb48471023f24841b6ed95e
    test "$(sha256sum /cache/rtctrl-network-rootfs-20261004/rootfs.img)" = '32273043cbc6656612dbf8a2e31866b27080ef26b8ee44b1ad83f91ae6c330a3  /cache/rtctrl-network-rootfs-20261004/rootfs.img'
    check_file /cache/rtctrl-rcu-reset-20261004/Image 34755072 e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457
    check_file /cache/rtctrl-display-20261005-v1/Image 34755072 dafdda0cc331605471c1b24a33cb4f037bf4af79b4145eabf12513dabf4d86a7
    check_file /cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4 16777216 3a87bd54f44b1e5d20701514c26669d086123e8b2ee8ed9087cc118c12fc679d
    check_file /cache/rtctrl-pid1-20261005-v3/initramfs-pid1.cpio.gz 972203 54db3bb6fa94dd1570a306aa90e3caa6ae5ed7bb6b93d96afcae0c5f8881afef
    check_file "$directory/boot-original.img" 41943040 0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28
}

test -d "$directory"
test ! -L "$directory"
test "$(realpath "$directory")" = "$directory"
test "$(stat -c '%u:%g:%a' "$directory")" = 0:0:700
check_file "$obsolete" 41943040 c55feb66c8acb9e66cc89af7c8a70077419b16a2a32fdaadb74ee068170d4d3e
check_protected
df -k /cache
echo CANDIDATE_V1_AND_PROTECTED_INPUTS_VERIFIED

if test "$action" = --check; then
    exit 0
fi

# A literal ordinary file, with no recursive deletion or partition access.
rm -- /cache/rtctrl-bootm-ram-20261005-v1/boot-linux-ram-v1.img
sync
test ! -e "$obsolete"
test ! -L "$obsolete"
check_protected
df -k /cache
echo CANDIDATE_V1_ARCHIVED_CACHE_COPY_RECLAIMED
