#!/bin/sh
# Compile an independent diagnostic for the fingerprinted original driver.
set -eu

source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
executable=${1:-$source_dir/private/read-cached-mcu-info}

if [ -e "$executable" ]; then
    echo "Refusing an existing executable: $executable" >&2
    exit 1
fi

mkdir -p "$(dirname -- "$executable")"
aarch64-linux-gnu-gcc -O2 -Wall -Wextra -Werror -static \
    "$source_dir/read-cached-mcu-info.c" -o "$executable"

aarch64-linux-gnu-readelf -h -l -d "$executable" > "$executable.elf.txt"
if grep -Eq 'INTERP|NEEDED' "$executable.elf.txt"; then
    echo 'Unexpected dynamic runtime dependency' >&2
    exit 1
fi

sha256sum "$executable"
