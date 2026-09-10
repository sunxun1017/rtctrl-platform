#!/usr/bin/env python3
"""Enforce module-owned contracts and adapter isolation, including local headers."""
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[1]
include_pattern = re.compile(r'^\s*#\s*include\s*[<"]([^">]+)[">]', re.MULTILINE)
errors = []
headers = {}
for base in (root / 'modules').rglob('include'):
    for path in base.rglob('*'):
        if path.suffix not in ('.h', '.hpp'):
            continue
        name = path.relative_to(base).as_posix()
        if name in headers:
            errors.append(f'Duplicate public header: {name}')
        headers[name] = path
native = re.compile(r'^(linux/|sys/|pthread\.h$|unistd\.h$|poll\.h$|fcntl\.h$|ecrt\.h$|rk_aiq|rknn)')
visited = set()

def visit(path):
    if path in visited:
        return
    visited.add(path)
    for name in include_pattern.findall(path.read_text()):
        if native.match(name):
            errors.append(f'{path.relative_to(root)}: native dependency {name}')
        if name.startswith('rtctrl/'):
            if name not in headers:
                errors.append(f'{path.relative_to(root)}: non-module dependency {name}')
            else:
                visit(headers[name])
        elif (path.parent / name).is_file():
            visit((path.parent / name).resolve())

for module in (root / 'modules').iterdir():
    if not module.is_dir():
        continue
    for path in module.rglob('*'):
        if 'tests' not in path.relative_to(module).parts and path.suffix in ('.c', '.cpp', '.h', '.hpp'):
            visit(path.resolve())
visit(root / 'apps/camera_capture/capture_cli.c')
# Public APIs must not silently return to the former globally visible header tree.
if list((root / 'include/rtctrl').rglob('*.h')) or list((root / 'include/rtctrl').rglob('*.hpp')):
    errors.append('Public headers must belong to modules or adapters, not include/rtctrl')
if errors:
    print('\n'.join(errors), file=sys.stderr)
    sys.exit(1)
print(f'Architecture boundaries passed: {len(headers)} module headers, {len(visited)} source/header files')
