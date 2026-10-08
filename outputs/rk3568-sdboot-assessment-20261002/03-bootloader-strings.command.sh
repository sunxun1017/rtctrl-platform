su 0 sh -c '
printf "\nBEGIN_BOOTLOADER_INSPECTION\n"
command -v strings
ls -l /dev/block/by-name/uboot
if [ -r /dev/block/by-name/uboot ]
then
    printf "\nUBOOT_RECOGNIZABLE_STRINGS\n"
    strings /dev/block/by-name/uboot | grep -E "^U-Boot |^bootcmd=|^boot_targets=|^bootdelay=|^bootcmd_mmc[0-9]=|^mmc_boot=|^distro_bootcmd=|^Scanning mmc|^Bootdev\(" | head -n 25
fi
printf "\nKERNEL_SD_CONFIG\n"
if [ -r /proc/config.gz ]
then
    zcat /proc/config.gz | grep -E "^CONFIG_MMC=|^CONFIG_MMC_BLOCK=|^CONFIG_MMC_DW=|^CONFIG_MMC_DW_ROCKCHIP=|^CONFIG_MMC_SDHCI_OF_DWCMSHC="
fi
printf "\nEND_BOOTLOADER_INSPECTION\n"
'
