su 0 sh -c '
printf "\nBEGIN_SD_STATE\n"
for node in /sys/firmware/devicetree/base/dwmmc@fe2b0000 /sys/firmware/devicetree/base/dwmmc@fe300000 /sys/firmware/devicetree/base/dwmmc@fe000000 /sys/firmware/devicetree/base/sdhci@fe310000
do
    printf "\nNODE %s\n" "$node"
    for property in status compatible
    do
        if [ -f "$node/$property" ]
        then
            printf "%s=" "$property"
            tr "\000" " " < "$node/$property"
            printf "\n"
        fi
    done
    for property in bus-width supports-sd non-removable broken-cd cd-gpios pinctrl-0 vmmc-supply vqmmc-supply
    do
        if [ -f "$node/$property" ]
        then
            printf "%s: " "$property"
            od -An -tx1 "$node/$property"
        fi
    done
done
printf "\nMMC_HOSTS\n"
ls -l /sys/class/mmc_host/
for card in /sys/bus/mmc/devices/*
do
    printf "\nCARD %s\n" "$card"
    for property in type name
    do
        if [ -f "$card/$property" ]
        then
            printf "%s=" "$property"
            cat "$card/$property"
        fi
    done
done
printf "\nMMC_DMESG\n"
dmesg | grep -i -e mmc -e sdhci -e dwmmc | tail -n 45
printf "\nEND_SD_STATE\n"
'
