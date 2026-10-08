#!/usr/bin/env python3
"""Create fresh probe revision and full 0011 incremental patch without kernel edits."""
import argparse
import difflib
import json
import re
import subprocess
from pathlib import Path
from source_utils import sha
from pl330_probe_changes import apply
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
KERNEL=ROOT/'third_party/linux-rk3588'
COMMIT='9f9e9d18574d0914c0d192a90c3babfe1fd63c95'

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--version',required=True);a=p.parse_args()
    if not re.fullmatch(r'v[6-9]|v[1-9][0-9]+',a.version):p.error('fresh v6 or later required')
    out=HERE/('driver-source-c3-'+a.version)
    if out.exists():raise ValueError('fresh directory required')
    for argv,wanted in [(['git','-C',KERNEL,'rev-parse','HEAD'],COMMIT),(['git','-C',KERNEL,'status','--porcelain'],'')]:
        if subprocess.run(argv,check=True,capture_output=True,text=True).stdout.strip()!=wanted:raise ValueError('locked original gate rejected')
    base=HERE/'driver-source-c3-v5';old=json.loads((base/'manifest.json').read_text())
    receipt=HERE/'C3-review-v1/receipt.json'
    if sha(receipt.read_bytes())!='1331508fb0182e62727a4ff6cfcf2d8118407e20c5a9bdd56425d6d773d6c5a5':raise ValueError('rejected v5 receipt drift')
    after={path:(base/path).read_bytes() for path in old['source_sha256']}
    for path,wanted in old['source_sha256'].items():
        if sha(after[path])!=wanted:raise ValueError('frozen v5 source drift')
    after['drivers/dma/pl330.c']=apply(after['drivers/dma/pl330.c'].decode()).encode()
    b=ROOT/'outputs/rk3568-asoc-errors-20261005/driver-source-v2'
    before={path:((b if path in ['sound/soc/soc-pcm.c','sound/core/pcm_native.c'] else KERNEL)/path).read_bytes() for path in after}
    for path,wanted in old['before_sha256'].items():
        if sha(before[path])!=wanted:raise ValueError('incremental base drift')
    patch=''
    for path,data in after.items():
        if data!=before[path]:patch+='diff --git a/'+path+' b/'+path+'\n'+''.join(difflib.unified_diff(before[path].decode().splitlines(True),data.decode().splitlines(True),fromfile='a/'+path,tofile='b/'+path))
    out.mkdir()
    for path,data in after.items():
        target=out/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    (out/'C3-lifecycle-review.patch').write_text(patch)
    manifest={**old,'phase':'Probe/IRQ publication and error/storage ownership revision; independent complete group review pending',
              'parent_rejected_receipt_sha256':sha(receipt.read_bytes()),'parent_source_sha256':old['source_sha256'],
              'source_sha256':{path:sha(data) for path,data in after.items()},'patch_sha256':sha(patch.encode()),
              'generator_sha256':{name:sha((HERE/name).read_bytes()) for name in ['driver-prepare-c3-probe.py','pl330_probe_changes.py','source_utils.py']}}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'output':str(out),'source_sha256':manifest['source_sha256']['drivers/dma/pl330.c'],'patch_sha256':manifest['patch_sha256'],'deployable':False}))
if __name__=='__main__':main()
