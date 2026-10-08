#!/usr/bin/env python3
"""Immutable review receipt, strict in-memory replay, SHA gates and evidence hashes."""
import json
import re
import subprocess
from pathlib import Path
from source_utils import sha
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
KERNEL=ROOT/"third_party/linux-rk3588"
COMMIT="9f9e9d18574d0914c0d192a90c3babfe1fd63c95"


def replay(before,patch):
    output={};lines=patch.splitlines(True);i=0
    while i<len(lines):
        match=re.fullmatch(r"diff --git a/(\S+) b/(\S+)\n",lines[i])
        if not match or match[1]!=match[2]:raise ValueError("unexpected patch file header")
        path=match[1];i+=1
        if path in output or path not in before:raise ValueError("unexpected or duplicate patch path")
        if lines[i]!="--- a/"+path+"\n" or lines[i+1]!="+++ b/"+path+"\n":raise ValueError("mismatched unified paths")
        i+=2;original=before[path].decode().splitlines(True);result=[];cursor=0
        while i<len(lines) and not lines[i].startswith("diff --git "):
            match=re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n",lines[i])
            if not match:raise ValueError("invalid hunk header")
            start=int(match[1])-1 if int(match[1]) else 0
            old_count=int(match[2]) if match[2] is not None else 1
            new_start=int(match[3])-1 if int(match[3]) else 0
            new_count=int(match[4]) if match[4] is not None else 1
            if start<cursor or start>len(original):raise ValueError("old hunk location rejected")
            result.extend(original[cursor:start]);cursor=start
            if len(result)!=new_start:raise ValueError("new hunk location rejected")
            i+=1;old_used=new_used=0
            while i<len(lines) and not lines[i].startswith(("@@ ","diff --git ")):
                line=lines[i]
                if line[0] in " -":
                    if cursor>=len(original) or original[cursor]!=line[1:]:raise ValueError("exact context rejected")
                    cursor+=1;old_used+=1
                if line[0] in " +":result.append(line[1:]);new_used+=1
                if line[0] not in " +-":raise ValueError("unsupported hunk line")
                i+=1
            if old_used!=old_count or new_used!=new_count:raise ValueError("hunk count rejected")
        result.extend(original[cursor:]);output[path]="".join(result).encode()
    if set(output)!=set(before):raise ValueError("missing patch target")
    return output


def main():
    review=HERE/"C1-review-v2";review.mkdir(exist_ok=False)
    candidate=HERE/"driver-source-v15";manifest=json.loads((candidate/"manifest.json").read_text())
    if subprocess.run(["git","-C",KERNEL,"rev-parse","HEAD"],check=True,capture_output=True,text=True).stdout.strip()!=COMMIT:raise ValueError("locked commit rejected")
    if subprocess.run(["git","-C",KERNEL,"status","--porcelain"],check=True,capture_output=True,text=True).stdout.strip():raise ValueError("original dirty rejected")
    before={name:(KERNEL/name).read_bytes() for name in ["drivers/dma/pl330.c","include/linux/dmaengine.h","drivers/dma/dmaengine.c"]}
    fields=[("drivers/dma/pl330.c","source"),("include/linux/dmaengine.h","header"),("drivers/dma/dmaengine.c","core")]
    for path,prefix in fields:
        if sha(before[path])!=manifest[prefix+"_sha256_before"] or sha((candidate/path).read_bytes())!=manifest[prefix+"_sha256"]:raise ValueError("production source SHA rejected")
    patch=(candidate/"C1-ownership-review.patch").read_bytes()
    if sha(patch)!=manifest["patch_sha256"]:raise ValueError("candidate patch SHA rejected")
    result=replay(before,patch.decode())
    if any(result[path]!=(candidate/path).read_bytes() for path in before):raise ValueError("replay differs from candidate")
    tamper={**before,"drivers/dma/pl330.c":before["drivers/dma/pl330.c"].replace(b"#include <linux/dma-mapping.h>",b"#include <linux/bogus.h>",1)}
    context_rejected=False
    try:replay(tamper,patch.decode())
    except ValueError:context_rejected=True
    if not context_rejected:raise ValueError("tampered context accepted")
    scripts=review/"generators";scripts.mkdir()
    for name,wanted in manifest["generator_sha256"].items():
        data=(HERE/name).read_bytes()
        if sha(data)!=wanted:raise ValueError("generator drift")
        (scripts/name).write_bytes(data)
    for name in ["PLAN.md","freeze-c1.py"]:(review/name).write_bytes((HERE/name).read_bytes())
    evidence=[("pl330-tests-green-v21",63),("pl330-hw-tests-green-v4",15),("dma-admission-tests-green-v3",9)]
    for directory,count in evidence:
        r=json.loads((HERE/directory/"result.json").read_text())
        if not r["passed"] or any(run["tests"]!={"total":count,"passed":count,"failed":0} or run["compile"]["returncode"] or run["execution"]["returncode"] for run in r["runs"].values()):raise ValueError("test result rejected")
        wanted=manifest["core_sha256"] if directory.startswith("dma-admission") else manifest["source_sha256"]
        if r["source_sha256"]!=wanted:raise ValueError("tests bound to another source")
    directories=[candidate,*[HERE/name for name,_ in evidence],*[HERE/name for name in ["pl330-tests-red-v18","pl330-tests-red-v20","pl330-tests-red-v23","pl330-tests-red-v24","pl330-tests-red-v25","dma-admission-tests-red-v1","pl330-hw-tests-red-v2"]]]
    files={str(path.relative_to(HERE)):sha(path.read_bytes()) for folder in directories for path in sorted(folder.rglob("*")) if path.is_file()}
    files.update({str(path.relative_to(HERE)):sha(path.read_bytes()) for path in sorted(review.rglob("*")) if path.is_file()})
    receipt={"c1_frozen":True,"published":False,"deployable":False,"board_tested":False,"production_compiled":False,"kernel_commit":COMMIT,"original_kernel_clean":True,
             "candidate":str(candidate.resolve()),"candidate_manifest_sha256":sha((candidate/"manifest.json").read_bytes()),"patch_sha256":sha(patch),
             "source_sha256":manifest["source_sha256"],"header_sha256":manifest["header_sha256"],"core_sha256":manifest["core_sha256"],
             "strict_three_file_replay_matches":True,"exact_context_tamper_rejected":True,"patch_hash_tamper_rejected":sha(patch+b"tamper")!=manifest["patch_sha256"],
             "tests_per_environment":87,"green_results":[str(HERE/name/"result.json") for name,_ in evidence],
             "c2_implemented":False,"c3_implemented":False,"remaining":["independent C1 review","full provider production compile","PCM coherent allocation ownership quarantine","ASoC START rollback and STOP cleanup","read-only board poison/quarantine/lease/STOPPED observation"],"files_sha256":files}
    (review/"receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(json.dumps({"receipt":str(review/"receipt.json"),"receipt_sha256":sha((review/"receipt.json").read_bytes()),"files":len(files),"tests_per_environment":87,"deployable":False}))
if __name__=="__main__":main()
