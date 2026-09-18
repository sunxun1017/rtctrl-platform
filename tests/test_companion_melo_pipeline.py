import importlib.util,time,threading,unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import numpy as np
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from apps.companion import melo_npu as p
class PipelineTests(unittest.TestCase):
 def run_case(self,generate,decode):
  engine=SimpleNamespace(prefix=SimpleNamespace(generate=generate),decoder=object())
  with patch.object(p,'decode_chunks',side_effect=decode),patch.object(p,'scale_silence',side_effect=lambda x:x):
   return p.MeloNpu.synthesize(engine,'test')
 def tearDown(self):
  self.assertFalse(any(t.name=='melo-decoder-pipeline' for t in threading.enumerate()))
 def test_order_copy_and_overlap(self):
  entered=threading.Event();produced_next=threading.Event()
  def generate(*args,callback,**kw):
   samples=np.ones(192,np.float32)
   self.assertEqual(callback(samples,0),1)
   self.assertTrue(entered.wait(1))
   samples[:]=2
   self.assertEqual(callback(samples,1),1)
   samples[:]=99;produced_next.set()
  def decode(z,d):
   if z.flat[0]==1:
    entered.set();self.assertTrue(produced_next.wait(1))
   self.assertFalse(z.flags.writeable)
   return np.array([z.flat[0]],np.float32)
  wave,rate=self.run_case(generate,decode)
  np.testing.assert_array_equal(wave,[1,2]);self.assertEqual(rate,44100)
 def test_decoder_failure_unblocks_full_queue(self):
  def generate(*a,callback,**kw):
   for _ in range(20):
    if callback(np.zeros(192,np.float32),0)==0:return
  def decode(*a):raise ValueError('decoder error')
  with self.assertRaises(RuntimeError):self.run_case(generate,decode)
 def test_producer_failure_joins_decoder(self):
  def generate(*a,callback,**kw):
   callback(np.zeros(192,np.float32),0);raise ValueError('producer error')
  with self.assertRaises(RuntimeError):self.run_case(generate,lambda *a:np.zeros(1))
 def test_invalid_latent_and_output_limit(self):
  for samples in [np.zeros(193),np.array([np.nan]*192),np.zeros(192*4001)]:
   def generate(*a,callback,**kw):self.assertEqual(callback(samples,0),0)
   with self.assertRaises(RuntimeError):self.run_case(generate,lambda *a:np.zeros(1))
  def generate(*a,callback,**kw):callback(np.zeros(192),0)
  with self.assertRaises(RuntimeError):self.run_case(generate,lambda *a:np.zeros(44100*45+1))
 def test_empty(self):
  with self.assertRaises(ValueError):self.run_case(lambda *a,**k:None,lambda *a:None)
if __name__=='__main__':unittest.main()
