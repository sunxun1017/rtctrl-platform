#!/usr/bin/env python3
"""Exercise the collector against offline fixtures without opening hardware."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/collect-linux-hardware.sh"
SHELL = shutil.which("sh")


class HardwareSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hardware snapshot ")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "target root"
        self.root.mkdir()
        self.output = self.base / "saved hardware"

    def write(self, path, data=b"fixture\n"):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def complete_fixture(self):
        self.write("sys/firmware/fdt", b"\xd0\x0d\xfe\xed\x00binary\xff\x00")
        self.write("sys/firmware/devicetree/base/compatible", b"example,board\x00example,soc\x00")
        self.write("sys/firmware/devicetree/base/audio@ff000000/bytes", b"\x00\xff\x10\x00")
        for name in ("version", "asound/cards", "asound/pcm", "bus/input/devices"):
            self.write("proc/" + name, ("target " + name + "\n").encode())
        self.write("proc/config.gz", b"\x1f\x8b\x00config fixture")
        usb = self.root / "sys/bus/usb/devices/1-1"
        usb.parent.mkdir(parents=True)
        target = self.root / "sys/devices/platform/usb/1-1"
        target.mkdir(parents=True)
        usb.symlink_to("../../../devices/platform/usb/1-1")
        for name, value in (("idVendor", "1234"), ("idProduct", "5678"),
                            ("bDeviceClass", "00"), ("product", "Fixture USB")):
            (target / name).write_text(value + "\n")
        (target / "serial").write_text("DO NOT COPY USB SERIAL\n")
        for bus, device in (("i2c", "1-001a"), ("spi", "spi0.0")):
            self.write(f"sys/bus/{bus}/devices/{device}/modalias", f"{bus}:fixture\n".encode())
            driver = self.root / f"sys/bus/{bus}/devices/{device}/driver"
            driver.symlink_to("../../drivers/fixture")

    def run_collector(self, *arguments, timeout=10, env=None):
        args = list(arguments) or ["--root", str(self.root), str(self.output)]
        return subprocess.run([SHELL, str(SCRIPT), *args], text=True, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout)

    def statuses(self):
        return (self.output / "status.tsv").read_text()

    def command_path(self):
        directory = self.base / "commands"
        directory.mkdir()
        for command in ("cat", "mkdir", "readlink", "rm", "uname"):
            (directory / command).symlink_to(shutil.which(command))
        return directory

    def test_summary_command_failure_does_not_report_complete(self):
        self.complete_fixture()
        commands = self.command_path()
        grep = commands / "grep"
        grep.write_text("#!/bin/sh\nexit 2\n")
        grep.chmod(0o700)
        result = self.run_collector(env={**os.environ, "PATH": str(commands)})
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertNotIn("All requested metadata", result.stdout)

    def test_missing_summary_command_does_not_report_complete(self):
        self.complete_fixture()
        commands = self.command_path()
        result = self.run_collector(env={**os.environ, "PATH": str(commands)})
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertNotIn("All requested metadata", result.stdout)

    def test_status_append_failure_stops_each_subshell_layer(self):
        self.complete_fixture()
        commands = self.command_path()
        (commands / "grep").symlink_to(shutil.which("grep"))
        (commands / "cat").unlink()
        # The real copy finishes; replacing status.tsv with a directory makes
        # its next append fail regardless of uid, without filling the disk.
        (commands / "cat").write_text(
            f"#!{sys.executable}\n"
            "import os, pathlib, subprocess, sys\n"
            f"result = subprocess.run([{shutil.which('cat')!r}, *sys.argv[1:]])\n"
            "if sys.argv[1] == os.environ['FAIL_AFTER_READ']:\n"
            "    status = pathlib.Path(os.environ['SNAPSHOT_OUTPUT']) / 'status.tsv'\n"
            "    status.rename(status.with_name('status.before-failure.tsv'))\n"
            "    status.mkdir()\n"
            "sys.exit(result.returncode)\n"
        )
        (commands / "cat").chmod(0o700)
        cases = (
            ("sys/firmware/fdt", "config.gz"),
            ("sys/firmware/devicetree/base/audio@ff000000/bytes", "devicetree/compatible"),
            ("sys/devices/platform/usb/1-1/idVendor", "usb/1-1/idProduct"),
        )
        for index, (trigger, later_output) in enumerate(cases):
            with self.subTest(layer=trigger):
                self.output = self.base / f"failed snapshot {index}"
                result = self.run_collector(env={
                    **os.environ, "PATH": str(commands),
                    "FAIL_AFTER_READ": str(self.root / trigger),
                    "SNAPSHOT_OUTPUT": str(self.output),
                })
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertNotIn("All requested metadata", result.stdout)
                self.assertFalse((self.output / later_output).exists())

    def test_copies_binary_and_whitelisted_metadata_without_changing_source(self):
        self.complete_fixture()
        before = {p.relative_to(self.root): p.read_bytes()
                  for p in self.root.rglob("*") if p.is_file() and not p.is_symlink()}
        result = self.run_collector()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual((self.output / "fdt.dtb").read_bytes(), b"\xd0\x0d\xfe\xed\x00binary\xff\x00")
        self.assertEqual((self.output / "devicetree/audio@ff000000/bytes").read_bytes(), b"\x00\xff\x10\x00")
        self.assertEqual((self.output / "usb/1-1/idVendor").read_text(), "1234\n")
        self.assertEqual((self.output / "i2c/1-001a/driver").read_text(), "../../drivers/fixture\n")
        self.assertEqual((self.output / "spi/spi0.0/modalias").read_text(), "spi:fixture\n")
        self.assertFalse((self.output / "uname.txt").exists())
        self.assertIn("offline", self.statuses())
        for p in self.output.rglob("*"):
            if p.is_file():
                self.assertNotIn(b"DO NOT COPY USB SERIAL", p.read_bytes())
        after = {p.relative_to(self.root): p.read_bytes()
                 for p in self.root.rglob("*") if p.is_file() and not p.is_symlink()}
        self.assertEqual(before, after)
        self.assertFalse((self.root / "dev").exists())
        self.assertFalse((self.output / "dev").exists())
        self.assertIn("locally", result.stdout)

    def test_missing_device_tree_and_optional_files_are_reported(self):
        result = self.run_collector()
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn("missing\t/sys/firmware/fdt", self.statuses())
        self.assertIn("missing\tdevice-tree", self.statuses())
        self.assertIn("missing\t/proc/config.gz", self.statuses())
        self.assertFalse((self.root / "dev").exists())

    def test_proc_device_tree_fallback_preserves_binary_files(self):
        self.write("proc/device-tree/compatible", b"example,soc\x00")
        result = self.run_collector()
        self.assertEqual(result.returncode, 1)
        self.assertEqual((self.output / "devicetree/compatible").read_bytes(), b"example,soc\x00")

    def test_nonempty_output_is_untouched_including_hidden_files(self):
        self.output.mkdir()
        sentinel = self.output / ".keep"
        sentinel.write_text("untouched")
        result = self.run_collector()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(list(self.output.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_text(), "untouched")

    def test_existing_empty_output_is_allowed(self):
        self.output.mkdir()
        result = self.run_collector()
        self.assertEqual(result.returncode, 1)
        self.assertTrue((self.output / "status.tsv").is_file())

    def test_empty_arguments_do_not_create_output(self):
        for args in (("--root", "", str(self.output)),
                     ("--root", str(self.root), ""), ("--root",), ()):
            with self.subTest(args=args):
                result = subprocess.run(["sh", str(SCRIPT), *args], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
        self.assertFalse(self.output.exists())

    def test_tree_symlinks_and_special_files_are_not_followed_or_copied(self):
        self.complete_fixture()
        tree = self.root / "sys/firmware/devicetree/base"
        secret = self.base / "outside-private-data"
        secret.write_text("DO NOT FOLLOW LINK")
        (tree / "escape").symlink_to(secret)
        (tree / "device").symlink_to("/dev/zero")
        (tree / "internal-link").symlink_to("compatible")
        os.mkfifo(tree / "pipe")
        result = self.run_collector(timeout=5)
        self.assertEqual(result.returncode, 1)
        for name in ("escape", "device", "internal-link", "pipe"):
            self.assertFalse(os.path.lexists(self.output / "devicetree" / name))
            self.assertIn(name, self.statuses())
        for p in self.output.rglob("*"):
            if p.is_file():
                self.assertNotIn(b"DO NOT FOLLOW LINK", p.read_bytes())

    def test_source_links_cannot_escape_root_or_reach_device_files(self):
        self.complete_fixture()
        fdt = self.root / "sys/firmware/fdt"
        fdt.unlink()
        fdt.symlink_to("/dev/zero")
        version = self.root / "proc/version"
        version.unlink()
        version.symlink_to("/proc/version")
        usb = self.root / "sys/devices/platform/usb/1-1/idVendor"
        usb.unlink()
        usb.symlink_to("/dev/zero")
        result = self.run_collector(timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.output / "fdt.dtb").exists())
        self.assertFalse((self.output / "proc/version").exists())
        self.assertFalse((self.output / "usb/1-1/idVendor").exists())
        self.assertIn("unsafe", self.statuses())

    def test_output_symlink_is_rejected(self):
        destination = self.base / "unrelated"
        destination.mkdir()
        self.output.symlink_to(destination, target_is_directory=True)
        result = self.run_collector()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(list(destination.iterdir()), [])

    def test_output_cannot_be_created_inside_source_dev(self):
        result = self.run_collector("--root", str(self.root), str(self.root / "dev"))
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / "dev").exists())

    def test_ancestor_symlinks_cannot_escape_source_metadata_trees(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "fdt").write_bytes(b"PRIVATE")
        (self.root / "sys").mkdir()
        (self.root / "sys/firmware").symlink_to(outside, target_is_directory=True)
        result = self.run_collector()
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.output / "fdt.dtb").exists())
        self.assertIn("unsafe\t/sys/firmware/fdt", self.statuses())

    def test_control_characters_in_tree_names_cannot_corrupt_status_rows(self):
        self.complete_fixture()
        tree = self.root / "sys/firmware/devicetree/base"
        for name in ("bad\tname", "bad\nname"):
            (tree / name).write_bytes(b"not copied")
        result = self.run_collector()
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.output / "devicetree/bad\tname").exists())
        self.assertFalse((self.output / "devicetree/bad\nname").exists())
        self.assertTrue(all(len(line.split("\t")) == 4 for line in self.statuses().splitlines()))

    @unittest.skipUnless(shutil.which("strace"), "strace unavailable")
    def test_never_opens_a_device_node(self):
        self.complete_fixture()
        (self.root / "sys/firmware/devicetree/base/device").symlink_to("/dev/zero")
        trace = self.base / "opened-files.log"
        result = subprocess.run(["strace", "-f", "-e", "trace=open,openat,creat", "-o", str(trace),
                                 "sh", str(SCRIPT), "--root", str(self.root), str(self.output)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn('"/dev/', trace.read_text())
        self.assertNotIn(str(self.root / "dev"), trace.read_text())

    @unittest.skipIf(os.geteuid() == 0, "permission denial requires an unprivileged user")
    def test_permission_failure_is_visible_and_partial_file_removed(self):
        self.complete_fixture()
        version = self.root / "proc/version"
        version.chmod(0)
        self.addCleanup(version.chmod, 0o600)
        result = self.run_collector()
        self.assertEqual(result.returncode, 1)
        self.assertIn("error\t/proc/version", self.statuses())
        self.assertFalse((self.output / "proc/version").exists())

    @unittest.skipIf(os.geteuid() == 0, "permission denial requires an unprivileged user")
    def test_unreadable_tree_directory_is_not_reported_complete(self):
        self.complete_fixture()
        tree = self.root / "sys/firmware/devicetree/base"
        tree.chmod(0)
        self.addCleanup(tree.chmod, 0o700)
        result = self.run_collector()
        self.assertEqual(result.returncode, 1)
        self.assertIn("error\t/sys/firmware/devicetree/base", self.statuses())


if __name__ == "__main__":
    unittest.main()
