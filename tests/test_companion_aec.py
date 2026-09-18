"""Software reference alignment tests; fake bridge only, no recordings."""
import audioop
import struct
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from apps.companion import aec

class Bridge:
    def __init__(self, config): self.calls=[]; self.closed=False
    def process(self, mic, reference):
        self.calls.append((mic,reference))
        return mic
    def close(self): self.closed=True

def pcm(value,count): return struct.pack('<h',value)*count

class EchoTests(unittest.TestCase):
    def setUp(self):
        self.patch=patch.object(aec,'NativeBridge',Bridge);self.patch.start()
        self.echo=aec.EchoCanceller({})
    def tearDown(self):self.echo.close();self.patch.stop()
    def test_timestamped_reference_not_immediate_queue(self):
        self.echo.render(pcm(7,512),16000,submitted_at=10)
        out=self.echo.process(pcm(3,256),captured_at=10)
        self.assertEqual(out,pcm(0,256))
        self.assertEqual(self.echo.native.calls[-1][1],pcm(0,256))
        out=self.echo.process(pcm(4,256),captured_at=10+.016)
        self.assertEqual(out,pcm(3,256))
        self.assertEqual(self.echo.native.calls[-1][1],pcm(7,256))
    def test_configured_delay(self):
        self.echo.close();self.echo=aec.EchoCanceller({'aec_reference_delay_ms':100})
        self.echo.render(pcm(7,256),16000,submitted_at=10)
        self.echo.process(pcm(2,256),captured_at=10.116)
        self.assertEqual(self.echo.native.calls[-1][1],pcm(7,256))
    def test_chunked_resampling_and_odd_playback_writes(self):
        data=b''.join(struct.pack('<h',i%1000) for i in range(4410))
        for offset in range(0,len(data),137):
            self.echo.render(data[offset:offset+137],44100,submitted_at=10)
        actual=b''.join(x[1] for x in self.echo.reference)
        expected,_=audioop.ratecv(data,2,1,44100,16000,None)
        self.assertEqual(actual,expected)
        self.assertEqual(self.echo.render_pending_byte,b'')
    def test_process_preserves_bytes_with_fixed_256_sample_delay(self):
        source=pcm(3,960)+pcm(4,960)+pcm(5,960)
        outputs=[]
        for i in range(3):
            outputs.append(self.echo.process(source[i*1920:(i+1)*1920],captured_at=1+(i+1)*.06))
        self.assertEqual([len(x) for x in outputs],[1920]*3)
        self.assertEqual(b''.join(outputs),pcm(0,256)+source[:-512])
        self.assertEqual(self.echo.stats['missing_reference_samples'],2880)
    def test_interruption_keeps_past_discards_future_without_resetting_native(self):
        self.echo.render(pcm(9,512),16000,submitted_at=10)
        bridge=self.echo.native
        self.echo.reset_reference(interrupted_at=10.016)
        self.assertIs(self.echo.native,bridge)
        self.assertEqual(b''.join(data for _,data in self.echo.reference),pcm(9,256))
        self.echo.process(pcm(2,256),captured_at=10.016)
        self.assertEqual(bridge.calls[-1][1],pcm(9,256))
        self.echo.process(pcm(2,256),captured_at=10.032)
        self.assertEqual(bridge.calls[-1][1],pcm(0,256))
    def test_reference_future_and_storage_bounded(self):
        with self.assertRaises(ValueError):self.echo.render(pcm(1,16000*6),16000,submitted_at=0)
        self.echo.render(pcm(1,16000*4),16000,submitted_at=1)
        with self.assertRaises(ValueError):self.echo.render(pcm(1,16000*2),16000,submitted_at=1)
        self.assertLessEqual(sum(len(x[1]) for x in self.echo.reference),16000*2*5)
    def test_capture_sample_clock_ignores_read_jitter(self):
        self.echo.render(pcm(1,256)+pcm(2,256)+pcm(3,256),16000,submitted_at=10)
        for end in (10.016,10.035,10.043):
            self.echo.process(pcm(9,256),captured_at=end)
        self.assertEqual([call[1] for call in self.echo.native.calls], [pcm(1,256),pcm(2,256),pcm(3,256)])
        self.assertEqual(self.echo.stats['capture_discontinuities'],0)
    def test_capture_discontinuity_reanchors_and_flushes_subframe(self):
        self.echo.process(pcm(7,100),captured_at=10)
        out=self.echo.process(pcm(8,256),captured_at=11)
        self.assertEqual(out,pcm(0,256))
        self.assertEqual(self.echo.native.calls[-1][0],pcm(8,256))
        self.assertEqual(self.echo.stats['capture_discontinuities'],1)
    def test_render_submission_jitter_keeps_contiguous_samples(self):
        self.echo.render(pcm(1,256),16000,submitted_at=10)
        self.echo.render(pcm(2,256),16000,submitted_at=10.019)
        self.assertEqual([start for start,_ in self.echo.reference],[160000,160256])

    def test_native_error_closes_fail_closed(self):
        with patch.object(self.echo.native,'process',side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):self.echo.process(pcm(0,256),captured_at=1)
        self.assertTrue(self.echo.closed)
        with self.assertRaises(RuntimeError):self.echo.process(pcm(0,256),captured_at=1)
    def test_bad_input(self):
        for data in (b'x','not bytes'):
            with self.assertRaises(ValueError):self.echo.process(data)
        with self.assertRaises(ValueError):self.echo.render(b'xx',1234)
        self.echo.close()
        with self.assertRaises(RuntimeError):self.echo.render(b'xx',16000)

if __name__=='__main__':unittest.main()
