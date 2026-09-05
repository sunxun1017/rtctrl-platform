from pathlib import Path
import subprocess,shutil,os
import argparse
ap=argparse.ArgumentParser(description='Build isolated SDK RKAIQ, never replace the system library')
ap.add_argument('--sdk-root',required=True,type=Path)
a=ap.parse_args()
repo=Path(__file__).resolve().parent.parent; sdk=a.sdk_root.resolve()
src=repo/'work/rkaiq-debug-src'; out=repo/'work/rkaiq-debug-build'
if not src.exists(): shutil.copytree(sdk/'external/camera_engine_rkaiq',src,symlinks=True)
host=sdk/'prebuilts/gcc/linux-x86/aarch64/gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu'
env=os.environ.copy(); env.update(AIQ_BUILD_HOST_DIR=str(host),AIQ_BUILD_TOOLCHAIN_TRIPLE='aarch64-none-linux-gnu',AIQ_BUILD_SYSROOT='libc',AIQ_BUILD_ARCH='aarch64')
env['PATH']=str(repo/'work/host-tools/usr/bin')+os.pathsep+env['PATH']
if not shutil.which('m4',path=env['PATH']): raise SystemExit('Install m4 or extract its package under work/host-tools')
args=['cmake','-G','Ninja','-S',str(src/'rkaiq'),'-B',str(out),'-DCMAKE_INSTALL_PREFIX='+str(repo/'work/rkaiq-debug-install'),'-DCMAKE_BUILD_TYPE=RelWithDebInfo','-DRKAIQ_TARGET_SOC=rv1126b','-DARCH=aarch64','-DCMAKE_TOOLCHAIN_FILE='+str(src/'rkaiq/cmake/toolchains/gcc.cmake'),'-DRKAIQ_BUILD_BINARY_IQ=ON','-DCMAKE_EXPORT_COMPILE_COMMANDS=YES','-DISP_HW_VERSION=-DISP_HW_V35','-DRKAIQ_USE_RAWSTREAM_LIB=OFF','-DRKAIQ_HAVE_FAKECAM=ON','-DRKAIQ_ENABLE_AF=ON','-DCMAKE_C_FLAGS_RELWITHDEBINFO=-O1 -g -fno-omit-frame-pointer','-DCMAKE_CXX_FLAGS_RELWITHDEBINFO=-O1 -g -fno-omit-frame-pointer']
with (repo/'work/rkaiq-configure.log').open('w') as f:p=subprocess.run(args,env=env,stdout=f,stderr=subprocess.STDOUT)
print('configure rc',p.returncode)
print((repo/'work/rkaiq-configure.log').read_text()[-6500:])

if p.returncode: raise SystemExit(p.returncode)
subprocess.run(['cmake','--build',str(out),'--target','rkaiq','-j','6'],env=env,check=True)

import hashlib,json
lib=out/'all_lib/RelWithDebInfo/librkaiq.so'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
manifest={'sdk_root':str(sdk),'source_commit':subprocess.check_output(['git','-C',str(sdk/'external/camera_engine_rkaiq'),'rev-parse','HEAD'],text=True).strip(),'sdk_source_status':subprocess.check_output(['git','-C',str(sdk/'external/camera_engine_rkaiq'),'status','--short'],text=True),'configure_args':args,'compiler':str(host/'bin/aarch64-none-linux-gnu-gcc'),'output_sha256':sha(lib),'cmake_cache_sha256':sha(out/'CMakeCache.txt'),'limitations':['includes SDK precompiled closed algorithms','temporary LD_LIBRARY_PATH deployment; no system library replacement']}
(repo/'work/rkaiq-debug-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
