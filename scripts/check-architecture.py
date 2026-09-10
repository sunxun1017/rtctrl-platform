#!/usr/bin/env python3
"""Reject adapter headers reachable from the realtime core, including transitive includes."""
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[1]
allowed_prefixes = ("rtctrl/model/", "rtctrl/control/", "rtctrl/safety/", "rtctrl/runtime/")
allowed_headers = {"rtctrl/hal/actuator_hal.hpp", "rtctrl/platform/realtime_platform.hpp",
                   "rtctrl/ipc/spsc_ring.hpp", "rtctrl/bridge/runtime_ports.hpp"}
include_pattern = re.compile(r'^\s*#\s*include\s*[<"]([^">]+)[">]', re.MULTILINE)
forbidden_system = re.compile(r"^(linux/|sys/|ecrt\.h$|rk_aiq|rknn|ros/|rclcpp/)")
visited = set()
errors = []


def visit(path):
    if path in visited:
        return
    visited.add(path)
    for include in include_pattern.findall(path.read_text()):
        if forbidden_system.match(include):
            errors.append(f"{path.relative_to(root)} includes platform/vendor header {include}")
        if not include.startswith("rtctrl/"):
            continue
        if not include.startswith(allowed_prefixes) and include not in allowed_headers:
            errors.append(f"{path.relative_to(root)} reaches adapter/application header {include}")
        else:
            visit(root / "include" / include)


for directory in ("src/runtime", "src/control", "src/safety", "include/rtctrl/runtime",
                  "include/rtctrl/control", "include/rtctrl/safety"):
    for source in (root / directory).rglob("*"):
        if source.suffix in (".cpp", ".hpp"):
            visit(source)
if errors:
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)
print(f"Realtime include boundaries passed ({len(visited)} files)")
