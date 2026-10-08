#!/system/bin/sh
# Three obsolete ordinary Image copies; complete host backups are required first.
set -eu
test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop ro.build.version.release)" = 11
test "$(getprop sys.boot_completed)" = 1
test "$(readlink -f /cache)" = /cache

check_file()
{
    path=$1
    bytes=$2
    digest=$3
    test -f "$path"
    test ! -L "$path"
    test "$(readlink -f "$path")" = "$path"
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
    test "$(sha256sum /cache/rtctrl-source-userspace-20261004/rootfs.ext4)" = '4fcebae566d889072954b2f5b220474fe9accd75bbb48471023f24841b6ed95e  /cache/rtctrl-source-userspace-20261004/rootfs.ext4'
    test "$(sha256sum /cache/rtctrl-network-rootfs-20261004/rootfs.img)" = '32273043cbc6656612dbf8a2e31866b27080ef26b8ee44b1ad83f91ae6c330a3  /cache/rtctrl-network-rootfs-20261004/rootfs.img'
    test "$(sha256sum /cache/rtctrl-rcu-reset-20261004/Image)" = 'e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457  /cache/rtctrl-rcu-reset-20261004/Image'
    test "$(sha256sum /cache/rtctrl-display-20261005-v1/Image)" = 'dafdda0cc331605471c1b24a33cb4f037bf4af79b4145eabf12513dabf4d86a7  /cache/rtctrl-display-20261005-v1/Image'
}

check_file /cache/rtctrl-source-kernel-20261004/Image 34888192 c0efb3bb522005cf106500c26c5c2c02d5905c2bfa9ecb273c2663db20aad4ec
check_file /cache/rtctrl-source-userspace-20261004/Image 34755072 b230838582b655f7786564ff21670ab1cd29172488df9c367a77d7005708c260
check_file /cache/rtctrl-source-wifi-20261004/Image 34755072 e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457
check_protected
echo CACHE_PROTECTED_BEFORE_OK
df -k /cache

rm -- /cache/rtctrl-source-kernel-20261004/Image
rm -- /cache/rtctrl-source-userspace-20261004/Image
rm -- /cache/rtctrl-source-wifi-20261004/Image
sync

for path in /cache/rtctrl-source-kernel-20261004/Image /cache/rtctrl-source-userspace-20261004/Image /cache/rtctrl-source-wifi-20261004/Image; do
    test ! -e "$path"
    test ! -L "$path"
done
check_protected
echo CACHE_PROTECTED_AFTER_OK
df -k /cache
echo CACHE_THREE_ARCHIVED_IMAGES_RECLAIMED
