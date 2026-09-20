#!/usr/bin/env python3
"""Guard the candidate kernel configuration and out-of-tree build boundary."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/prepare-linux-config.py"
spec = importlib.util.spec_from_file_location("linux_kernel", SCRIPT)
kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)


class ConfigAuditTests(unittest.TestCase):
    def test_dependency_dropping_driver_is_reported(self):
        errors = kernel.audit_config("CONFIG_USB=y\nCONFIG_SND_USB_AUDIO=m\n",
                                     "CONFIG_USB=y\n# CONFIG_SND_USB_AUDIO is not set\n")
        self.assertEqual(errors, ["CONFIG_SND_USB_AUDIO: requested m, resolved n"])

    def test_missing_unknown_symbol_is_not_a_pass(self):
        self.assertEqual(kernel.audit_config("CONFIG_TYPO_DRIVER=y\n", ""),
                         ["CONFIG_TYPO_DRIVER: requested y, resolved n"])

    def test_module_and_builtin_are_distinct(self):
        self.assertTrue(kernel.audit_config("CONFIG_USB=m\n", "CONFIG_USB=y\n"))

    def test_disabled_symbol_may_be_omitted_by_kconfig(self):
        self.assertEqual(kernel.audit_config("# CONFIG_UNUSED is not set\n", ""), [])

    def test_comments_strings_and_exact_keys(self):
        fragment = '# Explanation\nCONFIG_A=y\nCONFIG_AB=m\nCONFIG_NAME="patch"\n'
        self.assertEqual(kernel.audit_config(fragment, fragment), [])
        self.assertTrue(kernel.audit_config(fragment, 'CONFIG_AB=y\nCONFIG_NAME="patch"\n'))

    def test_conflicting_requests_rejected(self):
        with self.assertRaises(ValueError):
            kernel.audit_config("CONFIG_A=y\nCONFIG_A=m\n", "CONFIG_A=m\n")

    def test_malformed_config_request_is_not_silently_ignored(self):
        with self.assertRaises(ValueError):
            kernel.audit_config("CONFIG_USB =y\n", "")


class OutputBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "linux"
        self.source.mkdir()

    def test_source_and_descendant_refused(self):
        for output in (self.source, self.source / "out"):
            with self.subTest(output=output), self.assertRaises(ValueError):
                kernel.validate_output(self.source, output)

    def test_existing_data_preserved(self):
        out = self.root / "out"
        out.mkdir()
        (out / "user-data").write_text("keep")
        with self.assertRaises(ValueError):
            kernel.validate_output(self.source, out)
        self.assertEqual((out / "user-data").read_text(), "keep")

    def test_symlink_into_source_refused(self):
        alias = self.root / "alias"
        alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError):
            kernel.validate_output(self.source, alias / "out")

    def test_new_external_output_accepted_without_creating_it(self):
        out = self.root / "output"
        self.assertEqual(kernel.validate_output(self.source, out), out)
        self.assertFalse(out.exists())

    def test_output_file_refused(self):
        out = self.root / "file"
        out.write_text("keep")
        with self.assertRaises(ValueError):
            kernel.validate_output(self.source, out)

    def test_kbuild_unsupported_whitespace_rejected_before_build(self):
        with self.assertRaises(ValueError):
            kernel.validate_output(self.source, self.root / "space path")

    def test_kbuild_shell_metacharacters_rejected_before_creating_output(self):
        for name in ("out;touch", "out`id`", "out$(id)", "out*", "out'", "out:colon"):
            output = self.root / name
            with self.subTest(name=name), self.assertRaises(ValueError):
                kernel.validate_output(self.source, output)
            self.assertFalse(output.exists())

    def test_kconfig_environment_cannot_redirect_generated_files(self):
        poisoned = {"PATH": "/usr/bin", "KCONFIG_AUTOHEADER": "/tmp/user-header",
                    "KCONFIG_AUTOCONFIG": "/tmp/user-config", "KBUILD_OUTPUT": "/tmp/other",
                    "KCONFIG_CONFIG": "/tmp/existing", "MAKEFLAGS": "-e",
                    "KCONFIG_FUTURE_OUTPUT": "/tmp/future"}
        with patch.dict(os.environ, poisoned, clear=True):
            clean = kernel.build_environment(self.root / "out")
            self.assertEqual(os.environ["KCONFIG_AUTOHEADER"], "/tmp/user-header")
        self.assertEqual(clean["KCONFIG_CONFIG"], str(self.root / "out/.config"))
        for key in poisoned:
            if key not in ("PATH", "KCONFIG_CONFIG"):
                self.assertNotIn(key, clean)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "candidate.json"
        self.candidate = dict(schema=1, board="fixture-board", soc="fixture-soc", arch="riscv",
                              source="linux", source_commit="a" * 40,
                              defconfig="fixture_defconfig", cross_compile="riscv64-linux-gnu-",
                              fragments=["soc.cfg", "board.cfg"])

    def load(self):
        self.path.write_text(json.dumps(self.candidate))
        return kernel.load_candidate(self.path, self.root)

    def test_another_architecture_is_configuration_data(self):
        self.assertEqual(self.load()["arch"], "riscv")

    def test_repository_path_escape_rejected(self):
        for value in ("../outside.cfg", "/tmp/outside.cfg"):
            self.candidate["fragments"] = [value]
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load()

    def test_missing_field_and_unknown_schema_rejected(self):
        self.candidate["schema"] = 2
        with self.assertRaises(ValueError):
            self.load()
        self.candidate["schema"] = 1
        del self.candidate["arch"]
        with self.assertRaises(ValueError):
            self.load()

    def test_empty_fragments_rejected(self):
        self.candidate["fragments"] = []
        with self.assertRaises(ValueError):
            self.load()

    def test_comment_only_fragment_cannot_claim_zero_setting_success(self):
        fragment = self.root / "empty.cfg"
        fragment.write_text("# comments only\n")
        with self.assertRaises(ValueError):
            kernel.requested_settings([fragment])

    def test_standard_defconfig_name_is_hardware_neutral(self):
        self.candidate["defconfig"] = "defconfig"
        self.assertEqual(self.load()["defconfig"], "defconfig")

    def test_board_overrides_common_fragment_in_declared_order(self):
        first, second = self.root / "soc.cfg", self.root / "board.cfg"
        first.write_text("CONFIG_USB=y\nCONFIG_SOUND=y\n")
        second.write_text("CONFIG_SOUND=m\n")
        self.assertEqual(kernel.requested_settings([first, second]),
                         {"CONFIG_USB": "y", "CONFIG_SOUND": "m"})


if __name__ == "__main__":
    unittest.main()
