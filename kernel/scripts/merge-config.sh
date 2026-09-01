#!/usr/bin/env sh
set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "usage: $0 KERNEL_SOURCE OUTPUT_CONFIG [diagnostics]" >&2
  exit 2
fi

kernel_source=$1
output_config=$2
profile=${3:-production}
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
merge_script="$kernel_source/scripts/kconfig/merge_config.sh"

if [ ! -x "$merge_script" ]; then
  echo "missing executable: $merge_script" >&2
  exit 1
fi
if [ "$profile" != "production" ] && [ "$profile" != "diagnostics" ]; then
  echo "profile must be production or diagnostics" >&2
  exit 2
fi

output_dir=$(dirname -- "$output_config")
mkdir -p "$output_dir"
base="$project_root/kernel/config/rt-periodic-production.cfg"
if [ "$profile" = "diagnostics" ]; then
  KCONFIG_CONFIG="$output_config" "$merge_script" -m -O "$output_dir" "$base" \
    "$project_root/kernel/config/rt-diagnostics.cfg"
else
  KCONFIG_CONFIG="$output_config" "$merge_script" -m -O "$output_dir" "$base"
fi

echo "fragment merged into $output_config"
echo "next: make -C '$kernel_source' KCONFIG_CONFIG='$output_config' olddefconfig"
echo "then audit the final config; unresolved symbols are not silently accepted"
