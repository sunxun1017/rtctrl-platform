"""Local voice contract tests; no microphones, model downloads or real APIs."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.companion.local_voice import LocalVoiceTransport
from apps.companion.audio import PcmAudio


class Codec:
    def decode(self, value):
        return value

    def encode(self, value):
        return b"packet"

    def reset_decoder(self):
        pass

    def close(self):
        pass


class LocalVoiceTests(unittest.TestCase):
    def setUp(self):
        self.messages, self.errors = [], []
        self.config = {"local_asr_command": [sys.executable, "{input}", "{output}"],
                       "local_tts_command": [sys.executable, "{text}", "{output}"],
                       "max_listen_s": 1}
        self.transport = LocalVoiceTransport(self.config, self.messages.append, self.errors.append)
        self.env = patch.dict(os.environ, {"BAIDU_QIANFAN_API_KEY": "unit-test-secret"})
        self.env.start()
        self.codec = patch("apps.companion.local_voice.OpusCodec", Codec)
        self.codec.start()
        self.transport.connect()

    def tearDown(self):
        self.transport.close()
        self.codec.stop()
        self.env.stop()

    def test_warm_worker_not_ready_blocks_connect(self):
        config = dict(self.config, local_speech_socket="/missing/socket")
        candidate = LocalVoiceTransport(config, self.messages.append, self.errors.append)
        with self.assertRaisesRegex(ValueError, "仍在加载"):
            candidate.connect()

    def test_warm_worker_busy_blocks_connect(self):
        config = dict(self.config, local_speech_socket="/test/socket")
        candidate = LocalVoiceTransport(config, self.messages.append, self.errors.append)
        with patch("apps.companion.local_voice.socket.socket") as factory:
            factory.return_value.__enter__.return_value.recv.return_value = b'{"ok":true,"ready":true,"busy":true}\n'
            with self.assertRaisesRegex(ValueError, "上一轮"):
                candidate.connect()

    def test_hello_negotiates_local_rate_without_cloud_request(self):
        self.transport.send({"type": "hello"})
        self.assertEqual(self.messages[0]["audio_params"]["sample_rate"], 16000)
        self.assertTrue(self.messages[0]["session_id"])

    def test_rejects_shell_and_relative_executable(self):
        for command in ("echo hi", ["python3"], ["/missing/tool"]):
            with self.assertRaises(ValueError):
                self.transport._command(command)

    def test_recording_is_bounded(self):
        self.transport.send({"type": "listen", "state": "start"})
        with self.assertRaises(ValueError):
            self.transport.send(b"x" * 40000)

    def test_abort_drops_late_events_and_pcm(self):
        generation = self.transport._generation
        self.transport.send({"type": "abort"})
        self.transport._emit(generation, {"type": "llm", "text": "old"})
        self.assertEqual(self.messages, [])
        self.assertFalse(self.transport._recording)

    def test_pipeline_order_and_temp_cleanup(self):
        paths = []
        def execute(generation, command, timeout_key, **values):
            paths.append(values["output"])
            if timeout_key == "local_asr_timeout_s":
                Path(values["output"]).write_text(json.dumps({"text": "你好"}))
            else:
                with wave.open(values["output"], "wb") as output:
                    output.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
                    output.writeframes(b"\0" * 2646)
        with patch.object(self.transport, "_execute", side_effect=execute), patch.object(self.transport, "_reply", return_value="你好呀"):
            self.transport._run(self.transport._generation, b"\0" * 1920)
        self.assertFalse(self.errors)
        self.assertEqual([x["type"] for x in self.messages if isinstance(x, dict)], ["stt", "llm", "tts", "tts", "tts"])
        self.assertTrue(any(isinstance(x, PcmAudio) for x in self.messages))
        self.assertTrue(all(not Path(path).exists() for path in paths))

    def test_error_never_contains_command_or_secret(self):
        with patch.object(self.transport, "_execute", side_effect=RuntimeError("unit-test-secret private text")):
            self.transport._run(self.transport._generation, b"xx")
        self.assertEqual(len(self.errors), 1)
        self.assertNotIn("unit-test-secret", self.errors[0])
        self.assertIn("本地语音识别", self.errors[0])

    def test_https_only_text_no_redirect(self):
        response = MagicMock(status=200)
        response.read.return_value = json.dumps({"choices": [{"message": {"content": "回答"}}]}).encode()
        with patch("apps.companion.local_voice.http.client.HTTPSConnection") as factory:
            factory.return_value.getresponse.return_value = response
            self.assertEqual(self.transport._reply("问题"), "回答")
            factory.assert_called_once_with("qianfan.baidubce.com", timeout=30)
            args, kwargs = factory.return_value.request.call_args
            self.assertEqual(args[:2], ("POST", "/v2/chat/completions"))
            body = json.loads(kwargs["body"])
            self.assertEqual(body["messages"][1]["content"], "问题")
            response.status = 302
            with self.assertRaises(RuntimeError):
                self.transport._reply("问题")

    def test_proxy_restricted_to_loopback_and_uses_connect(self):
        self.transport.config["qianfan_proxy_url"] = "http://127.0.0.1:18080"
        response = MagicMock(status=200)
        response.read.return_value = b'{"choices":[{"message":{"content":"ok"}}]}'
        with patch("apps.companion.local_voice.http.client.HTTPSConnection") as factory:
            factory.return_value.getresponse.return_value = response
            self.transport._reply("test")
            factory.return_value.set_tunnel.assert_called_once_with("qianfan.baidubce.com", 443)
        self.transport.config["qianfan_proxy_url"] = "http://untrusted.example:80"
        with self.assertRaises(RuntimeError):
            self.transport._reply("test")

    def test_subprocess_uses_no_shell_and_no_cloud_credentials(self):
        with patch("apps.companion.local_voice.subprocess.Popen") as factory, patch("apps.companion.local_voice.os.killpg"):
            factory.return_value.returncode = 0
            self.transport._execute(self.transport._generation, [sys.executable, "-c", "pass"], "local_asr_timeout_s")
            _, kwargs = factory.call_args
            self.assertNotIn("BAIDU_QIANFAN_API_KEY", kwargs["env"])
            self.assertTrue(kwargs["start_new_session"])
            self.assertNotIn("shell", kwargs)

    def test_native_wave_is_owned_bit_exact_pcm_without_codec_or_resampling(self):
        for rate in (8000, 22050, 48000):
            self.messages.clear()
            with tempfile.TemporaryDirectory() as directory:
                filename = str(Path(directory) / "native.wav")
                original = b"\x00\x10\xff\x7f\x00\x80" * 173
                with wave.open(filename, "wb") as output:
                    output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
                    output.writeframes(original)
                with patch.object(self.transport._codec, "encode", side_effect=AssertionError("lossy encode")):
                    self.transport._play(self.transport._generation, filename)
            # The temporary WAV is gone; the queued PCM remains complete.
            self.assertEqual(self.messages, [PcmAudio(original, rate)])

    def test_wav_duration_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = str(Path(directory) / "large.wav")
            with wave.open(filename, "wb") as output:
                output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                output.writeframes(b"\0" * (16000 * 46 * 2))
            with self.assertRaises(ValueError):
                self.transport._play(self.transport._generation, filename)


if __name__ == "__main__":
    unittest.main()
