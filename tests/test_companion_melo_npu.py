"""Host contracts for Melo fixed-bucket decoder and complete-batch postprocessing."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.companion import melo_npu as m


def reference_scale(x, sr):
    # Independent transcription of sherpa v1.13.8 offline-tts.cc.
    intervals, last = [], -1
    threshold = int(sr * .2)
    for i, value in enumerate(x):
        if abs(float(value)) <= .01:
            if last == -1: last = i
            continue
        if last != -1 and i - last < threshold:
            last = -1
            continue
        if last != -1:
            intervals.append((last, i)); last = -1
    if last != -1 and len(x) - last > threshold:
        intervals.append((last, len(x)))
    out, cursor = [], 0
    for a, b in intervals:
        out.extend(x[cursor:a]); out.extend(x[a:a+int(np.float32(b-a)*np.float32(.2))]); cursor=b
    out.extend(x[cursor:])
    return np.asarray(out, np.float32)


class MeloTests(unittest.TestCase):
    def test_silence_boundary_matches_upstream(self):
        for sr in (8000,44100):
            for delta in (-1,0,1):
                for value in (0.,.01,np.nextafter(np.float32(.01),np.float32(1))):
                    quiet=np.full(int(sr*.2)+delta,value,np.float32)
                    voiced=np.array([.1,-.2],np.float32)
                    for x in (quiet,np.r_[quiet,voiced],np.r_[voiced,quiet],np.r_[voiced,quiet,voiced]):
                        np.testing.assert_array_equal(m.scale_silence(x,sr),reference_scale(x,sr))

    def test_chunk_halos_preserve_each_frame_exactly_once(self):
        for length in (1,16,223,224,225,240,256,448,449,4000):
            z=np.broadcast_to(np.arange(length,dtype=np.float32),(1,192,length))
            calls=[]
            def decoder(padded,count):
                self.assertEqual(padded.shape,(1,192,256))
                self.assertTrue(np.all(padded[:,:,count:]==0))
                calls.append(count)
                return np.repeat(padded[0,0],m.HOP)
            got=m.decode_chunks(z,decoder)
            np.testing.assert_array_equal(got,np.repeat(z[0,0],m.HOP))
            self.assertEqual(len(calls),(length+m.CORE-1)//m.CORE)

    def test_bad_latents_and_decoder_output(self):
        for z in (np.zeros((1,192,0)),np.zeros((1,192,4001)),np.zeros((192,3)),np.zeros((1,191,3)),np.full((1,192,3),np.nan)):
            with self.assertRaises(ValueError): m.decode_chunks(z,lambda *_:self.fail('decoder invoked'))
        for output in (np.zeros(10),np.full(m.BUCKET*m.HOP,np.nan),np.full(m.BUCKET*m.HOP,np.inf)):
            with self.assertRaises(ValueError):m.decode_chunks(np.zeros((1,192,3)),lambda *_:output)

    def engine(self, batches):
        obj=m.MeloNpu.__new__(m.MeloNpu)
        class Prefix:
            def generate(self,text,**kw):
                for batch in batches:
                    if kw['callback'](batch,0)==0:break
        obj.prefix=Prefix();obj.decoder=lambda *_:np.full(m.BUCKET*m.HOP,.1,np.float32)
        return obj

    def test_callback_failure_propagates(self):
        for batch in (np.zeros(193),np.zeros(0),np.full(192,np.nan)):
            with self.assertRaises(RuntimeError) as caught:self.engine([batch]).synthesize('test')
            self.assertIsInstance(caught.exception.__cause__,ValueError)
        obj=self.engine([np.zeros(192)])
        def broken(*_):raise OSError('NPU failed')
        obj.decoder=broken
        with self.assertRaises(RuntimeError) as caught:obj.synthesize('test')
        self.assertIsInstance(caught.exception.__cause__,OSError)

    def test_duration_limit_accumulates_batches(self):
        obj=self.engine([np.zeros(192),np.zeros(192)])
        with patch.object(m,'decode_chunks',return_value=np.full(m.RATE*23,.1,np.float32)):
            with self.assertRaises(RuntimeError) as caught:obj.synthesize('test')
        self.assertIn('too long',str(caught.exception.__cause__))
        with self.assertRaises(ValueError):self.engine([]).synthesize('test')

    def test_postprocess_once_per_callback_not_per_npu_chunk(self):
        batch=np.zeros(192*449,np.float32)
        obj=self.engine([batch,batch])
        with patch.object(m,'scale_silence',wraps=m.scale_silence) as scale:
            got,rate=obj.synthesize('test')
        self.assertEqual(scale.call_count,2)
        self.assertEqual(len(got),2*449*m.HOP)
        self.assertEqual(rate,44100)

if __name__=='__main__':unittest.main()
