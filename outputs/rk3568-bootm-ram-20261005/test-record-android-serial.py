#!/usr/bin/env python3
"""Exercise the observed CR parsing fault and missing/changed UART results."""
import importlib.util
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('recorder', HERE / 'record-android-serial.py')
recorder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recorder)


class RecordedUART(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (HERE.parent / 'rk3568-pid1-20261005/private/'
                   'android-baseline-after-linux-bootm-v2.raw.txt').read_bytes()
        cls.steps = json.loads((HERE / 'android-baseline-after-v2-serial.json').read_text())

    def collect(self, raw):
        return recorder.collect(raw, self.steps, 'test-only')

    def test_complete_actual_capture(self):
        self.assertTrue(self.collect(self.raw)['success'])

    def test_lone_cr_does_not_create_result(self):
        self.assertTrue(self.collect(self.raw + b'noise\r1\r\n')['success'])

    def test_duplicate_result_rejected(self):
        with self.assertRaises(ValueError):
            self.collect(self.raw + b'\r\n1\r\n')

    def test_missing_sha_rejected(self):
        with self.assertRaises(ValueError):
            self.collect(self.raw.replace(b'0db7ae12eebf0f3819e5fb72d9291abb4', b''))

    def test_changed_sha_rejected(self):
        with self.assertRaises(ValueError):
            self.collect(self.raw.replace(b'0db7ae12eebf0f3819e5fb72d9291abb4',
                                          b'1db7ae12eebf0f3819e5fb72d9291abb4'))

    def test_duplicate_battery_rejected(self):
        with self.assertRaises(ValueError):
            self.collect(self.raw + b'\r\n  level: 62\r\n')

    def test_non_ascii_rejected(self):
        with self.assertRaises(UnicodeDecodeError):
            self.collect(self.raw + b'\xff')


if __name__ == '__main__':
    unittest.main()
