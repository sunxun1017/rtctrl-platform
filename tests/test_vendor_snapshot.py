#!/usr/bin/env python3
"""Regression: SDK changes and patches must describe the actual copied input."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("rkaiq_build", Path(__file__).resolve().parents[1] / "scripts/build-ov13850-rkaiq-debug.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SnapshotTest(unittest.TestCase):
    def test_fresh_snapshot_and_patch_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, patches = root / "sdk", root / "patches"
            source.mkdir(); patches.mkdir()
            (source / "value").write_text("old\n")
            (patches / "series").write_text("fix.patch\n")
            (patches / "fix.patch").write_text("--- a/value\n+++ b/value\n@@ -1 +1 @@\n-old\n+fixed\n")
            first = module.prepare_source(source, root / "first", patches)
            self.assertEqual((root / "first/value").read_text(), "fixed\n")
            self.assertEqual((source / "value").read_text(), "old\n")
            self.assertEqual(first["patched_source_sha256"], module.tree_sha256(root / "first"))
            (source / "new-input").write_text("new SDK input\n")
            second = module.prepare_source(source, root / "second", patches)
            self.assertNotEqual(first["patched_source_sha256"], second["patched_source_sha256"])
            self.assertFalse((root / "first/new-input").exists())
            self.assertEqual(first["patches"], second["patches"])

    def test_wrong_patch_base_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "sdk").mkdir(); (root / "patches").mkdir()
            (root / "sdk/value").write_text("incompatible\n")
            (root / "patches/series").write_text("fix.patch\n")
            (root / "patches/fix.patch").write_text("--- a/value\n+++ b/value\n@@ -1 +1 @@\n-old\n+fixed\n")
            with self.assertRaises(module.subprocess.CalledProcessError):
                module.prepare_source(root / "sdk", root / "snapshot", root / "patches")


if __name__ == "__main__":
    unittest.main()
