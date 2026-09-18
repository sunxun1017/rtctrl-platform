"""Full duplex coordination without microphones or network."""
import sys
import time
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from apps.companion.config import validate
from apps.companion.core import Companion
from test_companion import FakeAudio, FakeCodec, wait_for
from test_companion_streaming import StreamTransport

class DuplexTests(unittest.TestCase):
    def setUp(self):
        config=validate(dict(mode="live",voice_backend="local",local_asr_backend="rknn",
            local_asr_streaming=True,local_speech_root="/models",local_speech_socket="/speech.sock",
            local_asr_command=["/bin/true"],local_tts_command=["/bin/true"],
            aec_enabled=True,aec_library="/fake.so",full_duplex=True))
        self.core=Companion(config,FakeAudio,FakeCodec,StreamTransport)
        self.core.start();self.core.action("connect")
        wait_for(lambda:self.core.snapshot()["connected"])
        self.core.action("unmute");self.core.action("continuous")
        self.transport=self.core.transport
    def tearDown(self):self.core.close()
    def message(self,kind,**data):self.transport.message(dict(type=kind,**data))
    def replies(self):return [x for x in self.transport.sent if isinstance(x,dict) and x.get("type")=="reply"]
    def speaking(self):
        self.message("duplex_final",text="first question")
        wait_for(lambda:len(self.replies())==1)
        self.message("tts",state="start")
        self.message("unused")
        self.transport.message(b"response")
        wait_for(lambda:self.core.snapshot()["state"]=="speaking" and self.core.audio.busy)
    def test_recognizes_while_playing_and_waits_for_drain(self):
        self.speaking();audio=self.core.audio;epoch=self.core.capture_epoch
        before=self.core.turn_audio_frames_sent
        audio.callback(b"\0\0")
        wait_for(lambda:self.core.turn_audio_frames_sent>before)
        self.assertEqual(self.core.capture_epoch,epoch)
        self.assertTrue(audio.recording)
        self.message("duplex_started")
        self.message("duplex_partial",text="second")
        wait_for(lambda:self.core.snapshot()["next_transcript"]=="second")
        self.assertEqual(self.core.snapshot()["state"],"speaking")
        self.message("duplex_final",text="second question")
        wait_for(lambda:self.core.snapshot()["pending_utterances"]==1)
        self.message("tts",state="stop");self.message("response_complete")
        time.sleep(.08);self.assertEqual(len(self.replies()),1)
        audio.busy=False
        wait_for(lambda:len(self.replies())==2)
        self.assertEqual(self.replies()[-1]["text"],"second question")
        self.assertIs(self.core.audio,audio)
    def test_drain_alone_does_not_start_next_response(self):
        self.speaking();self.message("duplex_final",text="next")
        wait_for(lambda:self.core.snapshot()["pending_utterances"]==1)
        self.message("tts",state="stop");self.core.audio.busy=False
        time.sleep(.08);self.assertEqual(len(self.replies()),1)
        self.message("response_complete")
        wait_for(lambda:len(self.replies())==2)
    def test_completion_keeps_listener_and_does_not_restart_capture(self):
        self.speaking();callback=self.core.audio.callback
        self.message("duplex_waiting");self.message("tts",state="stop")
        self.core.audio.busy=False;self.message("response_complete")
        wait_for(lambda:self.core.snapshot()["state"]=="listening")
        self.assertIs(self.core.audio.callback,callback)
        self.assertEqual(self.core.deadline,0)
        self.assertTrue(self.core.audio.recording)
    def test_mute_clears_pending_and_fences_late_recognition(self):
        self.speaking();audio=self.core.audio;generation=self.core.generation
        self.message("duplex_final",text="next")
        wait_for(lambda:self.core.snapshot()["pending_utterances"]==1)
        self.core.action("mute")
        self.core.post("message",dict(type="duplex_final",text="late"),generation)
        time.sleep(.08)
        self.assertFalse(audio.recording)
        self.assertEqual(self.core.snapshot()["pending_utterances"],0)
        self.assertTrue(self.core.snapshot()["muted"])
        self.assertEqual(self.core.snapshot()["input_state"],"off")
    def test_pending_queue_is_bounded(self):
        self.speaking()
        for i in range(4):self.message("duplex_final",text=str(i))
        wait_for(lambda:self.core.snapshot()["state"]=="error")
        self.assertFalse(self.core.snapshot()["continuous"])
        self.assertEqual(len(self.core.pending_utterances),0)
    def test_public_stop_cannot_leave_dead_listener(self):
        audio=self.core.audio
        self.core.action("stop")
        self.assertTrue(self.core.snapshot()["muted"])
        self.assertFalse(self.core.snapshot()["continuous"])
        self.assertFalse(audio.recording)

    def test_requires_aec(self):
        with self.assertRaises(ValueError):validate(dict(full_duplex=True))

if __name__=="__main__":unittest.main()
