#!/usr/bin/env python3
"""Actual offline format/DT negative cases, with no device operations."""
import copy
import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('offline_format_tests', HERE / 'offline-next.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class Format(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules, unused = tool.dependencies()
        cls.package = HERE / 'package-v1'
        cls.padded = tool.read(cls.package / 'boot-padded.img')
        cls.payloads = {name: tool.read(cls.package / 'components' / name)
                        for name in ('kernel', 'ramdisk', 'second', 'dtb')}
        cls.original = cls.modules['audit-boot.py'].inspect_boot(tool.locked(*tool.FIXED['original_boot']))
        cls.manifest = tool.unique_json(tool.read(cls.package / 'manifest.json'))
        cls.dt_report = cls.manifest['complete_DT']
        cls.before = tool.locked(*tool.FIXED['prior_shim'])
        cls.overlay = tool.locked(*tool.FIXED['original_dtbo'])
        cls.tree = cls.modules['dt-semantics-v2.py'].parse(cls.before)

    def inspect(self, blob):
        return tool.inspect_padded(blob, self.payloads, self.original, self.modules, self.dt_report)

    def test_actual_complete_package(self):
        self.assertEqual(self.inspect(self.padded)['raw_bytes'], 40482816)

    def test_nonzero_partition_padding_rejected(self):
        data = self.padded[:-1] + b'\x01'
        with self.assertRaises(ValueError):
            self.inspect(data)

    def test_truncated_complete_package_rejected(self):
        with self.assertRaises(ValueError):
            self.inspect(self.padded[:-1])

    def test_header_destination_drift_rejected(self):
        data = bytearray(self.padded)
        data[12] ^= 1
        with self.assertRaises(ValueError):
            self.inspect(bytes(data))

    def test_component_content_drift_rejected(self):
        data = bytearray(self.padded)
        data[2048 + 8192] ^= 1
        with self.assertRaises(ValueError):
            self.inspect(bytes(data))

    def test_overlapping_ram_spans_rejected(self):
        sizes = {n: len(b) for n, b in self.payloads.items()}
        sizes['ramdisk'] = 0x7000000
        with self.assertRaises(ValueError):
            tool.address_plan(self.payloads['kernel'], self.original['header'], sizes, 163344)

    def test_oversized_fdt_workspace_rejected(self):
        sizes = {n: len(b) for n, b in self.payloads.items()}
        sizes['dtb'] = 0x40001
        with self.assertRaises(ValueError):
            tool.address_plan(self.payloads['kernel'], self.original['header'], sizes, 163344)

    def test_incorrect_image_endian_flag_rejected(self):
        image = bytearray(self.payloads['kernel'])
        image[24] |= 1
        with self.assertRaises(ValueError):
            tool.address_plan(bytes(image), self.original['header'],
                {n: len(b) for n, b in self.payloads.items()}, 163344)

    def test_prior_shim_input_drift_rejected(self):
        data = self.before[:-1] + bytes([self.before[-1] ^ 1])
        with self.assertRaises(ValueError):
            tool.prepare_dt(data, self.overlay, self.modules)

    def test_original_overlay_drift_rejected(self):
        data = self.overlay[:-1] + b'\x01'
        with self.assertRaises(ValueError):
            tool.prepare_dt(self.before, data, self.modules)

    def test_trcm_profile_drift_rejected(self):
        tree = copy.deepcopy(self.tree)
        tree['properties'][tool.CPU + ':rockchip,clk-trcm'] = '00000002'
        with self.assertRaises(ValueError):
            tool.check_profile(tree)

    def test_calibration_profile_rejected(self):
        tree = copy.deepcopy(self.tree)
        tree['properties'][tool.CPU + ':rockchip,mclk-calibrate'] = ''
        with self.assertRaises(ValueError):
            tool.check_profile(tree)

    def test_codec_master_profile_rejected(self):
        tree = copy.deepcopy(self.tree)
        tree['properties'][tool.CARD + ':simple-audio-card,bitclock-master'] = '000002f9'
        with self.assertRaises(ValueError):
            tool.check_profile(tree)

    def test_duplicate_json_rejected(self):
        with self.assertRaises(ValueError):
            tool.unique_json(b'{"path":"a","path":"b"}')

    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):
            tool.relative('outputs/../elsewhere')


if __name__ == '__main__':
    unittest.main(verbosity=2)
