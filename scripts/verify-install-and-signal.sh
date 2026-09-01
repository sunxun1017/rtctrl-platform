#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
install_dir="$(mktemp -d)"
signal_log="$(mktemp)"

cleanup() {
  rm -rf -- "${install_dir}"
  rm -f -- "${signal_log}"
}
trap cleanup EXIT HUP INT TERM

cd "${project_dir}"
cmake --install build/release --prefix "${install_dir}"
test -f "${install_dir}/lib/cmake/rtctrl/rtctrlTargets.cmake"

./build/release/rtctrl_demo --duration 10 --arm --no-mlock >"${signal_log}" &
demo_pid=$!
sleep 1
kill -TERM "${demo_pid}"
wait "${demo_pid}"
grep -q "fault_latched=false" "${signal_log}"

printf 'install export and SIGTERM safety path passed\n'
