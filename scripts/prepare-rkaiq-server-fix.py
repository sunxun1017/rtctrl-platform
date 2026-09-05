#!/usr/bin/env python3
"""Apply RKAIQ maintenance patches to a fresh server copy, without SDK writes."""
import argparse,subprocess,shutil
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--sdk-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();sdk=a.sdk_root.resolve();out=a.output.resolve();repo=Path(__file__).resolve().parents[1]
if out==sdk or sdk in out.parents: p.error('output must be outside SDK')
if out.exists(): p.error('output must not exist')
shutil.copytree(sdk/'external/camera_engine_rkaiq/rkaiq_3A_server',out/'rkaiq_3A_server')
for patch in sorted((repo/'patches/rkaiq').glob('*.patch')):
 subprocess.run(['patch','--batch','-p1','--directory',str(out),'-i',str(patch)],check=True)
print(out/'rkaiq_3A_server/rkaiq_3A_server.cpp')
