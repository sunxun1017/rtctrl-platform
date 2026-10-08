#!/usr/bin/env python3
"""Exercise extracted production callbacks with joining asynchronous threads."""
import hashlib
import argparse
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='build/threaded-v3')
    parser.add_argument('--wrapper',default='build/green-final-v2/wrapper.c')
    parser.add_argument('--source',default='candidate-v2/drivers/power/supply/rk817_battery.c')
    args=parser.parse_args()
    output=HERE/args.output
    output.mkdir(parents=True,exist_ok=False)
    frozen=HERE/args.wrapper
    text='#define THREADED 1\n'+frozen.read_text().replace('#include "model-tests.h"','#include "model-threaded-tests.h"')
    wrapper=output/'wrapper.c'
    wrapper.write_text(text)
    results=[]
    for name,compiler,flags,runner in [
        ('host','gcc',['-O2'],[]),
        ('sanitizers','gcc',['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie'],[]),
        ('aarch64','aarch64-linux-gnu-gcc',['-O2','-static'],[str(HERE.parents[1]/'.deps/qemu-user/root/usr/bin/qemu-aarch64-static')]),
    ]:
        binary=output/name
        argv=[compiler,'-std=gnu11','-pthread','-Wall','-Wno-unused-function','-Wno-unused-variable','-Wno-unused-parameter','-I',str(HERE),*flags,str(wrapper),'-o',str(binary)]
        result=subprocess.run(argv,capture_output=True,text=True)
        (output/(name+'-compile.txt')).write_text(result.stdout+result.stderr)
        result.check_returncode()
        run_argv=runner+[str(binary)]
        result=subprocess.run(run_argv,capture_output=True,text=True,timeout=30)
        (output/(name+'-stdout.txt')).write_text(result.stdout)
        (output/(name+'-stderr.txt')).write_text(result.stderr)
        results.append({'environment':name,'compile_argv':argv,'run_argv':run_argv,'returncode':result.returncode,
            'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'passed':result.stdout.count('PASS '),'failed':result.stdout.count('FAIL ')})
    (output/'result.json').write_text(json.dumps({'results':results,'wrapper_sha256':hashlib.sha256(wrapper.read_bytes()).hexdigest(),
        'production_source_sha256':hashlib.sha256((HERE/args.source).read_bytes()).hexdigest(),
        'scope':'pthread dependency wrappers, not a kernel scheduler or IRQ hardware test','board_tested':False},indent=2)+'\n')
    print(json.dumps(results))

if __name__=='__main__':
    main()
