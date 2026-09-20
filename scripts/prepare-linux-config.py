#!/usr/bin/env python3
"""Resolve a data-driven Linux candidate config; never build/flash a board DTB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


REPO = Path(__file__).resolve().parents[1]


def load_candidate(path, repo=REPO):
    candidate = json.loads(path.read_text())
    required = ("schema", "board", "soc", "arch", "source", "source_commit",
                "defconfig", "cross_compile", "fragments")
    if not isinstance(candidate, dict) or any(key not in candidate for key in required):
        raise ValueError("candidate must contain " + ", ".join(required))
    if candidate["schema"] != 1:
        raise ValueError("unsupported candidate schema")
    for key in ("board", "soc", "arch"):
        if not isinstance(candidate[key], str) or not re.fullmatch(r"[a-z0-9_-]+", candidate[key]):
            raise ValueError(f"invalid candidate {key}")
    if not isinstance(candidate["source_commit"], str) or not re.fullmatch(
            r"[0-9a-f]{40}", candidate["source_commit"]):
        raise ValueError("candidate must pin a full kernel Git commit")
    if not isinstance(candidate["defconfig"], str) or not re.fullmatch(
            r"(?:[A-Za-z0-9_-]+_)?defconfig", candidate["defconfig"]):
        raise ValueError("defconfig must name defconfig or an existing *_defconfig")
    if not isinstance(candidate["cross_compile"], str) or not re.fullmatch(
            r"[A-Za-z0-9_./+-]+", candidate["cross_compile"]):
        raise ValueError("unsupported candidate cross-compiler prefix")
    if not isinstance(candidate["fragments"], list) or not candidate["fragments"]:
        raise ValueError("candidate requires at least one config fragment")
    for relative in [candidate["source"], *candidate["fragments"]]:
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise ValueError("candidate paths must be repository-relative")
        resolved = (repo / relative).resolve()
        if repo.resolve() not in resolved.parents:
            raise ValueError("candidate paths must stay inside repository")
    return candidate


def requested_settings(fragments):
    result = {}
    for fragment in fragments:
        # Board fragments may deliberately override SoC defaults, in order.
        result.update(settings(fragment.read_text()))
    if not result:
        raise ValueError("candidate fragments contain no configuration settings")
    return result


def settings(text):
    result = {}
    for line in text.splitlines():
        enabled = re.fullmatch(r'(CONFIG_[A-Za-z0-9_]+)=(.+)', line.strip())
        disabled = re.fullmatch(r'# (CONFIG_[A-Za-z0-9_]+) is not set', line.strip())
        if not enabled and not disabled:
            if line.strip() and not line.lstrip().startswith("#"):
                raise ValueError(f"malformed configuration line: {line}")
            continue
        key, value = enabled.groups() if enabled else (disabled.group(1), "n")
        if key in result and result[key] != value:
            raise ValueError(f"conflicting assignments for {key}")
        result[key] = value
    return result


def audit_config(fragment, resolved):
    return audit_settings(settings(fragment), resolved)


def audit_settings(requested, resolved):
    actual = settings(resolved)
    return [f"{key}: requested {value}, resolved {actual.get(key, 'n')}"
            for key, value in requested.items()
            if actual.get(key, "n") != value]


def validate_output(source, output):
    source, output = source.resolve(), output.resolve()
    if output == source or source in output.parents or output in source.parents:
        raise ValueError("output must be outside the kernel source tree")
    if any(not re.fullmatch(r"[A-Za-z0-9_./+-]+", str(path)) for path in (source, output)):
        raise ValueError("Kbuild paths require ASCII letters, digits, / . _ + - only")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("output must be a new or empty directory; existing data is preserved")
    return output


def git_info(source):
    def query(*args):
        return subprocess.check_output(["git", "-C", str(source), *args],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    try:
        return {"commit": query("rev-parse", "HEAD"),
                "dirty": bool(query("status", "--porcelain"))}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def build_environment(output):
    # Kbuild/Kconfig interpret their own paths, even when subprocess uses argv.
    # Strip all KCONFIG_* overrides, including autoheader/autoconfig output paths.
    overrides = {"KBUILD_OUTPUT", "KBUILD_SRC", "KBUILD_EXTMOD", "MAKEFLAGS",
                 "MFLAGS", "MAKEOVERRIDES", "ARCH", "CROSS_COMPILE"}
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("KCONFIG_") and key not in overrides}
    env["PATH"] = str(REPO / ".deps/host-tools/bin") + os.pathsep + env.get("PATH", "")
    env["KCONFIG_CONFIG"] = str(output / ".config")
    return env


def prepare(args, candidate, fragments):
    source = (args.source or REPO / candidate["source"]).resolve()
    output = validate_output(source, args.output)
    cross_compile = args.cross_compile or candidate["cross_compile"]
    if not re.fullmatch(r"[A-Za-z0-9_./+-]+", cross_compile):
        raise ValueError("unsupported cross-compiler prefix")
    for file in (source / "Makefile", source / "scripts/kconfig/merge_config.sh",
                 source / "arch" / candidate["arch"] / "configs" / candidate["defconfig"],
                 *fragments):
        if not file.is_file():
            raise ValueError(f"missing build input: {file}")
    provenance = git_info(source)
    if provenance["commit"] != candidate["source_commit"] or provenance["dirty"]:
        raise ValueError("kernel differs from the candidate's pinned clean commit; "
                         "review the source and candidate together")
    env = build_environment(output)
    for command in ("make", "bash", "flex", "bison", cross_compile + "gcc"):
        if not shutil.which(command, path=env["PATH"]):
            raise ValueError(f"missing build command: {command}")
    output.mkdir(parents=True, exist_ok=True)
    make = ["make", "-C", str(source), f"O={output}", f"ARCH={candidate['arch']}",
            f"CROSS_COMPILE={cross_compile}"]

    def run(command):
        print("+", " ".join(command), flush=True)
        subprocess.run(command, env=env, cwd=output, check=True)

    run(make + [candidate["defconfig"]])
    run(["bash", str(source / "scripts/kconfig/merge_config.sh"), "-m", "-O",
         str(output), str(output / ".config"), *map(str, fragments)])
    run(make + ["olddefconfig"])
    requested = requested_settings(fragments)
    failures = audit_settings(requested, (output / ".config").read_text())
    if failures:
        raise ValueError("Kconfig dropped/changed requested settings:\n" + "\n".join(failures))
    if args.prepare_headers:
        run(make + ["prepare", "modules_prepare"])
    compiler = subprocess.check_output([cross_compile + "gcc", "--version"],
                                       env=env, text=True).splitlines()[0]
    digest = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
    manifest = {
        "board_candidate": candidate["board"], "soc_candidate": candidate["soc"],
        "arch": candidate["arch"],
        "status": "config-only; board wiring and boot not validated",
        "source": str(source), **provenance, "defconfig": candidate["defconfig"],
        "compiler": compiler, "cross_compile": cross_compile,
        "candidate_sha256": digest(args.candidate),
        "fragments": [{"path": str(file.relative_to(REPO)), "sha256": digest(file)}
                      for file in fragments],
        "config_sha256": digest(output / ".config"),
        "headers_prepared": args.prepare_headers, "dtb": None,
        "image_built": False, "modules_built": False, "deployable": False,
    }
    (output / "kernel-config-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"Audited {len(requested)} settings: {output / '.config'}")
    print("Candidate only: no board DTB, boot image, module installation or flashing.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True,
                        help="kernel-candidate.json with explicit build inputs")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path, help="new/empty external build directory")
    mode.add_argument("--check-config", type=Path, help="audit an existing resolved .config")
    parser.add_argument("--source", type=Path, help="alternate checkout of the pinned kernel")
    parser.add_argument("--cross-compile", help="override the profile compiler prefix")
    parser.add_argument("--prepare-headers", action="store_true",
                        help="also run prepare/modules_prepare (no Module.symvers guarantee)")
    args = parser.parse_args()
    try:
        candidate = load_candidate(args.candidate)
        fragments = [REPO / file for file in candidate["fragments"]]
        if args.check_config:
            failures = audit_settings(requested_settings(fragments), args.check_config.read_text())
            if failures:
                raise ValueError("\n".join(failures))
            print("Candidate fragment matches resolved configuration; board wiring still unverified.")
        else:
            prepare(args, candidate, fragments)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
