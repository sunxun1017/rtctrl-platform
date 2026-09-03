#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! -f "$1" ]]; then
  echo "usage: $0 KERNEL_CONFIG" >&2
  exit 2
fi

config="$1"
required=(
  CONFIG_PREEMPT_RT=y
  CONFIG_HIGH_RES_TIMERS=y
  CONFIG_HZ_PERIODIC=y
  CONFIG_HZ_1000=y
  CONFIG_PCI=y
  CONFIG_PCIEPORTBUS=y
)
for setting in "${required[@]}"; do
  if ! grep -Fqx -- "${setting}" "${config}"; then
    echo "required kernel setting missing: ${setting}" >&2
    exit 1
  fi
done

for setting in CONFIG_NO_HZ CONFIG_NO_HZ_FULL CONFIG_WERROR; do
  if ! grep -Fqx -- "# ${setting} is not set" "${config}"; then
    echo "real-time policy requires '# ${setting} is not set'" >&2
    exit 1
  fi
done
if grep -Fqx -- "CONFIG_RT_GROUP_SCHED=y" "${config}"; then
  echo "real-time policy forbids CONFIG_RT_GROUP_SCHED=y" >&2
  exit 1
fi

echo "kernel configuration contract verified: ${config}"
