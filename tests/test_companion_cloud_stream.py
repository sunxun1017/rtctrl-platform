"""Streaming cloud contract tests: no network, recordings, or model execution."""
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.companion.cloud_stream import content_deltas, SentenceBuffer
from apps.companion.local_voice import LocalVoiceTransport
from apps.companion.audio import PcmStreamChunk


def event(text):
    return ("data: " + json.dumps({"choices": [{"delta": {"content": text}}]}) + "\n\n").encode()


class CloudStreamTests(unittest.TestCase):
    def test_sse_comments_role_usage_and_completion(self):
        raw = b": ping\r\n\r\n" + event("") + event("你好") + event("世界。")
        raw += b'data: {"choices": []}\n\ndata: [DONE]\n\n'
        self.assertEqual(list(content_deltas(io.BytesIO(raw), lambda: True)), ["你好", "世界。"])

    def test_truncation_and_bounded_events(self):
        for raw in (event("文本"), b"data: " + b"x" * 8200 + b"\n", b"data: invalid\n\n"):
            with self.assertRaises(ValueError):
                list(content_deltas(io.BytesIO(raw), lambda: True))

    def test_cancelled_parser_does_not_read(self):
        self.assertEqual(list(content_deltas(io.BytesIO(b"invalid"), lambda: False)), [])

    def test_split_waits_for_natural_clause(self):
        splitter = SentenceBuffer()
        self.assertEqual(splitter.feed("你好，"), [])
        self.assertEqual(splitter.feed("今天天气不错。后面"), ["你好，今天天气不错。"])
        self.assertEqual(splitter.feed("还没说完"), [])
        self.assertEqual(splitter.feed("", final=True), ["后面还没说完"])

    def test_long_clause_and_bounded_unpunctuated(self):
        splitter = SentenceBuffer()
        self.assertEqual(splitter.feed("这是一个稍微长一点但是已经完整的短句，"), ["这是一个稍微长一点但是已经完整的短句，"])
        with self.assertRaises(ValueError):splitter.feed("字" * 4097)

    def transport(self):
        messages = []
        t = LocalVoiceTransport({}, messages.append, lambda error: None)
        t._closed = False
        return t, messages

    def test_producer_and_synthesis_overlap_one_final(self):
        t, messages = self.transport()
        consuming = threading.Event()
        synthesized = []
        def deltas(generation, text, cancelled):
            yield "第一句话足够完整。"
            self.assertTrue(consuming.wait(1), "TTS waits for all cloud text")
            yield "第二句话也很完整。"
        def synth(generation, text, stream):
            synthesized.append(text)
            consuming.set()
            if not stream["playing"]:
                stream["playing"] = stream["first_pcm"] = True
                stream["rate"] = 44100
                t._emit(generation, {"type": "tts", "state": "start"})
            t._emit(generation, PcmStreamChunk(b"xx", 44100, False))
        with patch.object(t, "_reply_deltas", side_effect=deltas), patch.object(t, "_stream_tts", side_effect=synth):
            t._stream_reply(0, "固定测试")
        self.assertEqual(len(synthesized), 2)
        self.assertEqual(sum(isinstance(m, PcmStreamChunk) and m.end for m in messages), 1)
        self.assertEqual(sum(isinstance(m, dict) and m.get("state") == "start" for m in messages), 1)
        names = [name for m in messages if isinstance(m, dict) and m.get("type") == "latency" for name in m["values"]]
        self.assertEqual(names.count("cloud_first_token_ms"), 1)
        self.assertEqual(names.count("cloud_first_sentence_ms"), 1)
        self.assertEqual(names.count("cloud_ms"), 1)

    def test_cancel_unblocks_full_producer_queue(self):
        t, messages = self.transport()
        def deltas(generation, text, cancelled):
            for _ in range(100):yield "这是一句完整的话。"
        def synth(generation, text, stream):
            t._generation += 1
        with patch.object(t, "_reply_deltas", side_effect=deltas), patch.object(t, "_stream_tts", side_effect=synth):
            t._stream_reply(0, "固定测试")
        self.assertFalse(any(isinstance(m, PcmStreamChunk) and m.end for m in messages))
        self.assertFalse(any(job.name == "companion-cloud-stream" for job in threading.enumerate()))

    def test_cancel_shutdowns_detached_http_response_socket(self):
        t, messages = self.transport()
        reading, shutdown = threading.Event(), threading.Event()
        class NetworkSocket:
            def shutdown(self, how):shutdown.set()
        class Response:
            status = 200
            def readline(self, count):
                reading.set()
                shutdown.wait(1)
                return b""
        class Connection:
            sock = None
            def connect(self):self.sock = NetworkSocket()
            def request(self, *args, **kwargs):pass
            def getresponse(self):
                self.sock = None  # HTTP Connection:close transfers socket to response
                return Response()
            def close(self):pass
        errors = []
        def read():
            try:list(t._reply_deltas(0, "固定文本", threading.Event()))
            except ValueError:errors.append(True)
        with patch("apps.companion.local_voice.http.client.HTTPSConnection", return_value=Connection()):
            job = threading.Thread(target=read)
            job.start()
            self.assertTrue(reading.wait(1))
            t._cancel()
            job.join(1)
            self.assertFalse(job.is_alive())
            self.assertTrue(shutdown.is_set())
            self.assertIsNone(t._http_abort)
            self.assertIsNone(t._http)

    def test_producer_failure_never_emits_success_end(self):
        t, messages = self.transport()
        def deltas(*args):
            raise ValueError("server private error")
            yield ""
        with patch.object(t, "_reply_deltas", side_effect=deltas):
            with self.assertRaisesRegex(RuntimeError, "Cloud streaming failed"):
                t._stream_reply(0, "固定测试")
        self.assertFalse(any(isinstance(m, PcmStreamChunk) and m.end for m in messages))


if __name__ == "__main__":unittest.main()
