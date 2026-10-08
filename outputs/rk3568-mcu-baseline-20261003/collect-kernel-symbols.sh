#!/system/bin/sh
# Capture selected symbol addresses for offline analysis of the backed-up Image.
# The device ABI is not called. Restore the original pointer visibility setting.
set -eu

output_file=${1:?Provide a new private symbol file}
setting=/proc/sys/kernel/kptr_restrict
original=$(cat "$setting")

if [ -e "$output_file" ]; then
    echo "Refusing existing symbol file" >&2
    exit 1
fi

restore() {
    restore_status=$?
    trap - EXIT HUP INT TERM
    printf '%s\n' "$original" > "$setting"

    if [ "$(cat "$setting")" != "$original" ]; then
        echo "Pointer visibility restoration failed" >&2
        exit 1
    fi

    printf 'KPTR_RESTRICT_RESTORED=%s\n' "$original"
    exit "$restore_status"
}

trap restore EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

printf '0\n' > "$setting"
grep -E ' (_text|_stext|stext|MCU_[A-Za-z0-9_]+|mcuinterface_[A-Za-z0-9_]+|Write[A-Za-z0-9_]*ToMCU|[A-Za-z0-9_]*[Mm][Cc][Uu][A-Za-z0-9_]*|i2c_[A-Za-z0-9_]*|__i2c_transfer|device_property_read_bool|kthread_create_on_node|kernel_restart|msleep|__const_udelay|__udelay|__delay|schedule_timeout|copy_from_user|copy_to_user|_copy_from_user|_copy_to_user)$' \
    /proc/kallsyms > "$output_file"
chmod 600 "$output_file"
