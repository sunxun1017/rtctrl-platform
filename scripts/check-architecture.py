#!/usr/bin/env python3
"""Check transitive includes at realtime, capture-core and frame-consumer boundaries."""
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[1]
include_pattern = re.compile(r'^\s*#\s*include\s*[<"]([^">]+)[">]', re.MULTILINE)
forbidden_native = r"^(linux/|sys/|ecrt\.h$|rk_aiq|rknn|ros/|rclcpp/)"
errors = []


def scan(label, starts, allowed_headers, allowed_prefixes=(), forbidden=forbidden_native):
    visited = set()

    def visit(path):
        if path in visited:
            return
        visited.add(path)
        for include in include_pattern.findall(path.read_text()):
            if re.match(forbidden, include):
                errors.append(f"{label}: {path.relative_to(root)} includes native header {include}")
            if include.startswith("rtctrl/"):
                if include not in allowed_headers and not include.startswith(allowed_prefixes):
                    errors.append(f"{label}: {path.relative_to(root)} reaches forbidden header {include}")
                else:
                    visit(root / "include" / include)
            elif (path.parent / include).is_file():
                visit(path.parent / include)

    for start in starts:
        visit(start)
    print(f"{label}: checked {len(visited)} files")


starts = []
for directory in ("src/runtime", "src/control", "src/safety", "include/rtctrl/runtime",
                  "include/rtctrl/control", "include/rtctrl/safety"):
    starts.extend(p for p in (root / directory).rglob("*") if p.suffix in (".cpp", ".hpp"))
scan("Realtime core", starts,
     {"rtctrl/hal/actuator_hal.hpp", "rtctrl/platform/realtime_platform.hpp",
      "rtctrl/ipc/spsc_ring.hpp", "rtctrl/bridge/runtime_ports.hpp"},
     ("rtctrl/model/", "rtctrl/control/", "rtctrl/safety/", "rtctrl/runtime/"))
scan("Composed actuator HAL", [root / "src/hal/protocol_actuator_hal.cpp"],
     {"rtctrl/hal/protocol_actuator_hal.hpp", "rtctrl/hal/actuator_hal.hpp",
      "rtctrl/hal/actuator_link.hpp", "rtctrl/hal/actuator_protocol.hpp"}, ("rtctrl/model/",))
capture_headers = {"rtctrl/vision/capture.h", "rtctrl/vision/capture_backend.h",
                   "rtctrl/vision/image_format.h"}
forbidden_capture = r"^(linux/|sys/|pthread\.h$|unistd\.h$|poll\.h$|fcntl\.h$|rk_aiq|rknn)"
scan("Capture core/consumer", [root / p for p in (
    "src/vision/capture.c", "apps/camera_capture/capture_cli.c")],
    capture_headers, forbidden=forbidden_capture)
scan("Synthetic adapter", [root / "src/vision/synthetic_capture.c"],
     capture_headers | {"rtctrl/vision/synthetic_capture.h"}, forbidden=forbidden_capture)
if errors:
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)
print("Architecture include boundaries passed")
