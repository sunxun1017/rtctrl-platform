#!/usr/bin/env python3
"""Use the reviewed transfer checks with a smaller, explicit UART burst."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'live-fdt-transfer.py'
SOURCE_SHA = 'b3d66dd29df18072eba7a059361d6b4362abe68ea990d1a4c70b5799e32280d0'
if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA:
    raise ValueError('Reviewed transfer implementation changed')
spec = importlib.util.spec_from_file_location('transfer', SOURCE)
transfer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transfer)
transfer.CHUNK = 256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    read = sub.add_parser('plan-read')
    read.add_argument('metadata_raw', type=Path)
    read.add_argument('destination', type=Path)
    audit = sub.add_parser('audit')
    audit.add_argument('metadata_raw', type=Path)
    audit.add_argument('read_raw', type=Path)
    audit.add_argument('output', type=Path)
    audit.add_argument('receipt', type=Path)
    args = parser.parse_args()
    if args.operation == 'plan-read':
        print(json.dumps(transfer.plan_read(args.metadata_raw, args.destination)))
    else:
        print(json.dumps(transfer.audit(args.metadata_raw, args.read_raw, args.output, args.receipt)))


if __name__ == '__main__':
    main()
