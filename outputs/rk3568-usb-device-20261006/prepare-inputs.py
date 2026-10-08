#!/usr/bin/env python3
"""SHA-lock exact tested Linux DT and existing USB dependency/source evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
BASE_REL='outputs/rk3568-audio-runtime-20261005/build/audio-ram-shim-v1/applied-audit-only.dtb'
BASE_SHA='4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f'
FORMAL=ROOT/'outputs/rk3568-formal-dtb-20261005'
PACKAGE=ROOT/'outputs/rk3568-boot-package-20261005'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    out=HERE/'inputs-v1'
    out.mkdir(exist_ok=False)
    assert sha(ROOT/BASE_REL)==BASE_SHA
    assert (ROOT/BASE_REL).stat().st_size==163285
    records={}
    def copy(path,rel,expected=None):
        value=sha(path)
        if expected:
            assert value==expected,str(path)
        target=out/rel
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target)
        assert sha(target)==value
        records[Path(rel).as_posix()]={'source':path.relative_to(ROOT).as_posix(),'sha256':value}
    copy(ROOT/BASE_REL,'audio-linux-tested.dtb',BASE_SHA)
    for name,expected in [('dt-semantics-v2.py','b89b3e4dab11281e02ec4a31104907e8b66579ba2e44556c4108d470f468aa56'),('libfdt-v2.py','9fdba61ae8d7d004ac7f24b7f116f6a314032c01624357f01619f609a5b8a954')]:
        copy(PACKAGE/name,name,expected)
    copy(PACKAGE/'build/libfdt-v2/libfdt-locked.so','build/libfdt-v2/libfdt-locked.so','03c8661fb005cd967c768332622c6aed6415dbcdce31939de26933e61b388a18')
    copy(ROOT/'.deps/kernel/aiot-3568pq-rcu-reset/scripts/dtc/dtc','dtc','3be6ad1bcef2e36b35624e9f2cd6c13957949e08818868ad04ad070b4fd9e896')
    for name in ('USB-DEPENDENCIES.md','README.md','audit-usb-closure.py'):
        copy(FORMAL/name,'prior/'+name)
    copy(FORMAL/'build/usb-source-v1/result.json','prior/usb-source-result.json')
    source_record=json.loads((FORMAL/'build/usb-source-v1/result.json').read_text())
    for name in ('drivers/usb/dwc3/core.c','drivers/usb/dwc3/dwc3-of-simple.c','drivers/phy/phy-core.c','drivers/phy/rockchip/phy-rockchip-inno-usb2.c'):
        expected=source_record['inputs_sha256']['third_party\\linux-rk3588\\'+name.replace('/','\\')]
        copy(FORMAL/'build/usb-source-v1/source-snapshot'/name,'source/'+name,expected)
    copy(FORMAL/'build/usb-source-v1/source-snapshot/kernel.config','source/kernel.config','1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912')
    copy(FORMAL/'build/usb-closure-v3/result.json','prior/usb-closure-result.json')
    copy(FORMAL/'build/usb-closure-v3/candidate-usb-closure.json','prior/usb-closure.json')
    copy(ROOT/'outputs/rk3568-audio-runtime-20261005/build/audio-ram-shim-v1/manifest.json','prior/audio-shim-manifest.json')
    spec=importlib.util.spec_from_file_location('input_semantic',out/'dt-semantics-v2.py')
    semantic=importlib.util.module_from_spec(spec);spec.loader.exec_module(semantic)
    tree=semantic.parse((out/'audio-linux-tested.dtb').read_bytes())
    paths=['/usbdrd','/usbdrd/dwc3@fcc00000','/usb2-phy@fe8a0000','/usb2-phy@fe8a0000/otg-port','/usbhost','/phy@fe820000']
    props={path:{key.rsplit(':',1)[1]:value for key,value in tree['properties'].items() if key.rsplit(':',1)[0]==path} for path in paths}
    report={'files':records,'baseline_sha256':BASE_SHA,'baseline_bytes':163285,'baseline_selected_properties':props,
        'nodes':len(tree['nodes']),'properties':len(tree['properties']),'phandles':len(semantic.phandles(tree)),
        'hardware_access':False,'linux_libfdt_executed':False,'dtc_executed':False}
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n',newline='\n')
    print(json.dumps({'files':len(records),'properties':props,'nodes':report['nodes'],'phandles':report['phandles']}))

if __name__=='__main__':
    main()
