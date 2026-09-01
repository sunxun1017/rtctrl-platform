#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${project_dir}"

cmake --preset release
cmake --build --preset release -j "${RTCTRL_BUILD_JOBS:-8}"
ctest --preset release
./build/release/rtctrl_frame_demo
./build/release/rtctrl_demo --duration "${RTCTRL_DEMO_SECONDS:-3}" --arm --no-mlock
./build/release/rtctrl_bench "${RTCTRL_BENCH_SECONDS:-3}" 1000
