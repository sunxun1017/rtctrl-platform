#!/usr/bin/env python3
"""Reject duplicate or embedded requests while accepting the recorded prompt."""
import importlib.util
from pathlib import Path

here = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('auditor', here / 'audit-default-address.py')
auditor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auditor)
cases = {
    'actual_uart': (auditor.raw('default-address-boot-v1.raw.txt'), 1),
    'bare_command': ('bootm 20000000\n', 1),
    'duplicate_requests': ('=> bootm 20000000\nbootm 20000000\n', 2),
    'embedded_diagnostic': ('diagnostic mentions bootm 20000000\n', 0),
    'other_address': ('=> bootm 21000000\n', 0),
}
for label, (console, expected) in cases.items():
    actual = auditor.bootm_requests(console)
    assert actual == expected, (label, actual, expected)
print('default-address command audit: 5/5 passed')
