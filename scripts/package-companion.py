#!/usr/bin/env python3
"""Build a portable companion bundle without credentials or board state."""
import argparse
import hashlib
import json
import pathlib
import shutil
import tarfile
import tempfile

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-deps", type=pathlib.Path,
                        help="pip --target directory containing websocket-client 1.8.0")
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    root = pathlib.Path(__file__).resolve().parents[1]
    output = args.output or root / "build/companion/rtctrl-companion.tar.gz"
    if args.python_deps:
        deps = args.python_deps.resolve()
        metadata = list(deps.glob("websocket_client-1.8.0.dist-info/METADATA"))
        if not (deps / "websocket").is_dir() or not metadata:
            parser.error("--python-deps must contain websocket-client 1.8.0 installed with --target")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rtctrl-companion-") as temp:
        stage = pathlib.Path(temp)
        for path in ("apps/companion", "config/companion", "deploy/companion"):
            shutil.copytree(root/path, stage/path,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy2(root/"deploy/companion/run-companion.sh",stage/"run-companion.sh")
        shutil.copy2(root/"apps/companion/README.md",stage/"README.md")
        shutil.copy2(root/"LICENSE",stage/"LICENSE")
        if args.python_deps:
            for path in ("websocket", "websocket_client-1.8.0.dist-info"):
                shutil.copytree(deps/path,stage/"vendor"/path,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        manifest = {}
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                manifest[str(path.relative_to(stage))] = hashlib.sha256(path.read_bytes()).hexdigest()
        (stage/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
        with tarfile.open(output, "w:gz") as archive:
            for path in sorted(stage.iterdir()):
                archive.add(path,arcname=path.name)
    print(output)

if __name__ == "__main__":
    main()
