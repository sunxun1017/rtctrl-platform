#!/bin/sh
# This kernel's copystring parameter retains newline bytes. Restore the known empty value.
set -eu
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
modules=$(cat /proc/modules)
test -z "$modules"
parameter=/sys/module/firmware_class/parameters/path
before=$(hexdump -v -e '1/1 "%02x"' "$parameter")
test "$before" = 0a0a
hexdump -C "$parameter"
# param_set_copystring uses strlen/strcpy; a single NUL supplies the empty string.
printf '\000' > "$parameter"
after=$(hexdump -v -e '1/1 "%02x"' "$parameter")
test "$after" = 0a
hexdump -C "$parameter"
echo FIRMWARE_CLASS_EMPTY_VALUE_RESTORED_BYTE_EXACT
