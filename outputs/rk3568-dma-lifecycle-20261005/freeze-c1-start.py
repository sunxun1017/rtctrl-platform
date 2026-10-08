#!/usr/bin/env python3
"""New immutable C1 receipt for the checked profile debugfs publication fix."""
import json,subprocess
from pathlib import Path
from source_utils import sha
from freeze_c1_import import strict_replay
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def main():
    review=HERE/"C1-review-v5";review.mkdir(exist_ok=False);candidate=HERE/"driver-source-v18"
    manifest=json.loads((candidate/"manifest.json").read_text());kernel=ROOT/"third_party/linux-rk3588"
    for argv,wanted in [(["git","-C",kernel,"rev-parse","HEAD"],manifest["kernel_commit"]),(["git","-C",kernel,"status","--porcelain"],"")]:
        if subprocess.run(argv,check=True,capture_output=True,text=True).stdout.strip()!=wanted:raise ValueError("locked original rejected")
    paths=["drivers/dma/pl330.c","include/linux/dmaengine.h","drivers/dma/dmaengine.c"]
    before={p:(kernel/p).read_bytes() for p in paths};patch=(candidate/"C1-ownership-review.patch").read_bytes()
    if sha(patch)!=manifest["patch_sha256"]:raise ValueError("patch drift")
    replay=strict_replay(before,patch.decode())
    if any(replay[p]!=(candidate/p).read_bytes() for p in paths):raise ValueError("replay mismatch")
    context_rejected=False
    try:strict_replay({**before,paths[0]:before[paths[0]].replace(b"#include <linux/dma-mapping.h>",b"#include <linux/bogus.h>",1)},patch.decode())
    except ValueError:context_rejected=True
    if not context_rejected:raise ValueError("context tamper accepted")
    evidence=[("pl330-start-tests-green-v1",67,"source_sha256"),("pl330-start-hw-tests-green-v2",17,"source_sha256"),("dma-admission-tests-green-v4",9,"core_sha256"),("pl330-debugfs-tests-green-v3",2,"source_sha256")]
    for name,count,field in evidence:
        result=json.loads((HERE/name/"result.json").read_text())
        if not result["passed"] or result["source_sha256"]!=manifest[field] or any(run["tests"]!={"total":count,"passed":count,"failed":0} or run["compile"]["returncode"] or run["execution"]["returncode"] for run in result["runs"].values()):raise ValueError("green evidence rejected")
    generators=review/"generators";generators.mkdir()
    for name in ["driver-prepare-c1-start.py","test-pl330-debugfs.py","test-pl330-start.py","test-pl330-start-shim.h","test-pl330-start-main.c","test-pl330-start-hardware.py","test-pl330-start-hw-shim.h","test-pl330-start-hw-main.c","freeze-c1-start.py","freeze_c1_import.py","source_utils.py"]:(generators/name).write_bytes((HERE/name).read_bytes())
    (review/"DEBUGFS-SCOPE.md").write_text("Checked PL330 registration precedes debugfs admission in the real probe. This profile now publishes no old raw-pointer debugfs file, so there is no old/new debugfs reader to drain during remove. CONFIG_DEBUG_FS=n already publishes none. The unprotected helper branch retains its previous behavior; this patch does not claim safe unbind for unprotected profiles. Lifecycle observation remains a later read-only interface requirement. C2/C3, production compile, board START and deployment remain incomplete.\n")
    folders=[candidate,*[HERE/name for name,_,_ in evidence],HERE/"pl330-debugfs-tests-red-v1",HERE/"pl330-terminate-tests-red-v1",HERE/"pl330-start-tests-red-v2",HERE/"pl330-start-hw-tests-red-v2",review]
    files={str(path.relative_to(HERE)):sha(path.read_bytes()) for folder in folders for path in sorted(folder.rglob("*")) if path.is_file()}
    receipt={"c1_frozen":True,"published":False,"deployable":False,"board_tested":False,"production_compiled":False,"kernel_commit":manifest["kernel_commit"],"original_kernel_clean":True,"candidate":str(candidate),"candidate_manifest_sha256":sha((candidate/"manifest.json").read_bytes()),"parent_receipt_sha256":manifest["parent_receipt_sha256"],"source_sha256":manifest["source_sha256"],"header_sha256":manifest["header_sha256"],"core_sha256":manifest["core_sha256"],"patch_sha256":sha(patch),"strict_three_file_replay_matches":True,"exact_context_tamper_rejected":True,"patch_hash_tamper_rejected":sha(patch+b"tamper")!=manifest["patch_sha256"],"debugfs_checked_profile_published":False,"tests_per_environment":95,"green_results":[str(HERE/name/"result.json") for name,_,_ in evidence],"c2_implemented":False,"c3_implemented":False,"remaining":["independent C1 review","full provider production compile","PCM allocation quarantine registration and actual native hw_params chain","ASoC START rollback and STOP cleanup","read-only lifecycle observation"],"files_sha256":files}
    (review/"receipt.json").write_text(json.dumps(receipt,indent=2)+"\n");print(json.dumps({"receipt":str(review/"receipt.json"),"receipt_sha256":sha((review/"receipt.json").read_bytes()),"files":len(files),"tests_per_environment":95,"deployable":False}))
if __name__=="__main__":main()
