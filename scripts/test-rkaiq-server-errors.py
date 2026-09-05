#!/usr/bin/env python3
"""Patch an isolated server source copy and regression-test its actual functions."""
import argparse,subprocess,shutil,tempfile
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--sdk-root',type=Path,required=True);a=p.parse_args()
r=Path(__file__).resolve().parents[1];sdk=a.sdk_root.resolve();(r/'work').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='rkaiq-error-test-',dir=r/'work') as td:
 t=Path(td);d=t/'rkaiq_3A_server';d.mkdir();src=d/'rkaiq_3A_server.cpp'
 shutil.copyfile(sdk/'external/camera_engine_rkaiq/rkaiq_3A_server/rkaiq_3A_server.cpp',src)
 for n in ['0001-3a-server-check-init-context.patch','0002-3a-server-check-start-result.patch']:
  subprocess.run(['patch','-p1','--batch','--directory',str(t),'-i',str(r/'patches/rkaiq'/n)],check=True)
 inc=sdk/'external/camera_engine_rkaiq/rkaiq/include'
 args=['g++','-std=c++11','-ffunction-sections','-fdata-sections','-Wl,--gc-sections','-DUSE_NEWSTRUCT=1','-DISP_HW_V35','-DSERVER_SOURCE="'+str(src)+'"']
 for sub in ['', 'common','xcore','algos','iq_parser_v2','isp']:args+=['-I'+str(inc/sub)]
 subprocess.run(args+[str(r/'scripts/test-rkaiq-server-errors.cpp'),'-o',str(t/'regression')],check=True)
 subprocess.run([str(t/'regression')],check=True,timeout=10)
