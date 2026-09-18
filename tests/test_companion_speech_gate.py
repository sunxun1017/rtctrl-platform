import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from apps.companion.speech_gate import SpeechGate

class GateTests(unittest.TestCase):
    def test_silence_dc_and_short_click_do_not_trigger(self):
        gate=SpeechGate()
        for frame in [bytes(1920)]*100+[b"\x20\x03"*960]*10+[b"\x64\x00\x9c\xff"*480]+[bytes(1920)]*10:
            self.assertIsNone(gate.feed(frame))
        self.assertLessEqual(len(gate.history),8)
    def test_onset_includes_bounded_preroll(self):
        gate=SpeechGate()
        quiet=bytes(1920);voice=b"\x64\x00\x9c\xff"*480
        for _ in range(20):gate.feed(quiet)
        self.assertIsNone(gate.feed(voice));self.assertIsNone(gate.feed(voice))
        self.assertEqual(gate.feed(voice),[quiet]*5+[voice]*3)
    def test_low_level_noise_does_not_trigger(self):
        gate=SpeechGate()
        for _ in range(1000):self.assertIsNone(gate.feed(b"\x0a\x00\xf6\xff"*480))

if __name__=='__main__': unittest.main()
