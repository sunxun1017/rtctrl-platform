#!/usr/bin/env python3
"""Keep original sealed tools intact; prepare versioned review regressions."""
import json
import shutil
from pathlib import Path
from source_utils import sha

HERE = Path(__file__).resolve().parent
TARGET = HERE / "review-regression-v1"


def main():
    TARGET.mkdir(exist_ok=False)
    shutil.copytree(HERE / "source-input-v1", TARGET / "source-input-v1")
    tools = ["test-params.py", "test-lifecycle.py", "test-config.py", "test-params-shim.h", "test-lifecycle-shim.h", "test-config-shim.h", "test-params-main.c", "test-lifecycle-main.c", "test-irq-main.c", "test-pm-main.c", "test-config-main.c", "source_utils.py"]
    record = {}
    for name in tools:
        original = (HERE / name).read_bytes()
        text = original.decode()
        if name.endswith(".py"):
            text = text.replace("ROOT = HERE.parents[1]", "ROOT = HERE.parents[2]")
        if name in ["test-lifecycle-main.c", "test-irq-main.c", "test-pm-main.c"]:
            text = text.replace("info.checked_lifecycle = true;", "info.checked_lifecycle = true;\n    info.ready = true; /* Normal regression fixtures represent completed probe. */")
        (TARGET / name).write_text(text)
        record[name] = {"original_sha256": sha(original), "revision_sha256": sha(text.encode())}
    for original_name, new_name, before, after in [
        ("build-object.py", "build-review-object.py", '"kbuild-object-"', '"kbuild-review-object-"'),
        ("verify-dt-profile.py", "verify-review-dt-profile.py", '"actual-dt-profile-"', '"actual-dt-review-profile-"'),
    ]:
        original = (HERE / original_name).read_bytes()
        text = original.decode().replace(before, after)
        if new_name.startswith("verify"):
            text = text.replace("if checked.parent != HERE:", "if checked.parent != TARGET:").replace("HERE = Path(__file__).resolve().parent", "HERE = Path(__file__).resolve().parent\nTARGET = HERE / 'review-regression-v1'")
        path = HERE / new_name
        if path.exists():
            raise ValueError("review tool exists")
        path.write_text(text)
        record[new_name] = {"original": original_name, "original_sha256": sha(original), "revision_sha256": sha(text.encode())}
    (TARGET / "runner-provenance.json").write_text(json.dumps(record, indent=2) + "\n")
    print(TARGET)


if __name__ == "__main__":
    main()
