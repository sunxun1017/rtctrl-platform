#!/usr/bin/env python3
"""Compile actual battery object in a private source/config/output only."""
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
COMMIT='9f9e9d18574d0914c0d192a90c3babfe1fd63c95'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    output=HERE/'build/kbuild-v5'
    output.mkdir(parents=True,exist_ok=False)
    original=ROOT/'third_party/linux-rk3588'
    head=subprocess.check_output(['git','-C',str(original),'rev-parse','HEAD'],text=True).strip()
    status=subprocess.check_output(['git','-C',str(original),'status','--porcelain'],text=True)
    if head!=COMMIT or status:
        raise ValueError('Original kernel must be unchanged')
    source=output/'kernel-source'
    build=output/'kernel-build'
    env=dict(os.environ)
    env['PATH']=str(ROOT/'.deps/host-tools/bin')+':'+env['PATH']
    steps=[]
    def run(label,argv):
        with (output/(label+'.txt')).open('w') as stream:
            result=subprocess.run(argv,stdout=stream,stderr=subprocess.STDOUT,env=env)
        steps.append({'label':label,'argv':argv,'returncode':result.returncode})
        (output/'steps.json').write_text(json.dumps(steps,indent=2)+'\n')
        result.check_returncode()
    run('clone',['git','clone','--shared','--no-checkout',str(original),str(source)])
    run('checkout',['git','-C',str(source),'checkout','--detach',COMMIT])
    # The baseline audio config needs its already-reviewed arm64 include fix.
    # All twelve public patches match the current dedicated audio kernel.
    public=ROOT/'platforms/rk3568/boards/aiot-3568pq/patches'
    applied={}
    for number in range(1,13):
        matches=list(public.glob(f'{number:04d}-*.patch'))
        if len(matches)!=1:
            raise ValueError('Unique baseline public patch required')
        patch=matches[0]
        applied[patch.relative_to(ROOT).as_posix()]=sha(patch)
        run(f'baseline-{number:02d}-check',['git','-C',str(source),'apply','--check',str(patch)])
        run(f'baseline-{number:02d}-apply',['git','-C',str(source),'apply',str(patch)])
    old=HERE/'original-v1/drivers/power/supply/rk817_battery.c'
    candidate=HERE/'candidate-v4/drivers/power/supply/rk817_battery.c'
    if sha(source/'drivers/power/supply/rk817_battery.c')!=sha(old):
        raise ValueError('Private source battery differs from locked original')
    patch=''.join(difflib.unified_diff(old.read_text().splitlines(True),candidate.read_text().splitlines(True),
        fromfile='a/drivers/power/supply/rk817_battery.c',tofile='b/drivers/power/supply/rk817_battery.c'))
    patch_path=HERE/'candidate-v4/rk817-lifecycle-review.patch'
    patch_path.write_text(patch)
    run('patch-check',['git','-C',str(source),'apply','--check',str(patch_path)])
    run('patch-apply',['git','-C',str(source),'apply',str(patch_path)])
    if sha(source/'drivers/power/supply/rk817_battery.c')!=sha(candidate):
        raise ValueError('Applied source identity differs')
    build.mkdir()
    baseline=HERE/'original-v1/audio.config'
    config=baseline.read_text().replace('# CONFIG_BATTERY_RK817 is not set','CONFIG_BATTERY_RK817=y')
    config=config.replace('CONFIG_CHARGER_BQ24735=y','# CONFIG_CHARGER_BQ24735 is not set')
    (build/'.config').write_text(config)
    common=['make','-C',str(source),'O='+str(build),'ARCH=arm64','CROSS_COMPILE=aarch64-linux-gnu-']
    run('olddefconfig',common+['olddefconfig'])
    if (build/'.config').read_text()!=config:
        raise ValueError('Unexpected Kconfig change')
    for symbol in ['CHARGER_RK817','CHARGER_BQ24735','CHARGER_BQ25700','CHARGER_BQ25713']:
        if '# CONFIG_'+symbol+' is not set' not in config:
            raise ValueError('External/internal charger must remain disabled')
    run('object',common+['V=1','-j4','drivers/power/supply/rk817_battery.o'])
    obj=build/'drivers/power/supply/rk817_battery.o'
    run('symbols',['aarch64-linux-gnu-nm','-a',str(obj)])
    run('elf',['aarch64-linux-gnu-readelf','-h',str(obj)])
    for required in ['rk817_battery_probe','rk817_battery_remove','rk817_battery_shutdown','rk817_bat_stop','rk817_bat_pm_suspend','rk817_bat_pm_resume','synchronize_irq','rk809_bat_refresh_plug_state']:
        if required not in (output/'symbols.txt').read_text():
            raise ValueError('Missing actual object symbol '+required)
    if subprocess.check_output(['git','-C',str(original),'status','--porcelain'],text=True):
        raise ValueError('Original source changed during build')
    for name,path in [('battery.o',obj),('battery.config',build/'.config'),('battery.o.cmd',build/'drivers/power/supply/.rk817_battery.o.cmd')]:
        shutil.copyfile(path,output/name)
    manifest={'kernel_commit':COMMIT,'source_sha256':sha(candidate),'patch_sha256':sha(patch_path),
        'config_sha256':sha(output/'battery.config'),'object_sha256':sha(output/'battery.o'),
        'compiler':subprocess.check_output(['aarch64-linux-gnu-gcc','--version'],text=True).splitlines()[0],
        'config_delta':['CONFIG_BATTERY_RK817=n -> y','CONFIG_CHARGER_BQ24735=y -> n'],'baseline_patches_sha256':applied,'steps':steps,'board_tested':False,
        'image_built':False,'external_chargers_enabled':False,'original_kernel_unchanged':True}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest),flush=True)

if __name__=='__main__':
    main()
