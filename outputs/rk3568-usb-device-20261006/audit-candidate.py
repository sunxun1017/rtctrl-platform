#!/usr/bin/env python3
"""Independently audit existing candidate and real-libfdt binary mutations."""
import argparse
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',required=True)
    parser.add_argument('--name',default='audit-binary-v1')
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('usb_candidate_builder',HERE/'build-candidate.py')
    build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)
    C=build.C
    C.require(build.os.name=='posix','Real libfdt negative generation requires Linux')
    C.require(build.re.fullmatch('[a-z0-9-]+',args.name),'Fresh own basename required')
    out=HERE/'build'/args.name
    out.mkdir(parents=True,exist_ok=False)
    path=Path(args.candidate)
    blob=path.read_bytes()
    audit=C.audit(blob)
    real=C.module('usb_audit_locked_fdt',C.INPUTS/'libfdt-v2.py').RealLibFdt()
    negatives=build.negatives(real,blob,out/'rejected-dtbs')
    report={'baseline_sha256':C.BASE_SHA,'candidate_sha256':C.sha(blob),'candidate_bytes':len(blob),
        'full_tree_and_graph':audit,'negative_binary_fixtures':negatives,
        'all_negative_fixtures_rejected':True,'diagnostics_gate_evaluated_here':False,
        'board_tested':False,'usb_recovery_verified':False,'physical_no_vbus_verified':False}
    build.write_json(out/'result.json',report)
    print(json.dumps({'candidate_sha256':C.sha(blob),'binary_negatives_rejected':len(negatives),'diagnostics_gate_evaluated_here':False}))

if __name__=='__main__':
    main()
