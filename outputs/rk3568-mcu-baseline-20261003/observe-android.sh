#!/system/bin/sh
# Passive diagnostic probe; never opens UART/MCU devices or sends bus messages.
set -eu

output_dir=${1:?Provide a new diagnostic directory}
trace_root=/sys/kernel/debug/tracing
instance_name=rtctrl_mcu_20261003_$$
instance_dir=$trace_root/instances/$instance_name
instance_created=0

if [ -e "$output_dir" ]; then
    echo "Refusing existing diagnostic directory: $output_dir" >&2
    exit 1
fi

mkdir "$output_dir"
chmod 700 "$output_dir"

cleanup() {
    cleanup_status=$?
    cleanup_failed=0
    trap - EXIT HUP INT TERM

    if [ "$instance_created" -eq 1 ]; then
        if ! printf '0\n' > "$instance_dir/tracing_on"; then
            cleanup_failed=1
        fi

        for event_name in i2c_read i2c_write i2c_reply i2c_result; do
            if [ -e "$instance_dir/events/i2c/$event_name/enable" ]; then
                if ! printf '0\n' > "$instance_dir/events/i2c/$event_name/enable"; then
                    cleanup_failed=1
                fi
            fi
        done

        if [ -e "$instance_dir/events/sched/sched_switch/enable" ]; then
            if ! printf '0\n' > "$instance_dir/events/sched/sched_switch/enable"; then
                cleanup_failed=1
            fi
        fi

        if ! rmdir "$instance_dir"; then
            cleanup_failed=1
        fi

        if [ -e "$instance_dir" ]; then
            cleanup_failed=1
        fi
    fi

    if [ "$cleanup_failed" -ne 0 ]; then
        echo "Observation cleanup failed; inspect the private instance" >&2
        exit 1
    fi

    printf 'PRIVATE_TRACE_INSTANCE_REMOVED\n' > "$output_dir/cleanup.txt"
    exit "$cleanup_status"
}

trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

{
    id
    uname -r
    getprop ro.build.version.release
    cat /proc/uptime
    cat "$trace_root/tracing_on"
    cat "$trace_root/current_tracer"
    ls "$trace_root/instances"
} > "$output_dir/state-before.txt"

{
    ls -l /dev/ttySMT0 /dev/ttySMT1 /dev/ttySMT4 /dev/McuCom
    readlink /sys/class/tty/ttySMT0/device
    readlink /sys/class/tty/ttySMT1/device
    readlink /sys/class/tty/ttySMT4/device
    readlink /sys/bus/i2c/devices/5-0062/driver
    cat /sys/bus/i2c/devices/5-0062/uevent
    ls -l /sys/firmware/devicetree/base/i2c@fe5e0000/mcuinf@62
} > "$output_dir/bindings.txt"

# One native listing avoids spawning a process for each of thousands of FDs.
# Filter on the board; unrelated descriptor paths and process argv are omitted.
ls -l /proc/[0-9]*/fd 2>/dev/null \
    | awk '
        /^\/proc\/[0-9]+\/fd:$/ {
            owner = $0
        }
        / -> \/dev\/(ttySMT[0-9]+|McuCom)$/ {
            print owner
            print $0
        }
    ' > "$output_dir/device-owners.txt"

# This private instance does not reset or alter the existing root/wifi tracer.
mkdir "$instance_dir"
instance_created=1
printf '0\n' > "$instance_dir/tracing_on"
printf '64\n' > "$instance_dir/buffer_size_kb"
printf 'nop\n' > "$instance_dir/current_tracer"

for event_name in i2c_read i2c_write i2c_reply; do
    event_dir=$instance_dir/events/i2c/$event_name
    printf 'adapter_nr == 5 && addr == 98\n' > "$event_dir/filter"
    cat "$event_dir/filter" > "$output_dir/$event_name-filter.txt"
    printf '1\n' > "$event_dir/enable"
done

# Result records have no address field; correlation with address-filtered
# messages is required before interpreting a result as an MCU transfer.
printf 'adapter_nr == 5\n' > "$instance_dir/events/i2c/i2c_result/filter"
printf '1\n' > "$instance_dir/events/i2c/i2c_result/enable"

# Scheduling of this shell supplies a positive control for the trace pipeline.
# It does not cause any I2C/UART operation and excludes unrelated process data.
printf 'prev_pid == %s\n' "$$" \
    > "$instance_dir/events/sched/sched_switch/filter"
printf '1\n' > "$instance_dir/events/sched/sched_switch/enable"

cat /proc/uptime > "$output_dir/observation-start.txt"
cat /proc/tty/driver/serial > "$output_dir/uart-before.txt"
printf '1\n' > "$instance_dir/tracing_on"

iteration=0
while [ "$iteration" -lt 6 ]; do
    sleep 5
    iteration=$((iteration + 1))
done

printf '0\n' > "$instance_dir/tracing_on"
cat /proc/tty/driver/serial > "$output_dir/uart-after.txt"
cat /proc/uptime > "$output_dir/observation-end.txt"
cat "$instance_dir/trace" > "$output_dir/mcu.trace.txt"

for stats_path in "$instance_dir"/per_cpu/cpu*/stats; do
    printf '%s\n' "${stats_path#"$instance_dir"/}"
    cat "$stats_path"
done > "$output_dir/trace-stats.txt"

{
    cat "$trace_root/tracing_on"
    cat "$trace_root/current_tracer"
} > "$output_dir/state-after.txt"

printf 'MCU_PASSIVE_OBSERVATION_SAVED\n'
