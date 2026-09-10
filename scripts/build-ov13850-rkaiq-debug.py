#!/usr/bin/env python3
"""Build RKAIQ from a fresh, patched snapshot; never reuse an unverified work copy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_sha256(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update(sha256(path).encode() + b"\0")
    return digest.hexdigest()


def prepare_source(source, destination, patch_dir):
    # Materialize symlinks: later SDK edits must not alter this build's input.
    shutil.copytree(source, destination, symlinks=False,
                    ignore=shutil.ignore_patterns(".git"))
    source_hash = tree_sha256(destination)
    patches = []
    for line in (patch_dir / "series").read_text().splitlines():
        name = line.strip()
        if not name or name.startswith("#"):
            continue
        patch = patch_dir / name
        if Path(name).name != name or not patch.is_file():
            raise ValueError(f"Invalid patch series entry: {name}")
        subprocess.run(["patch", "--batch", "--forward", "--fuzz=0", "-p1",
                        "--directory", str(destination), "-i", str(patch.resolve())], check=True)
        patches.append({"name": name, "sha256": sha256(patch)})
    return {"source_snapshot_sha256": source_hash, "patches": patches,
            "patched_source_sha256": tree_sha256(destination)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-root", required=True, type=Path)
    parser.add_argument("--prepare-only", action="store_true",
                        help="Snapshot and apply patches without configuring or compiling")
    parser.add_argument("--jobs", type=int, default=6)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    repo = Path(__file__).resolve().parents[1]
    sdk = args.sdk_root.resolve()
    origin = sdk / "external/camera_engine_rkaiq"
    if not (origin / "rkaiq/CMakeLists.txt").is_file():
        parser.error(f"Missing RKAIQ source: {origin}")
    build_root = repo / "build/rkaiq"
    build_root.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="run-", dir=build_root))
    source, output = run / "source", run / "build"
    manifest = {"schema_version": 1, "status": "preparing", "sdk_root": str(sdk),
                "source_directory": str(source), "build_directory": str(output)}
    manifest_path = run / "manifest.json"
    try:
        manifest.update(prepare_source(origin, source, repo / "patches/rkaiq"))
        revision = subprocess.run(["git", "-C", str(origin), "rev-parse", "HEAD"],
                                  text=True, capture_output=True, check=False)
        manifest["sdk_source_commit_informational"] = revision.stdout.strip() if revision.returncode == 0 else None
        manifest["status"] = "prepared"
        if not args.prepare_only:
            host = sdk / "prebuilts/gcc/linux-x86/aarch64/gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu"
            compiler = host / "bin/aarch64-none-linux-gnu-gcc"
            env = os.environ.copy()
            env.update(AIQ_BUILD_HOST_DIR=str(host), AIQ_BUILD_TOOLCHAIN_TRIPLE="aarch64-none-linux-gnu",
                       AIQ_BUILD_SYSROOT="libc", AIQ_BUILD_ARCH="aarch64")
            env["PATH"] = str(repo / "work/host-tools/usr/bin") + os.pathsep + env["PATH"]
            if not shutil.which("m4", path=env["PATH"]):
                raise RuntimeError("Install m4 or provide work/host-tools/usr/bin/m4")
            configure = ["cmake", "-G", "Ninja", "-S", str(source / "rkaiq"), "-B", str(output),
                         "-DCMAKE_INSTALL_PREFIX=" + str(run / "install"),
                         "-DCMAKE_BUILD_TYPE=RelWithDebInfo", "-DRKAIQ_TARGET_SOC=rv1126b", "-DARCH=aarch64",
                         "-DCMAKE_TOOLCHAIN_FILE=" + str(source / "rkaiq/cmake/toolchains/gcc.cmake"),
                         "-DRKAIQ_BUILD_BINARY_IQ=ON", "-DCMAKE_EXPORT_COMPILE_COMMANDS=YES",
                         "-DISP_HW_VERSION=-DISP_HW_V35", "-DRKAIQ_USE_RAWSTREAM_LIB=OFF",
                         "-DRKAIQ_HAVE_FAKECAM=ON", "-DRKAIQ_ENABLE_AF=ON",
                         "-DCMAKE_C_FLAGS_RELWITHDEBINFO=-O1 -g -fno-omit-frame-pointer",
                         "-DCMAKE_CXX_FLAGS_RELWITHDEBINFO=-O1 -g -fno-omit-frame-pointer"]
            manifest.update(compiler=str(compiler), compiler_sha256=sha256(compiler), configure_args=configure)
            with (run / "configure.log").open("w") as log:
                subprocess.run(configure, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
            subprocess.run(["cmake", "--build", str(output), "--target", "rkaiq", "-j", str(args.jobs)],
                           env=env, check=True)
            library = output / "all_lib/RelWithDebInfo/librkaiq.so"
            manifest.update(status="built", output=str(library), output_sha256=sha256(library),
                            cmake_cache_sha256=sha256(output / "CMakeCache.txt"))
        manifest["limitations"] = ["Includes SDK precompiled algorithms; toolchain/sysroot are external inputs",
                                  "Build target is librkaiq; server patches are staged but the server is not built here",
                                  "No board validation or system library replacement"]
    except Exception as error:
        manifest.update(status="failed", error=str(error))
        raise
    finally:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"Build manifest: {manifest_path}")


if __name__ == "__main__":
    main()
