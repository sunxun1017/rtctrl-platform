"""Streaming lifecycle and protocol regressions without audio, NPU or cloud."""
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.companion.streaming_asr import StreamingAsr
from apps.companion.local_voice import LocalVoiceTransport
from apps.companion.core import Companion
from apps.companion.config import validate
from test_companion import FakeAudio, FakeCodec, FakeTransport, wait_for

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.directory = self.root / 'npu-asr'
        self.directory.mkdir()
        self.stream = None
    def tearDown(self):
        if self.stream:
            self.stream.close()
            self.stream.process.stdin.close()
            self.stream.process.stdout.close()
        self.temp.cleanup()
    def runner(self, response):
        path = self.directory / 'rknn_zipformer_stream'
        path.write_text("#!" + sys.executable + '\nimport sys,struct\nprint(\'{"type":"ready"}\',flush=True)\nh=sys.stdin.buffer.read(5)\nn,op=struct.unpack("<IB",h)\nsys.stdin.buffer.read(n)\n' + response)
        path.chmod(0o700)
        self.stream = StreamingAsr(self.root)
        return self.stream
    def test_partial(self):
        stream=self.runner('print(\'{"type":"partial","text":"你好","endpoint":false}\',flush=True)\n')
        self.assertEqual(stream.exchange(1,b'\0\0')['text'],'你好')
    def test_faults(self):
        for response in ['print("bad",flush=True)\n', 'print(\'{"type":"error"}\',flush=True)\n', 'print(\'{"type":"final"}\',flush=True)\n', 'print("x"*17000,flush=True)\n', 'raise SystemExit(0)\n']:
            with self.subTest(response=response):
                stream=self.runner(response)
                with self.assertRaises((ValueError,RuntimeError)):stream.exchange(1,b'\0\0')
                stream.close();stream.process.stdin.close();stream.process.stdout.close();self.stream=None
    def test_read_deadline(self):
        stream=self.runner("import time;time.sleep(.2)\n")
        with self.assertRaises(TimeoutError):stream._read(time.monotonic()-.1)
    def test_invalid_frame(self):
        stream=self.runner('pass\n')
        for op,pcm in [(0,b''),(1,b'x'),(2,b'xx'),(1,b'x'*32002)]:
            with self.assertRaises(ValueError):stream.exchange(op,pcm)

class TurnTests(unittest.TestCase):
    def setUp(self):
        self.messages=[];self.errors=[]
        self.transport=LocalVoiceTransport({'max_listen_s':30},self.messages.append,self.errors.append)
        self.transport._closed=False
        self.transport._asr_stream=MagicMock()
        self.transport._codec=MagicMock()
        self.transport._run=MagicMock()
    def tearDown(self):self.transport.close()
    def turn(self,final,automatic=False):
        self.transport._asr_stream.exchange.side_effect=[{'type':'reset'},{'type':'partial','text':'未完成','endpoint':automatic},{'type':'final','text':final}]
        frames=queue.Queue();frames.put(b'\0\0');frames.put(None)
        self.transport._recording=True
        self.transport._stream_turn(self.transport._generation,frames,automatic)
    def test_partial_only_does_not_start_reply(self):
        checked=[]
        def exchange(op,*args):
            if op==3:return {'type':'reset'}
            if op==1:return {'type':'partial','text':'半句'}
            checked.append(self.transport._run.call_count)
            return {'type':'final','text':'完整句'}
        self.transport._asr_stream.exchange.side_effect=exchange
        frames=queue.Queue();frames.put(b'\0\0');frames.put(None)
        self.transport._stream_turn(self.transport._generation,frames,False)
        self.assertEqual(checked,[0]);self.transport._run.assert_called_once()
        self.assertTrue(self.messages[0]['partial'])
    def test_auto_endpoint_manual_stop_once(self):
        self.turn('完整句',True)
        self.transport.send({'type':'listen','state':'stop'})
        self.assertEqual([m['type'] for m in self.messages],['stt','asr_endpoint'])
        self.transport._run.assert_called_once()
        self.assertEqual([c.args[0] for c in self.transport._asr_stream.exchange.call_args_list],[3,1,2])
    def test_empty_does_not_start_cloud(self):
        self.turn('  ')
        self.transport._run.assert_not_called()
        self.assertEqual(self.messages[-1]['type'],'asr_empty')
    def test_abort_fences_late_partial_and_final(self):
        def exchange(op,*args):
            if op==1:self.transport._cancel()
            return {'type':'partial' if op==1 else 'reset','text':'迟到'}
        self.transport._asr_stream.exchange.side_effect=exchange
        frames=queue.Queue();frames.put(b'\0\0')
        self.transport._stream_turn(self.transport._generation,frames,False)
        self.assertEqual(self.messages,[]);self.transport._run.assert_not_called()
    def test_queue_full_is_not_silently_dropped(self):
        self.transport._recording=True;self.transport._frames=queue.Queue(maxsize=1)
        self.transport.send_pcm(b'\0\0')
        with self.assertRaises(queue.Full):self.transport.send_pcm(b'\0\0')

class StreamTransport(FakeTransport):
    def send_pcm(self, pcm):self.sent.append(pcm)

class ContinuousCoreTests(unittest.TestCase):
    def setUp(self):
        config=validate({'mode':'live','voice_backend':'local','local_asr_backend':'rknn',
            'local_asr_streaming':True,'local_speech_root':'/models','local_speech_socket':'/speech.sock',
            'local_asr_command':['/bin/true'],'local_tts_command':['/bin/true']})
        self.core=Companion(config,FakeAudio,FakeCodec,StreamTransport)
        self.core.start();self.core.action('connect');wait_for(lambda:self.core.snapshot()['connected'])
        self.core.action('unmute')
    def tearDown(self):self.core.close()
    def frame(self):
        self.core.audio.callback(b'\0\0')
        wait_for(lambda:self.core.turn_audio_frames_sent>0)
    def test_endpoint_and_stop_idempotent_then_resume(self):
        self.core.action('continuous');self.frame()
        transport=self.core.transport
        transport.message({'type':'asr_endpoint'})
        wait_for(lambda:self.core.snapshot()['state']=='thinking')
        self.core.action('stop');transport.message({'type':'asr_endpoint'})
        transport.message({'type':'asr_empty'})
        wait_for(lambda:self.core.snapshot()['state']=='listening')
        self.assertEqual(sum(x.get('state')=='stop' for x in transport.sent if isinstance(x,dict)),1)
    def test_lease_expiry_mutes(self):
        self.core.action('continuous');self.core.auto_until=time.monotonic()-.1
        wait_for(lambda:self.core.snapshot()['muted'])
        self.assertFalse(self.core.snapshot()['continuous'])
        self.assertFalse(self.core.audio.recording)
    def test_mute_and_disconnect_fence_old_generation(self):
        self.core.action('continuous');old=self.core.generation
        self.core.action('mute')
        self.core.post('message',{'type':'stt','text':'迟到','partial':True},old)
        wait_for(lambda:self.core.snapshot()['connected'])
        self.core.action('disconnect')
        self.core.post('message',{'type':'asr_endpoint'},old)
        time.sleep(.05)
        self.assertEqual(self.core.snapshot()['state'],'offline')
        self.assertNotEqual(self.core.snapshot()['transcript'],'迟到')
        self.assertFalse(self.core.snapshot()['continuous'])

if __name__=='__main__':unittest.main()
