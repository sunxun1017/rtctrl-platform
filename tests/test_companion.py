import io
import json
import pathlib
import sys
import subprocess
import struct
import tarfile
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from apps.companion.config import validate
from apps.companion.core import Companion, validate_hello
from apps.companion.monitor import Monitor
from apps.companion.server import Server

class FakeAudio:
    def __init__(self, config, on_error=None):
        self.recording = False
        self.busy = False
        self.played = []
        self.rate = None
        self.closed = False
    def configure_output(self, rate): self.rate = rate
    def start(self, callback): self.recording = True; self.callback = callback
    def stop_capture(self): self.recording = False
    def play(self, packet): self.played.append(packet); self.busy = True
    def playback_busy(self): return self.busy
    def interrupt(self): self.busy = False
    def stop(self): self.closed = True; self.recording = False; self.busy = False

class FakeCodec:
    def encode(self, pcm): return b"opus"
    def close(self): pass

class FakeTransport:
    def __init__(self, config, on_message, on_error):
        self.message, self.error = on_message, on_error
        self.sent = []
        self.closed = False
        self.broken = False
    def connect(self):
        self.message({"type":"hello", "session_id":"test", "audio_params":{
            "format":"opus", "channels":1, "sample_rate":24000, "frame_duration":60}})
    def send(self, value):
        if self.broken: raise RuntimeError("offline")
        self.sent.append(value)
    def close(self): self.closed = True

