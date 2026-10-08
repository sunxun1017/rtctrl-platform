su 0 sh -c '
printf "\nBEGIN_SD_BOOT_POLICY\n"
strings /dev/block/by-name/uboot | grep -E "^rkimg_bootdev=|^preboot=|^boot_prefixes=|^boot_syslinux_conf=|^scan_dev_for_extlinux=|^scan_dev_for_scripts=|^scan_dev_for_boot_part=|^scan_dev_for_boot=|^Boot from SDcard$" | head -n 20
printf "\nEND_SD_BOOT_POLICY\n"
'
