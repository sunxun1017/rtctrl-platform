#!/usr/bin/env python3
"""Fault-injection checks for the safety-relevant DTB audit, using a real DTB."""
import importlib.util
from pathlib import Path
import struct
import sys
import unittest

spec = importlib.util.spec_from_file_location('audit', Path(__file__).with_name('verify-firstboot.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
properties, reservations = module.read_dtb(Path(sys.argv.pop(1)))


class AuditFaults(unittest.TestCase):
    def reject(self, path, value, message):
        changed = dict(properties)
        changed[path] = value
        with self.assertRaisesRegex(ValueError, message):
            module.audit(changed, reservations)

    def test_real_compiled_candidate(self):
        self.assertFalse(module.audit(properties, reservations)['deployable'])

    def test_wrong_io_voltage_domain(self):
        prefix = '/syscon@fdc20000/io-domains/'
        self.reject(prefix+'vccio4-supply', properties[prefix+'vccio5-supply'], 'vccio4 supply mapping')

    def test_wrong_regulator_voltage(self):
        self.reject('/i2c@fdd40000/pmic@20/regulators/LDO_REG4/regulator-min-microvolt',
                    struct.pack('>I', 3000000), '3.1V codec IO supply')

    def test_emmc_high_speed_regression(self):
        self.reject('/sdhci@fe310000/max-frequency', struct.pack('>I', 200000000), '52MHz eMMC')

    def test_camera_probe_regression(self):
        self.reject('/mipi-csi2-hw@fdfb0000/status', b'okay\0', 'disabled')

    def test_actuator_uart_regression(self):
        self.reject('/serial@fdd50000/status', b'okay\0', 'disabled')

    def test_android_partition_bootargs(self):
        self.reject('/chosen/bootargs', b'rdinit=/init root=/dev/mmcblk0p15\0', 'initramfs only')

    def test_missing_memory_reservations(self):
        with self.assertRaisesRegex(ValueError, 'FDT reservations'):
            module.audit(properties, [])

    def test_high_remap_without_no_map(self):
        changed = dict(properties)
        changed.pop('/reserved-memory/buffer@1f0000000/no-map', None)
        with self.assertRaisesRegex(ValueError, 'high remap no-map'):
            module.audit(changed, reservations)

    def test_high_remap_wrong_size(self):
        self.reject('/reserved-memory/buffer@1f0000000/reg',
                    struct.pack('>4I', 1, 0xf0000000, 0, 0x08000000), 'high remap reservation')

    def test_loader_logo_not_reserved(self):
        self.reject('/reserved-memory/drm-logo@00000000/reg', bytes(16), 'loader logo reservation')

    def test_loader_lut_not_reserved(self):
        self.reject('/reserved-memory/drm-cubic-lut@00000000/reg', bytes(16), 'loader LUT reservation')


if __name__ == '__main__':
    unittest.main()
