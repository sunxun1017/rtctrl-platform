#!/usr/bin/env python3
"""Create narrow v2 copies of existing tools and SHA-bound version inputs."""
import hashlib
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
BASE_REL='outputs/rk3568-audio-runtime-20261005/build/audio-ram-shim-v1/applied-audit-only.dtb'
BASE_SHA='4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    old=HERE/'sealed-v1'
    manifest=json.loads((old/'manifest.json').read_text())
    own_prefix=HERE.relative_to(ROOT).as_posix()+'/'
    for rel,expected in manifest['files_sha256'].items():
        assert rel.startswith(own_prefix)
        assert sha(old/'snapshot'/rel[len(own_prefix):])==expected,rel
    inputs=HERE/'inputs-v2';inputs.mkdir(exist_ok=False)
    records={}
    def copy(path,rel,expected=None):
        digest=sha(path)
        if expected:
            assert digest==expected,str(path)
        dest=inputs/rel
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,dest)
        assert sha(dest)==digest
        records[Path(rel).as_posix()]={'source':path.relative_to(ROOT).as_posix(),'sha256':digest}
    copy(ROOT/BASE_REL,'audio-linux-tested.dtb',BASE_SHA)
    assert (ROOT/BASE_REL).stat().st_size==163285
    copy(old/'manifest.json','sealed-v1-manifest.json')
    for name in ('README.md','PLAN.md','build-emmc-bridge.py','test-emmc-bridge.py','check-linux-match.py','verify-dtc-warnings.py'):
        copy(HERE/name,'old/'+name,manifest['files_sha256'][own_prefix+name])
    for rel in ('outputs/rk3568-boot-package-20261005/dt-semantics-v2.py','outputs/rk3568-boot-package-20261005/libfdt-v2.py',
                'outputs/rk3568-boot-package-20261005/build/libfdt-v2/libfdt-locked.so',
                'outputs/rk3568-boot-package-20261005/build/roundtrip-v1/rsce/arch/arm64/boot/dts/rockchip/rk3568_smdt_3568a_v20.dtb',
                'outputs/rk3568-boot-package-20261005/FORMAL-EARLY-REVIEW.md',
                '.deps/kernel/aiot-3568pq-rcu-reset/scripts/dtc/dtc',
                'third_party/linux-rk3588/drivers/of/base.c','third_party/linux-rk3588/drivers/of/property.c',
                'third_party/linux-rk3588/include/linux/of.h','third_party/linux-rk3588/drivers/mmc/host/sdhci-of-dwcmshc.c',
                '.deps/kernel/aiot-3568pq-audio-v1/.config'):
        copy(ROOT/rel,'external/'+rel,manifest['inputs_sha256'][rel])
    old_base="ROOT / 'outputs/rk3568-audio-20261005/build/dtb-v3/audio.dtb'"
    new_base="ROOT / '"+BASE_REL+"'"
    generated={}
    for name in ('build-emmc-bridge.py','test-emmc-bridge.py','check-linux-match.py','verify-dtc-warnings.py'):
        text=(HERE/name).read_text()
        if name in ('build-emmc-bridge.py','test-emmc-bridge.py'):
            assert text.count(old_base)==1
            text=text.replace(old_base,new_base,1)
            text=text.replace('9cf8cc0189239dab2fda0dae0ac3519c20d5b5802900111587695458dc3ab478',BASE_SHA)
            if name=='test-emmc-bridge.py':
                assert text.count('len(baseline) == 163161')==1
                text=text.replace('len(baseline) == 163161','len(baseline) == 163285',1)
        if name=='check-linux-match.py':
            before="    vectors = [\n"
            after=("    baseline_path = "+new_base+"\n"
                   "    baseline = baseline_path.read_bytes()\n"
                   "    if sha(baseline) != '"+BASE_SHA+"' or len(baseline) != 163285:\n"
                   "        raise ValueError('Exact actual Linux baseline required')\n"
                   "    baseline_compatible = bytes.fromhex(semantic.parse(baseline)['properties']['/sdhci@fe310000:compatible'])\n"
                   "    vectors = [\n")
            assert text.count(before)==1
            text=text.replace(before,after,1)
            original="('tested_baseline', b'rockchip,rk3568-dwcmshc\\0rockchip,dwcmshc-sdhci\\0', 'rk3568_drvdata')"
            assert text.count(original)==1
            text=text.replace(original,"('tested_baseline', baseline_compatible, 'rk3568_drvdata')",1)
            text=text.replace("'candidate_sha256': sha(candidate), 'actual_functions'", "'candidate_sha256': sha(candidate), 'baseline_sha256': sha(baseline), 'baseline_compatible_hex': baseline_compatible.hex(), 'actual_functions'",1)
        target=HERE/(Path(name).stem+'-v2.py')
        assert not target.exists()
        target.write_text(text,newline='\n')
        generated[target.name]=sha(target)
    report={'baseline_sha256':BASE_SHA,'baseline_bytes':163285,'input_files':records,'generated_tools_sha256':generated,
        'old_sealed_v1_manifest_sha256':sha(old/'manifest.json'),'old_sealed_v1_snapshot_files_unchanged':len(manifest['files_sha256']),
        'tool_change_scope':'BASE path/SHA/size only; OF tested-baseline vector reads the actual new baseline DT. Existing algorithms/fixtures retained.',
        'hardware_or_network_access':False,'linux_execution_by_preparation':False}
    (inputs/'manifest.json').write_text(json.dumps(report,indent=2)+'\n',newline='\n')
    print(json.dumps({'inputs':len(records),'old_snapshot_files':len(manifest['files_sha256']),'v2_tools':list(generated)}))

if __name__=='__main__':
    main()
