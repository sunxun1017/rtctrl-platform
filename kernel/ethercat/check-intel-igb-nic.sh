#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 NETWORK_INTERFACE" >&2
  exit 2
fi

interface="$1"
sysfs="/sys/class/net/${interface}"
if [[ ! -d "${sysfs}" || ! -e "${sysfs}/device/vendor" ||
      ! -e "${sysfs}/device/device" ]]; then
  echo "not a PCI network interface: ${interface}" >&2
  exit 2
fi

vendor="$(<"${sysfs}/device/vendor")"
device="$(<"${sysfs}/device/device")"
mac="$(<"${sysfs}/address")"
driver="$(basename "$(readlink -f "${sysfs}/device/driver")")"
pci_address="$(basename "$(readlink -f "${sysfs}/device")")"

case "${vendor}:${device}" in
  0x8086:0x1521|0x8086:0x1522|0x8086:0x1523|0x8086:0x1524|\
  0x8086:0x1533|0x8086:0x1536|0x8086:0x1537|0x8086:0x1538|\
  0x8086:0x1539|0x8086:0x157b|0x8086:0x157c)
    ;;
  *)
    echo "unsupported NIC ${vendor}:${device}; expected Intel I210/I211/I350" >&2
    exit 1
    ;;
esac

if [[ "${driver}" != "igb" && "${driver}" != "ec_igb" ]]; then
  echo "unexpected driver ${driver}; expected igb before takeover or ec_igb after" >&2
  exit 1
fi

if command -v ip >/dev/null 2>&1 &&
   ip route show default 2>/dev/null | grep -Eq "(^| )dev ${interface}( |$)"; then
  echo "refusing management/default-route interface: ${interface}" >&2
  echo "install a physically dedicated I210/I211/I350 port for EtherCAT" >&2
  exit 1
fi

echo "dedicated EtherCAT NIC candidate accepted"
echo "  interface: ${interface}"
echo "  PCI:       ${pci_address} (${vendor}:${device})"
echo "  driver:    ${driver}"
echo "  MAC:       ${mac}"
echo "IgH config: MASTER0_DEVICE=\"${mac}\" DEVICE_MODULES=\"igb\""
