#!/usr/bin/env python3
"""Finite actual-input drift tests for the next offline package's new gates."""
import copy
import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('offline_next_tests', HERE / 'offline-next.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class Inputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root_build = tool.ROOT / 'outputs/rk3568-audio-runtime-20261005/build/root-audio-integration-v5'
        cls.build_bytes = tool.read(root_build / 'full-build-v1/receipt.json')
        cls.build = tool.unique_json(cls.build_bytes)
        cls.codec = tool.unique_json(tool.read(root_build / 'canonical-codec-v1/receipt.json'))
        cls.image = tool.read(tool.ROOT / cls.codec['Image']['path'])
        cls.module = tool.read(root_build / 'canonical-codec-v1/modules/snd-soc-rk817.ko')
        cls.notes = tool.read(root_build / 'canonical-codec-v1/kernel.notes')

    def validate(self, build=None, codec=None, image=None, module=None, notes=None):
        self.assertTrue(hasattr(tool, 'validate_new_records'), 'New actual Image/codec binding gate is absent')
        return tool.validate_new_records(build or self.build, codec or self.codec,
            self.image if image is None else image, self.module if module is None else module,
            self.notes if notes is None else notes, tool.metadata(self.build_bytes)['sha256'])

    def test_actual_image_and_canonical_module(self):
        self.validate()

    def test_incomplete_image_build_rejected(self):
        record = copy.deepcopy(self.build)
        record['Image_and_modules_built'] = False
        with self.assertRaises(ValueError):
            self.validate(build=record)

    def test_failed_actual_compile_rejected(self):
        record = copy.deepcopy(self.build)
        record['steps'][0]['exit'] = 2
        with self.assertRaises(ValueError):
            self.validate(build=record)

    def test_drifted_image_rejected(self):
        data = self.image[:-1] + bytes([self.image[-1] ^ 1])
        with self.assertRaises(ValueError):
            self.validate(image=data)

    def test_drifted_module_rejected(self):
        data = self.module[:-1] + bytes([self.module[-1] ^ 1])
        with self.assertRaises(ValueError):
            self.validate(module=data)

    def test_old_intermediate_internal_name_rejected(self):
        record = copy.deepcopy(self.codec)
        record['module_internal_name'] = 'rk817_codec'
        with self.assertRaises(ValueError):
            self.validate(codec=record)

    def test_unclosed_imports_rejected(self):
        record = copy.deepcopy(self.codec)
        record['module']['imports_resolved'] = False
        with self.assertRaises(ValueError):
            self.validate(codec=record)

    def test_drifted_notes_rejected(self):
        data = self.notes[:-1] + bytes([self.notes[-1] ^ 1])
        with self.assertRaises(ValueError):
            self.validate(notes=data)

    def test_wrong_image_receipt_binding_rejected(self):
        record = copy.deepcopy(self.codec)
        record['Image_receipt_sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.validate(codec=record)


if __name__ == '__main__':
    unittest.main(verbosity=2)
