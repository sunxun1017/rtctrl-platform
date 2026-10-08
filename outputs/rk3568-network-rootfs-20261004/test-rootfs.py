#!/usr/bin/env python3
"""Exercise packaging refusals and real ext4 tampering boundaries, without a mount."""
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("rootfs_verifier", HERE / "verify-rootfs.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
builder = verifier.builder


def rejection(function, message):
    try:
        function()
    except (ValueError, OSError) as error:
        if message not in str(error):
            raise AssertionError("Unexpected failure: " + str(error)) from error
        return
    raise AssertionError("Expected rejection: " + message)


def tamper_case(base, folder, commands, expected):
    folder.mkdir()
    (folder / "build").mkdir()
    shutil.copyfile(base / "rootfs.img", folder / "rootfs.img")
    shutil.copyfile(base / "rootfs-manifest.json", folder / "rootfs-manifest.json")
    for command in commands:
        builder.run(["debugfs", "-w", "-R", command, str(folder / "rootfs.img")])
    # Update the outer checksum to require semantic/inode inspection, not only SHA.
    manifest = json.loads((folder / "rootfs-manifest.json").read_text())
    manifest["image"]["sha256"] = builder.sha((folder / "rootfs.img").read_bytes())
    (folder / "rootfs-manifest.json").write_text(json.dumps(manifest))
    rejection(lambda: verifier.verify(folder, execute=False), expected)


def main():
    initial = verifier.verify(HERE)
    original_sha = initial["image_sha256"]
    results = ["actual_image_e2fsck_inode_payload_and_qemu"]
    rejection(lambda: builder.build(HERE), "Refusing existing output")
    results.append("existing_primary_build_refused")
    with tempfile.TemporaryDirectory(prefix="negative-tests-", dir=HERE / "build") as temporary:
        work = Path(temporary)
        outside = Path(tempfile.gettempdir()) / "rtctrl-rootfs-forbidden-output"
        rejection(lambda: builder.build(outside), "outside allowed boundary")
        results.append("output_outside_boundary_refused")
        existing = work / "existing-image"
        existing.mkdir()
        (existing / "rootfs.img").write_bytes(b"untouched")
        rejection(lambda: builder.build(existing), "Refusing existing output")
        assert (existing / "rootfs.img").read_bytes() == b"untouched"
        assert not (existing / "build").exists()
        results.append("existing_image_preserved_before_build")
        linked = work / "linked"
        linked.symlink_to(existing, target_is_directory=True)
        rejection(lambda: builder.build(linked), "Symlink path component")
        results.append("symlink_output_parent_refused")
        dangling = work / "dangling"
        dangling.mkdir()
        (dangling / "rootfs.img").symlink_to(work / "missing")
        rejection(lambda: builder.build(dangling), "Refusing existing output")
        results.append("dangling_image_symlink_refused")
        ordinary = work / "ordinary"
        ordinary.write_bytes(b"plain")
        input_link = work / "input-link"
        input_link.symlink_to(ordinary)
        rejection(lambda: builder.bounded_path(input_link, HERE, regular=True), "Symlink path component")
        results.append("symlink_input_refused")
        rejection(lambda: builder.bounded_path(work, HERE, regular=True), "not an ordinary file")
        results.append("directory_input_refused")
        busybox = builder.read_input(builder.BINARIES["bin/busybox"][0])[1]
        dynamic = bytearray(busybox)
        phoff = struct.unpack_from("<Q", dynamic, 32)[0]
        struct.pack_into("<I", dynamic, phoff, 3)
        rejection(lambda: builder.check_elf(dynamic), "Dynamic ELF interpreter")
        results.append("actual_elf_interpreter_mutation_refused")
        dependency = bytearray(busybox)
        struct.pack_into("<I", dependency, phoff, 2)
        struct.pack_into("<Q", dependency, phoff + 8, len(dependency))
        struct.pack_into("<Q", dependency, phoff + 32, 16)
        dependency.extend(struct.pack("<qQ", 1, 0))
        rejection(lambda: builder.check_elf(dependency), "DT_NEEDED dependency")
        results.append("actual_elf_needed_mutation_refused")
        wrong_arch = bytearray(busybox)
        struct.pack_into("<H", wrong_arch, 18, 62)
        rejection(lambda: builder.check_elf(wrong_arch), "Expected AArch64")
        results.append("wrong_elf_architecture_refused")
        module_path = next(name for name in builder.BINARIES if name.endswith(".ko"))
        module = builder.read_input(builder.BINARIES[module_path][0])[1]
        wrong_module = module.replace(builder.RELEASE.encode(), b"X" * len(builder.RELEASE))
        rejection(lambda: builder.check_elf(wrong_module, module=True), "does not match tested kernel")
        results.append("wrong_module_vermagic_refused")
        tamper_case(HERE, work / "owner", ["set_inode_field /usr/bin/wpa_cli uid 1000"], "Non-root inode ownership")
        results.append("actual_nonroot_inode_refused")
        tamper_case(HERE, work / "mode", ["set_inode_field /usr/bin/wpa_cli mode 0100644"], "Wrong inode type/mode")
        results.append("actual_wrong_executable_mode_refused")
        payload = work / "corrupt"
        payload.write_bytes(b"wrong source binary")
        tamper_case(HERE, work / "payload", ["rm /usr/bin/wpa_cli", "write " + str(payload) + " /usr/bin/wpa_cli",
                    "set_inode_field /usr/bin/wpa_cli mode 0100755"], "Image payload differs")
        results.append("actual_payload_tampering_refused")
        tamper_case(HERE, work / "credentials", ["write " + str(payload) + " /tmp/wpa.conf"], "path inventory differs")
        results.append("actual_persisted_credential_path_refused")
        tamper_case(HERE, work / "resolver", ["rm /etc/resolv.conf", "symlink /etc/resolv.conf /etc/persistent-dns"], "Symlink target differs")
        results.append("actual_nonram_resolver_link_refused")
        tamper_case(HERE, work / "logs", ["rm /var/log", "symlink /var/log /var/lib/log"], "Symlink target differs")
        results.append("actual_nonram_log_link_refused")
        tamper_case(HERE, work / "init", ["write " + str(payload) + " /init"], "path inventory differs")
        results.append("actual_unplanned_init_refused")
        tamper_case(HERE, work / "module", ["rm /lib/modules/" + builder.RELEASE + "/bcmdhd.ko",
                    "write " + str(payload) + " /lib/modules/" + builder.RELEASE + "/bcmdhd.ko"], "Image payload differs")
        results.append("actual_wrong_module_payload_refused")
        image = work / "byte-flip"
        image.mkdir()
        (image / "build").mkdir()
        shutil.copyfile(HERE / "rootfs.img", image / "rootfs.img")
        shutil.copyfile(HERE / "rootfs-manifest.json", image / "rootfs-manifest.json")
        with (image / "rootfs.img").open("r+b") as stream:
            stream.seek(8192)
            stream.write(b"tamper")
        rejection(lambda: verifier.verify(image, execute=False), "Image checksum differs")
        results.append("actual_image_outer_sha_tampering_refused")
    assert builder.sha((HERE / "rootfs.img").read_bytes()) == original_sha
    summary = {"status": "ROOTFS_HOST_TESTS_PASSED", "checks": len(results),
               "passed": results, "primary_image_unchanged": True, "board_tested": False}
    (HERE / "build/test-result.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