def wait_for(fn, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn(): return
        time.sleep(.01)
    raise AssertionError("condition timed out")

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.core = Companion(validate({"mode":"live","backend_url":"wss://example.test"}),
                              FakeAudio, FakeCodec, FakeTransport)
        self.core.start()
        self.core.action("connect")
        wait_for(lambda: self.core.snapshot()["connected"])
    def tearDown(self): self.core.close()
    def listen(self):
        self.core.action("unmute")
        self.core.action("listen")
    def send_frame(self):
        before = self.core.snapshot()["metrics"]["audio_frames_sent"]
        self.core.audio.callback(b"pcm")
        wait_for(lambda: self.core.snapshot()["metrics"]["audio_frames_sent"] == before + 1)
    def test_connect_never_records_and_negotiates_output(self):
        self.assertTrue(self.core.snapshot()["muted"])
        self.assertFalse(self.core.audio.recording)
        self.assertEqual(self.core.audio.rate, 24000)
        with self.assertRaises(ValueError): self.core.action("listen")
    def test_ptt_audio_and_tail_drain(self):
        self.listen()
        self.core.audio.callback(b"pcm")
        wait_for(lambda: b"opus" in self.core.transport.sent)
        self.core.action("stop")
        self.assertFalse(self.core.audio.recording)
        self.core.transport.message({"type":"tts","state":"start"})
        self.core.transport.message(b"response")
        self.core.transport.message({"type":"tts","state":"stop"})
        wait_for(lambda: self.core.audio.played)
        self.assertEqual(self.core.snapshot()["state"],"speaking")
        self.core.audio.busy = False
        wait_for(lambda: self.core.snapshot()["state"] == "idle")
    def test_repeated_unmute_does_not_lose_recording_deadline(self):
        self.listen()
        deadline = self.core.deadline
        self.core.action("unmute")
        self.assertEqual(self.core.snapshot()["state"],"listening")
        self.assertEqual(deadline,self.core.deadline)
    def test_mute_stops_and_rejects_late_tts(self):
        self.listen()
        self.send_frame()
        self.core.action("stop")
        audio = self.core.audio
        old = self.core.transport
        self.core.action("mute")
        old.message({"type":"tts","state":"start"})
        old.message(b"late")
        time.sleep(.08)
        self.assertFalse(audio.recording)
        self.assertEqual(audio.played,[])
        self.assertEqual(self.core.snapshot()["state"],"muted")
    def test_interrupted_reply_cannot_enter_next_turn(self):
        self.listen()
        self.send_frame()
        self.core.action("stop")
        old = self.core.transport
        self.core.action("interrupt")
        wait_for(lambda:self.core.snapshot()["connected"])
        self.core.action("listen")
        self.send_frame()
        self.core.action("stop")
        old.message({"type":"tts","state":"start"})
        old.message(b"stale")
        time.sleep(.08)
        self.assertEqual(self.core.snapshot()["state"],"thinking")
        self.assertEqual(self.core.audio.played,[])
    def test_old_capture_callback_cannot_enter_new_turn(self):
        self.listen()
        old_callback = self.core.audio.callback
        self.send_frame()
        self.core.action("stop")
        self.core.transport.message({"type":"tts","state":"start"})
        self.core.transport.message({"type":"tts","state":"stop"})
        wait_for(lambda:self.core.snapshot()["state"]=="idle")
        self.core.action("listen")
        before = self.core.snapshot()["metrics"]["audio_frames_sent"]
        old_callback(b"stale-pcm")
        time.sleep(.08)
        self.assertEqual(self.core.snapshot()["metrics"]["audio_frames_sent"], before)
    def test_empty_recording_stops_without_waiting_for_backend(self):
        self.listen()
        audio, transport = self.core.audio, self.core.transport
        state = self.core.action("stop")
        self.assertEqual(state["state"], "error")
        self.assertIn("未采集到音频", state["error"])
        self.assertFalse(state["connected"])
        self.assertEqual(self.core.deadline, 0)
        self.assertTrue(audio.closed)
        self.assertTrue(transport.closed)
        self.assertIn({"type":"abort", "session_id":"test", "reason":"no_audio"}, transport.sent)
        self.assertFalse(any(isinstance(item, dict) and item.get("type") == "listen"
                             and item.get("state") == "stop" for item in transport.sent))
        transport.message({"type":"tts", "state":"start"})
        transport.message(b"late")
        time.sleep(.08)
        self.assertEqual(audio.played, [])
        self.assertEqual(self.core.snapshot()["state"], "error")
        self.core.action("connect")
        wait_for(lambda:self.core.snapshot()["connected"])
        self.assertTrue(self.core.thread.is_alive())

    def test_failed_pcm_send_does_not_count_as_captured_turn(self):
        self.listen()
        self.core.transport.broken = True
        self.core.audio.callback(b"pcm")
        wait_for(lambda:self.core.snapshot()["state"] == "error")
        self.assertEqual(self.core.turn_audio_frames_sent, 0)
        self.assertEqual(self.core.snapshot()["metrics"]["audio_frames_sent"], 0)

    def test_empty_auto_stop_reports_no_audio(self):
        self.listen()
        self.core.deadline = time.monotonic() - 1
        wait_for(lambda:self.core.snapshot()["state"] == "error")
        self.assertIn("未采集到音频", self.core.snapshot()["error"])
        self.assertEqual(self.core.deadline, 0)

    def test_empty_new_turn_does_not_reuse_previous_frame_count(self):
        self.listen()
        self.send_frame()
        self.core.action("stop")
        self.core.transport.message({"type":"tts", "state":"start"})
        self.core.transport.message({"type":"tts", "state":"stop"})
        wait_for(lambda:self.core.snapshot()["state"] == "idle")
        self.core.action("listen")
        state = self.core.action("stop")
        self.assertEqual(state["metrics"]["audio_frames_sent"], 1)
        self.assertEqual(state["state"], "error")
        self.assertIn("未采集到音频", state["error"])

    def test_empty_recording_cleanup_survives_abort_send_failure(self):
        self.listen()
        audio, transport = self.core.audio, self.core.transport
        transport.broken = True
        state = self.core.action("stop")
        self.assertEqual(state["state"], "error")
        self.assertIn("未采集到音频", state["error"])
        self.assertTrue(audio.closed)
        self.assertTrue(transport.closed)

    def test_realtime_tail_is_paced_synthetic_audio_without_listen_stop(self):
        self.core.config["listen_mode"] = "realtime"
        encoded = []
        def encode(pcm):
            encoded.append((time.monotonic(), pcm))
            return b"opus"
        self.core.codec.encode = encode
        self.listen()
        self.send_frame()
        audio, transport = self.core.audio, self.core.transport
        self.core.action("stop")
        self.assertFalse(audio.recording)
        self.assertEqual(self.core.snapshot()["state"], "thinking")
        self.assertGreater(self.core.silence_remaining, 0)
        self.assertEqual(self.core.action("unmute")["state"], "thinking")
        wait_for(lambda:self.core.silence_remaining == 0, timeout=3)
        silence = [(stamp, pcm) for stamp, pcm in encoded if pcm == bytes(1920)]
        self.assertEqual(len(silence), 20)
        self.assertTrue(all(b[0] - a[0] >= .055 for a, b in zip(silence, silence[1:])))
        self.assertFalse(audio.recording)
        self.assertEqual(self.core.turn_audio_frames_sent, 1)
        self.assertEqual(self.core.snapshot()["metrics"]["audio_frames_sent"], 21)
        self.assertIn({"type":"listen", "session_id":"test", "state":"start", "mode":"realtime"}, transport.sent)
        self.assertFalse(any(isinstance(item,dict) and item.get("type") == "listen"
                             and item.get("state") == "stop" for item in transport.sent))

    def test_realtime_early_tts_stops_capture_and_rejects_late_pcm(self):
        self.core.config["listen_mode"] = "realtime"
        self.listen()
        self.send_frame()
        audio, transport = self.core.audio, self.core.transport
        old_callback = audio.callback
        transport.message({"type":"tts", "state":"start"})
        wait_for(lambda:self.core.snapshot()["state"] == "speaking")
        self.assertFalse(audio.recording)
        self.assertEqual(self.core.silence_remaining, 0)
        old_callback(b"late")
        transport.message(b"reply")
        wait_for(lambda:audio.played == [b"reply"])
        self.assertEqual(self.core.snapshot()["metrics"]["audio_frames_sent"], 1)
        self.core.action("stop")
        self.assertEqual(self.core.snapshot()["state"], "speaking")

    def test_realtime_tts_cancels_pending_silence(self):
        self.core.config["listen_mode"] = "realtime"
        self.listen()
        self.send_frame()
        self.core.action("stop")
        self.core.transport.message({"type":"tts", "state":"start"})
        wait_for(lambda:self.core.snapshot()["state"] == "speaking")
        count = self.core.snapshot()["metrics"]["audio_frames_sent"]
        time.sleep(.15)
        self.assertEqual(self.core.silence_remaining, 0)
        self.assertEqual(self.core.snapshot()["metrics"]["audio_frames_sent"], count)

    def test_realtime_interrupt_and_release_cancel_pending_silence(self):
        self.core.config["listen_mode"] = "realtime"
        for action in ("interrupt", "disconnect"):
            self.listen()
            self.send_frame()
            self.core.action("stop")
            old = self.core.transport
            self.core.action(action)
            count = len(old.sent)
            time.sleep(.15)
            self.assertEqual(self.core.silence_remaining, 0)
            self.assertEqual(len(old.sent), count)
            self.assertTrue(old.closed)
            if action == "interrupt":
                wait_for(lambda:self.core.snapshot()["connected"])

    def test_capture_peak_is_current_turn_and_does_not_reject_silence(self):
        self.listen()
        self.core.audio.callback(struct.pack("<hhh", -32768, 7, 1234))
        wait_for(lambda:self.core.snapshot()["metrics"]["audio_frames_sent"] == 1)
        self.assertEqual(self.core.snapshot()["metrics"]["capture_peak_amplitude"], 32768)
        self.core.audio.callback(struct.pack("<h", 20))
        wait_for(lambda:self.core.snapshot()["metrics"]["audio_frames_sent"] == 2)
        self.assertEqual(self.core.snapshot()["metrics"]["capture_peak_amplitude"], 32768)
        self.core.action("interrupt")
        wait_for(lambda:self.core.snapshot()["connected"])
        self.core.action("listen")
        self.assertEqual(self.core.snapshot()["metrics"]["capture_peak_amplitude"], 0)
        self.core.audio.callback(bytes(1920))
        wait_for(lambda:self.core.snapshot()["metrics"]["audio_frames_sent"] == 3)
        state = self.core.action("stop")
        self.assertEqual(state["state"], "thinking")
        self.assertEqual(state["metrics"]["capture_peak_amplitude"], 0)

    def test_network_error_closes_microphone(self):
        self.listen()
        audio = self.core.audio
        self.core.transport.error("secret error body")
        wait_for(lambda: self.core.snapshot()["state"] == "error")
        self.assertTrue(audio.closed)
        self.assertNotIn("secret",self.core.snapshot()["error"])
    def test_timeout_failure_does_not_kill_worker(self):
        self.listen()
        self.core.transport.broken = True
        self.core.deadline = time.monotonic()-1
        wait_for(lambda: self.core.snapshot()["state"] == "error")
        self.assertTrue(self.core.thread.is_alive())
        self.core.action("connect")
        wait_for(lambda: self.core.snapshot()["connected"])
    def test_old_connection_callback_ignored(self):
        old = self.core.transport
        self.core.action("disconnect")
        self.core.action("connect")
        wait_for(lambda:self.core.snapshot()["connected"])
        old.error("stale")
        time.sleep(.08)
        self.assertTrue(self.core.snapshot()["connected"])
    def test_no_remote_actuator_authority(self):
        self.core.transport.message({"type":"iot","method":"action_control","params":{"action_type":5}})
        time.sleep(.08)
        self.assertFalse(self.core.snapshot()["capabilities"]["actuator_control"])
        self.assertTrue(self.core.snapshot()["connected"])
    def test_queue_overflow_stops_session(self):
        self.listen()
        audio = self.core.audio
        self.core.overflow.set()
        wait_for(lambda:self.core.snapshot()["state"] == "error")
        self.assertTrue(audio.closed)
    def test_wrong_session_ignored(self):
        self.listen()
        self.core.transport.message({"type":"stt","session_id":"other","text":"wrong"})
        time.sleep(.08)
        self.assertEqual(self.core.snapshot()["transcript"],"")
    def test_max_recording_auto_stops(self):
        self.listen()
        self.send_frame()
        self.core.deadline = time.monotonic()-1
        wait_for(lambda:self.core.snapshot()["state"] == "thinking")
        self.assertFalse(self.core.audio.recording)
    def test_response_timeout_releases_audio(self):
        self.listen()
        self.send_frame()
        self.core.action("stop")
        audio = self.core.audio
        self.core.deadline = time.monotonic()-1
        wait_for(lambda:self.core.snapshot()["state"] == "error")
        self.assertTrue(audio.closed)

    def test_voice_progress_distinguishes_no_recognition_reply_and_audio(self):
        self.listen()
        self.assertEqual(self.core.snapshot()["voice_progress"], "recording")
        self.send_frame()
        self.core.action("stop")
        self.assertEqual(self.core.snapshot()["voice_progress"], "waiting_recognition")
        self.assertIn("未收到识别结果", self.core._timeout_reason())
        self.core.transport.message({"type":"stt", "text":"测试"})
        wait_for(lambda:self.core.snapshot()["voice_progress"] == "waiting_reply")
        self.assertIn("未收到回答", self.core._timeout_reason())
        self.core.transport.message({"type":"tts", "state":"start"})
        wait_for(lambda:self.core.snapshot()["voice_progress"] == "waiting_audio")
        self.assertIn("未收到语音音频", self.core._timeout_reason())
        self.core.transport.message(b"audio")
        wait_for(lambda:self.core.snapshot()["voice_progress"] == "receiving_audio")
        self.core.audio.busy = False
        self.core.transport.message({"type":"tts", "state":"stop"})
        wait_for(lambda:self.core.snapshot()["voice_progress"] == "complete")
        self.core.action("listen")
        self.assertEqual(self.core.snapshot()["voice_progress"], "recording")
        self.assertEqual(self.core.turn_audio_frames_received, 0)

    def test_voice_timeout_exposes_stage_and_releases_devices(self):
        self.listen()
        self.send_frame()
        self.core.action("stop")
        self.core.transport.message({"type":"stt", "text":"测试"})
        wait_for(lambda:self.core.snapshot()["voice_progress"] == "waiting_reply")
        audio = self.core.audio
        self.core.deadline = time.monotonic()-1
        wait_for(lambda:self.core.snapshot()["state"] == "error")
        value = self.core.snapshot()
        self.assertEqual(value["voice_progress"], "failed")
        self.assertIn("未收到回答", value["error"])
        self.assertTrue(audio.closed)

    def test_late_stt_does_not_regress_audio_progress(self):
        self.listen()
        self.send_frame()
        self.core.action("stop")
        self.core.transport.message({"type":"tts", "state":"start"})
        self.core.transport.message(b"audio")
        self.core.transport.message({"type":"stt", "text":"迟到的识别"})
        wait_for(lambda:self.core.snapshot()["transcript"] == "迟到的识别")
        self.assertEqual(self.core.snapshot()["voice_progress"], "receiving_audio")

class LocalCoreTests(unittest.TestCase):
    def test_local_manual_stop_does_not_add_cloud_vad_tail(self):
        config = validate({"mode": "live", "voice_backend": "local",
                           "local_asr_command": ["/bin/true"], "local_tts_command": ["/bin/true"]})
        core = Companion(config, FakeAudio, FakeCodec, FakeTransport)
        core.start()
        try:
            core.action("connect")
            wait_for(lambda: core.snapshot()["connected"])
            self.assertFalse(core.snapshot()["capabilities"]["audio_upload"])
            self.assertTrue(core.snapshot()["muted"])
            core.action("unmute"); core.action("listen")
            core.audio.callback(b"pcm")
            wait_for(lambda: core.turn_audio_frames_sent == 1)
            core.action("stop")
            self.assertEqual(core.silence_remaining, 0)
            self.assertTrue(any(isinstance(x, dict) and x.get("type") == "listen" and
                                x.get("state") == "stop" for x in core.transport.sent))
            self.assertIn("本地语音识别", core._timeout_reason())
        finally:
            core.close()

class ConfigTests(unittest.TestCase):
    def test_invalid_and_unsafe_configs(self):
        for config in ({"device_settings_enabled":1},{"port":True},{"face_poll_s":float("nan")},{"bind":"0.0.0.0"},
                       {"unknown":1},{"mode":"live","backend_url":"ws://example.test"},
                       {"face_url":"http://remote.test/status.json"}):
            with self.subTest(config=config),self.assertRaises(ValueError): validate(config)
    def test_local_voice_configuration(self):
        base = {"mode": "live", "voice_backend": "local", "listen_mode": "manual",
                "local_asr_command": ["/usr/bin/python3", "asr.py", "{input}", "{output}"],
                "local_tts_command": ["/usr/bin/python3", "tts.py", "{text}", "{output}"]}
        self.assertEqual(validate(base)["backend_url"], "")
        self.assertFalse(validate(base)["allow_insecure_ws"])
        for change in ({"listen_mode": "realtime"}, {"local_asr_command": []},
                       {"local_tts_command": "bad"}, {"local_asr_command": ["relative"]},
                       {"local_asr_timeout_s": True}, {"qianfan_model": ""},
                       {"qianfan_proxy_url": "http://example.test:80"},
                       {"qianfan_proxy_url": "http://secret@127.0.0.1:18080"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(dict(base, **change))
        self.assertEqual(validate(dict(base, qianfan_proxy_url="http://127.0.0.1:18080"))["voice_backend"], "local")

    def test_hello_validation(self):
        with self.assertRaises(ValueError): validate_hello({"type":"hello"})
        with self.assertRaises(ValueError): validate_hello({"session_id":"x","audio_params":{"sample_rate":44100}})
        self.assertEqual(validate_hello({"session_id":"x","audio_params":{"sample_rate":24000}}),(24000,"x"))

class MonitorTests(unittest.TestCase):
    def test_freeze_and_invalid_face_fields(self):
        core=Companion(validate({}))
        monitor=Monitor(core)
        value={"running":True,"frame":3,"faces":[None,{"name":"A","similarity":.8},
              {"name":"bad","similarity":float("nan")}],"fps":float("nan")}
        monitor.opener.open=lambda *a,**k:io.BytesIO(json.dumps(value).encode())
        with patch("apps.companion.monitor.time.monotonic",return_value=10):
            first=monitor.sample_face()
        self.assertTrue(first["available"])
        self.assertTrue(first["running"])
        self.assertEqual(len(first["faces"]),1)
        self.assertIsNone(first["fps"])
        with patch("apps.companion.monitor.time.monotonic",return_value=20):
            self.assertFalse(monitor.sample_face()["available"])

class BundleTests(unittest.TestCase):
    def test_bundle_is_self_contained_and_has_no_credentials(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            archive = pathlib.Path(folder)/"bundle.tar.gz"
            subprocess.run([sys.executable,str(root/"scripts/package-companion.py"),
                            "--output",str(archive)],check=True,stdout=subprocess.PIPE)
            unpacked = pathlib.Path(folder)/"unpacked"
            with tarfile.open(archive) as package:
                names = package.getnames()
                self.assertNotIn(".env",names)
                package.extractall(unpacked)
            manifest = json.loads((unpacked/"manifest.json").read_text())
            self.assertIn("apps/companion/core.py",manifest)
            result = subprocess.run(["sh","run-companion.sh","config/companion/demo.json","--doctor"],
                cwd=unpacked,check=True,stdout=subprocess.PIPE,text=True)
            self.assertEqual(json.loads(result.stdout)["mode"],"demo")

class HttpTests(unittest.TestCase):
    def setUp(self):
        self.core=Companion(validate({}))
        self.core.start()
        self.server=Server(("127.0.0.1",0),self.core)
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.worker.start()
        self.base="http://127.0.0.1:%d"%self.server.server_port
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.core.close();self.worker.join()
    def req(self,path="/api/status",body=None,headers=None):
        request=urllib.request.Request(self.base+path,data=body,headers=headers or {})
        return self.opener.open(request,timeout=3)
    def test_demo_complete_and_interrupt(self):
        headers={"Content-Type":"application/json"}
        for action in ("connect","unmute","listen","stop"):
            with self.req("/api/action",json.dumps({"action":action}).encode(),headers) as response:
                state=json.load(response)
        self.assertEqual(state["state"],"thinking")
        wait_for(lambda:self.core.snapshot()["state"]=="speaking")
        self.assertIn("演示",self.core.snapshot()["reply"])
        with self.req("/api/action",b'{"action":"interrupt"}',headers) as response:
            self.assertEqual(json.load(response)["state"],"idle")
    def test_csrf_invalid_host_and_payload(self):
        for headers,body,code in [
            ({"Origin":"http://evil.test","Content-Type":"application/json"},b'{"action":"connect"}',403),
            ({"Host":"evil.test","Content-Type":"application/json"},b'{"action":"connect"}',403),
            ({"Content-Type":"text/plain"},b'{"action":"connect"}',415),
            ({"Content-Type":"application/json"},b'[]',400),
            ({"Content-Type":"application/json"},b"x"*1025,400)]:
            with self.subTest(code=code),self.assertRaises(urllib.error.HTTPError) as raised:
                self.req("/api/action",body,headers)
            self.assertEqual(raised.exception.code,code)
    def test_network_api_gates_and_async_dispatch(self):
        with self.req("/api/network") as response:
            self.assertFalse(json.load(response)["available"])
        class Network:
            def __init__(self): self.calls = []
            def snapshot(self): return {"available": True, "busy": False, "networks": []}
            def action(self, value):
                self.calls.append(value)
                return {"available": True, "busy": True, "networks": []}
        network = Network()
        self.server.network = network
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.req("/api/network", b'{"action":"scan"}',
                     {"Origin":"http://evil.test", "Content-Type":"application/json"})
        self.assertEqual(raised.exception.code, 403)
        self.assertEqual(network.calls, [])
        with self.req("/api/network", b'{"action":"scan"}',
                      {"Content-Type":"application/json"}) as response:
            self.assertEqual(response.status, 202)
            self.assertTrue(json.load(response)["busy"])
        self.assertEqual(network.calls, [{"action":"scan"}])
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.req("/api/network", b'{"password":"SECRET"', {"Content-Type":"application/json"})
        self.assertNotIn(b"SECRET", raised.exception.read())
    def test_device_api_gates_and_same_origin(self):
        with self.req("/api/device") as response:
            self.assertFalse(json.load(response)["available"])
        headers = {"Content-Type": "application/json"}
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.req("/api/device", b'{"action":"set_volume","value":40}', headers)
        self.assertEqual(raised.exception.code, 400)
        class Device:
            def __init__(self): self.calls = []
            def snapshot(self): return {"available": True, "volume_percent": 40}
            def action(self, body):
                if not isinstance(body, dict): raise ValueError("invalid action")
                self.calls.append(body)
                return self.snapshot()
        device = self.server.device = Device()
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.req("/api/device", b'{"action":"set_volume","value":40}',
                     dict(headers, Origin="http://evil.test"))
        self.assertEqual(raised.exception.code, 403)
        self.assertEqual(device.calls, [])
        with self.req("/api/device", b'{"action":"set_volume","value":40}', headers) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response)["volume_percent"], 40)
        self.assertEqual(device.calls, [{"action": "set_volume", "value": 40}])
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.req("/api/device", b'[]', headers)
        self.assertEqual(raised.exception.code, 400)

    def test_static_and_status(self):
        for path in ("/","/style.css","/app.js","/api/status"):
            with self.req(path) as response:
                self.assertEqual(response.status,200)
                self.assertTrue(response.read())
                self.assertIn("frame-ancestors",response.headers["Content-Security-Policy"])

if __name__=="__main__": unittest.main()
