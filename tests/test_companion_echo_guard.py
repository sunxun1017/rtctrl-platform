"""Synthetic text only: lexical suspicion is not proof of acoustic echo."""
import sys
import time
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.companion.echo_guard import EchoGuard


class EchoGuardTests(unittest.TestCase):
    def setUp(self):
        self.guard = EchoGuard()
        self.guard.remember("你好！今天我们一起学习如何照顾花园里的植物。", 10)

    def test_exact_subsentence_and_punctuation(self):
        for text in ("你好", "今天我们一起学习", "花园里的植物", "今天，我们一起学习！"):
            self.assertTrue(self.guard.suspected(text, 11), text)
        self.guard.remember("Welcome to the GARDEN!", 11)
        self.assertTrue(self.guard.suspected("welcome，TO the garden", 12))

    def test_one_and_two_asr_edits(self):
        for text in ("今天我们一学习", "今天我们一起学西", "今天我们一学习如何照花园里的植物"):
            self.assertTrue(self.guard.suspected(text, 11), text)

    def test_unrelated_and_short_fuzzy_rejected(self):
        for text in ("帮我查询明天的火车时刻", "你好啊", "海洋", "", "！！！"):
            self.assertFalse(self.guard.suspected(text, 11), text)

    def test_expiry_clear_and_capacity(self):
        self.assertTrue(self.guard.suspected("你好", 45))
        self.assertFalse(self.guard.suspected("你好", 45.01))
        for i in range(4):
            self.guard.remember(str(i) * 5000, 50)
        self.assertEqual(len(self.guard._recent), 3)
        self.assertLessEqual(sum(len(t) for _, t in self.guard._recent), 6144)
        self.assertFalse(self.guard.suspected("000", 51))
        self.assertTrue(self.guard.suspected("333", 51))
        self.guard.clear()
        self.assertFalse(self.guard.suspected("333", 51))

    def test_refresh_deduplicates_and_retains_other_references(self):
        self.guard.remember("另一段合成文字", 11)
        self.guard.remember("你好，今天我们一起学习如何照顾花园里的植物！", 40)
        self.assertEqual(len(self.guard._recent), 2)
        self.assertTrue(self.guard.suspected("另一段合成文字", 41))
        self.assertTrue(self.guard.suspected("你好", 60))

    def test_oversized_candidate_and_bounded_worst_case(self):
        for _ in range(3):
            self.guard.remember("花" * 2048, 20)
        self.assertFalse(self.guard.suspected("草" * 513, 21))
        before = time.monotonic()
        self.assertFalse(self.guard.suspected("草" * 512, 21))
        # A generous host regression ceiling; no claim about board latency.
        self.assertLess(time.monotonic() - before, 5)


if __name__ == "__main__":
    unittest.main()
