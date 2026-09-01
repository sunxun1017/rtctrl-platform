#!/usr/bin/env sh
set -eu

strict=0
if [ "${1:-}" = "--strict" ]; then
  strict=1
elif [ "$#" -ne 0 ]; then
  echo "usage: $0 [--strict]" >&2
  exit 2
fi

failures=0
warn() { printf 'WARN  %s\n' "$*"; }
pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; failures=$((failures + 1)); }

kernel_release=$(uname -r)
printf 'kernel=%s machine=%s\n' "$kernel_release" "$(uname -m)"

config_file=
temporary_config=
if [ -r /proc/config.gz ]; then
  temporary_config=$(mktemp)
  trap 'rm -f "$temporary_config"' EXIT HUP INT TERM
  gzip -cd /proc/config.gz > "$temporary_config"
  config_file=$temporary_config
elif [ -r "/boot/config-$kernel_release" ]; then
  config_file="/boot/config-$kernel_release"
fi

expect_enabled() {
  symbol=$1
  if [ -z "$config_file" ]; then
    if [ "$strict" -eq 1 ]; then
      fail "cannot inspect $symbol: running kernel config is unavailable"
    else
      warn "cannot inspect $symbol: running kernel config is unavailable"
    fi
  elif grep -qx "$symbol=y" "$config_file"; then
    pass "$symbol=y"
  else
    fail "$symbol is not enabled"
  fi
}

expect_disabled() {
  symbol=$1
  if [ -z "$config_file" ]; then
    if [ "$strict" -eq 1 ]; then
      fail "cannot inspect $symbol: running kernel config is unavailable"
    else
      warn "cannot inspect $symbol: running kernel config is unavailable"
    fi
  elif grep -Eq "^# $symbol is not set$|^$symbol=n$" "$config_file"; then
    pass "$symbol is disabled"
  else
    fail "$symbol is enabled or unresolved"
  fi
}

expect_enabled CONFIG_PREEMPT_RT
expect_enabled CONFIG_HIGH_RES_TIMERS
expect_enabled CONFIG_HZ_PERIODIC
expect_enabled CONFIG_HZ_1000
expect_enabled CONFIG_CPUSETS
expect_enabled CONFIG_CPU_ISOLATION
expect_disabled CONFIG_RT_GROUP_SCHED

if [ -r /sys/kernel/realtime ]; then
  if [ "$(cat /sys/kernel/realtime)" = "1" ]; then
    pass "/sys/kernel/realtime=1"
  else
    fail "/sys/kernel/realtime is not 1"
  fi
else
  if [ "$strict" -eq 1 ]; then
    fail "/sys/kernel/realtime is unavailable"
  else
    warn "/sys/kernel/realtime is unavailable"
  fi
fi

if [ -r /proc/cmdline ]; then
  printf 'cmdline=%s\n' "$(cat /proc/cmdline)"
fi
for sysctl in /proc/sys/kernel/sched_rt_period_us /proc/sys/kernel/sched_rt_runtime_us; do
  if [ -r "$sysctl" ]; then
    printf '%s=%s\n' "$sysctl" "$(cat "$sysctl")"
  fi
done

if [ -r /proc/self/limits ]; then
  awk '/Max realtime priority/ {print "limit_rtprio_soft=" $4 " limit_rtprio_hard=" $5}
       /Max locked memory/ {print "limit_memlock_soft=" $4 " limit_memlock_hard=" $5 " unit=" $6}' \
    /proc/self/limits
fi
if [ -r /sys/devices/system/clocksource/clocksource0/current_clocksource ]; then
  printf 'clocksource=%s\n' "$(cat /sys/devices/system/clocksource/clocksource0/current_clocksource)"
fi

if [ "$failures" -ne 0 ]; then
  warn "$failures production requirement(s) are not satisfied"
  if [ "$strict" -eq 1 ]; then
    exit 1
  fi
fi
exit 0
