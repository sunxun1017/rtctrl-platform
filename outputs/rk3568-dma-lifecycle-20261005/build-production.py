#!/usr/bin/env python3
"""Offline full-series replay and real arm64 Kbuild object ABI verification."""
import argparse, hashlib, importlib.util, json, os, re, subprocess, tarfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
KERNEL=ROOT/'third_party/linux-rk3588'
COMMIT='9f9e9d18574d0914c0d192a90c3babfe1fd63c95'
def sha(data):return hashlib.sha256(data).hexdigest()
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module
def clean():
    for args,wanted in [(['rev-parse','HEAD'],COMMIT),(['status','--porcelain'],'')]:
        if subprocess.check_output(['git','-C',str(KERNEL),*args],text=True).strip()!=wanted:
            raise ValueError('locked original source rejected')
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-dir',type=Path,required=True)
    p.add_argument('--revision',required=True)
    p.add_argument('--cpu-dir',type=Path)
    a=p.parse_args()
    if not re.fullmatch('v[1-9][0-9]*',a.revision):p.error('fresh vN required')
    out=HERE/('production-'+a.revision);out.mkdir(exist_ok=False)
    candidate=a.source_dir.resolve();manifest=json.loads((candidate/'manifest.json').read_text())
    for path,digest in manifest['source_sha256'].items():
        if sha((candidate/path).read_bytes())!=digest:raise ValueError('candidate drift: '+path)
    patch=candidate/'C3-lifecycle-review.patch'
    if sha(patch.read_bytes())!=manifest['patch_sha256']:raise ValueError('patch drift')
    clean()
    b=load('b_replay',ROOT/'outputs/rk3568-asoc-errors-20261005/driver-prepare.py')
    patch_dir=ROOT/'platforms/rk3568/boards/aiot-3568pq/patches'
    patches={name:(patch_dir/name).read_bytes() for name in b.DEPENDENCIES}
    patches[b.PATCH_NAME]=(patch_dir/b.PATCH_NAME).read_bytes()
    expected={**b.DEPENDENCIES,b.PATCH_NAME:'c3bd1bd7e8fd581e21a962993519f934ceb78a7efe61d77da846972e93b73f2b'}
    for name,data in patches.items():
        if sha(data)!=expected[name]:raise ValueError('published dependency drift: '+name)
    patches['0011-pl330-pcm-lifecycle.patch']=patch.read_bytes()
    cpu=None
    if a.cpu_dir:
        directory=a.cpu_dir.resolve();cpu_path='sound/soc/rockchip/rockchip_i2s_tdm.c'
        data=(directory/cpu_path).read_bytes();cpu_patch=(directory/'i2s-lifecycle-pm.patch').read_bytes()
        if sha(data)!='cbd19c1a8b128d442f6321ebb9ce1d51524633536282862b6c06fa76b4f77b59' or sha(cpu_patch)!='ec857605a70abccce88ac71c1e5070b866fb245717ad90ae0db2af26fc9aa495':raise ValueError('accepted CPU v10 drift')
        patches['0012-i2s-lifecycle.patch']=cpu_patch;cpu={'path':cpu_path,'source_sha256':sha(data),'patch_sha256':sha(cpu_patch),'manifest_sha256':sha((directory/'manifest.json').read_bytes())}
    replay,records=b.replay(out,patches)
    for path,digest in manifest['source_sha256'].items():
        if sha((replay/path).read_bytes())!=digest:raise ValueError('full series replay differs: '+path)
    if cpu and sha((replay/cpu['path']).read_bytes())!=cpu['source_sha256']:raise ValueError('CPU full replay differs')
    # Source-only Git archive reads the locked commit; no checkout/Git metadata writes.
    source=out/'source';source.mkdir()
    with (out/'archive.stderr').open('wb') as errors:
        process=subprocess.Popen(['git','-C',str(KERNEL),'archive','--format=tar',COMMIT],stdout=subprocess.PIPE,stderr=errors)
        with tarfile.open(fileobj=process.stdout,mode='r|') as archive:
            for entry in archive:
                dest=(source/entry.name).resolve()
                if source.resolve() not in dest.parents:raise ValueError('unsafe archive path')
                archive.extract(entry,source)
        process.stdout.close()
        if process.wait():raise ValueError('archive failed')
    for path in replay.rglob('*'):
        if path.is_file():(source/path.relative_to(replay)).write_bytes(path.read_bytes())
    clean()
    config_tool=load('config_tool',ROOT/'scripts/prepare-linux-config.py')
    candidate_config=ROOT/'platforms/rk3568/boards/aiot-3568pq/firstboot-candidate.json'
    profile=config_tool.load_candidate(candidate_config)
    fragments=[ROOT/path for path in profile['fragments']]
    build=out/'build';build.mkdir();env=config_tool.build_environment(build)
    compiler=subprocess.check_output([profile['cross_compile']+'gcc','--version'],env=env,text=True).splitlines()[0]
    make=['make','-C',str(source),'O='+str(build),'ARCH=arm64','CROSS_COMPILE='+profile['cross_compile']]
    commands=[]
    def run(argv,stem):
        with (out/(stem+'.stdout')).open('wb') as stdout,(out/(stem+'.stderr')).open('wb') as stderr:
            completed=subprocess.run(argv,env=env,stdout=stdout,stderr=stderr)
        rec={'argv':argv,'returncode':completed.returncode,'stdout_sha256':sha((out/(stem+'.stdout')).read_bytes()),'stderr_sha256':sha((out/(stem+'.stderr')).read_bytes())}
        commands.append(rec)
        (out/'progress.json').write_text(json.dumps(commands,indent=2)+'\n')
        return completed.returncode
    for argv,stem in [(make+[profile['defconfig']],'defconfig'),(['bash',str(source/'scripts/kconfig/merge_config.sh'),'-m','-O',str(build),str(build/'.config'),*[str(f) for f in fragments]],'merge'),(make+['olddefconfig'],'olddefconfig')]:
        if run(argv,stem):raise ValueError('config stage failed: '+stem)
    failures=config_tool.audit_settings(config_tool.requested_settings(fragments),(build/'.config').read_text())
    if failures:raise ValueError('config mismatch: '+str(failures))
    objects=['drivers/dma/pl330.o','drivers/dma/dmaengine.o','sound/core/pcm.o','sound/core/pcm_memory.o','sound/core/pcm_dmaengine.o','sound/core/pcm_native.o','sound/soc/soc-pcm.o','sound/soc/soc-component.o','sound/soc/soc-dai.o','sound/soc/soc-generic-dmaengine-pcm.o']
    if cpu:objects+=['sound/core/memalloc.o','sound/soc/rockchip/rockchip_i2s_tdm.o']
    rc=run(make+['-j4',*objects],'objects')
    clean()
    result={'kernel_commit':COMMIT,'original_tree_clean':True,'published':False,'deployable':False,'board_tested':False,'image_built':False,'objects_build_passed':rc==0,'candidate_manifest_sha256':sha((candidate/'manifest.json').read_bytes()),'source_sha256':manifest['source_sha256'],'patch_series':records,'replay_files_sha256':{str(f.relative_to(replay)):sha(f.read_bytes()) for f in replay.rglob('*') if f.is_file()},'compiler':compiler,'config_sha256':sha((build/'.config').read_bytes()),'fragments_sha256':{str(f.relative_to(ROOT)):sha(f.read_bytes()) for f in fragments},'commands':commands,'objects_sha256':{path:sha((build/path).read_bytes()) for path in objects if (build/path).exists()},'generator_sha256':sha(Path(__file__).read_bytes())}
    result['cpu']=cpu
    result['kbuild_commands_sha256']={str((Path(path).parent/('.'+Path(path).name+'.cmd'))):sha((build/Path(path).parent/('.'+Path(path).name+'.cmd')).read_bytes()) for path in objects if (build/Path(path).parent/('.'+Path(path).name+'.cmd')).exists()}
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'result':str(out/'result.json'),'passed':rc==0,'compiled':len(result['objects_sha256'])}),flush=True)
    return int(rc!=0)
if __name__=='__main__':raise SystemExit(main())
