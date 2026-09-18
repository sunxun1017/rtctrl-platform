"""Audio contract tests: fake processes and pipes, never real sound devices."""
import importlib.util
import os
from pathlib import Path
import select
import sys
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("companion_audio_under_test", ROOT / "apps/companion/audio.py")
audio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audio)


class FakeCodec:
    def __init__(self, decoder_sample_rate=16000):
        self.decoder_sample_rate = decoder_sample_rate
        self.closed = False
        self.resets = 0

    def decode(self, packet):
        return packet * 100

    def reset_decoder(self):
        self.resets += 1

    def close(self):
        self.closed = True


class FakeEchoCanceller:
    def __init__(self, config):
        self.captured = []
        self.rendered = []
        self.closed = False
        self.resets = 0
    def process(self, pcm, captured_at=None):
        self.captured.append((pcm, captured_at))
        return pcm
    def render(self, pcm, rate, submitted_at=None):
        self.rendered.append((pcm, rate, submitted_at))
    def reset_reference(self): self.resets += 1
    def close(self): self.closed = True


class FakeProcess:
    def __init__(self, capture):
        read_fd, write_fd = os.pipe()
        self.returncode = None
        self.terminated = False
        self.stdin = None if capture else os.fdopen(write_fd, "wb", buffering=0)
        self.stdout = os.fdopen(read_fd, "rb", buffering=0) if capture else None
        self.peer = os.fdopen(write_fd, "wb", buffering=0) if capture else os.fdopen(read_fd, "rb", buffering=0)

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode

    def cleanup(self):
        for stream in (self.stdin, self.stdout, self.peer):
            if stream:
                stream.close()


def eventually(predicate, seconds=1):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition not reached before timeout")


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.processes = []
        self.patchers = [mock.patch.object(audio, "OpusCodec", FakeCodec),
                         mock.patch.object(audio, "prerequisites", return_value={"arecord": "x", "aplay": "x", "libopus": "x"}),
                         mock.patch.object(audio.shutil, "which", return_value="x"),
                         mock.patch.object(audio.subprocess, "Popen", side_effect=self.spawn)]
        for patcher in self.patchers:
            patcher.start()
        self.errors = []
        self.io = audio.AudioIO({}, on_error=self.errors.append)

    def spawn(self, command, **kwargs):
        self.assertNotIn("shell", kwargs)
        process = FakeProcess(command[0] == "arecord")
        self.processes.append((command, process))
        return process

    def tearDown(self):
        self.io.stop()
        for _, process in self.processes:
            process.cleanup()
        for patcher in reversed(self.patchers):
            patcher.stop()

    def enable_fake_aec(self):
        self.io.stop()
        package = mock.patch.object(audio, "__package__", "apps.companion")
        bridge = mock.patch("apps.companion.aec.EchoCanceller", FakeEchoCanceller)
        specification = mock.patch.object(audio, "__spec__", None)
        specification.start()
        self.addCleanup(specification.stop)
        package.start();bridge.start()
        self.addCleanup(package.stop);self.addCleanup(bridge.stop)
        self.io = audio.AudioIO({"aec_enabled": True}, on_error=self.errors.append)
        return self.io._aec

    def test_aec_pause_keeps_capture_and_start_reuses_with_new_callback(self):
        echo = self.enable_fake_aec()
        first, second = [], []
        self.io.start(first.append)
        capture = self.io._capture
        worker = self.io._capture_thread
        frame = b"\x01\0" * audio.FRAME_SAMPLES
        capture.peer.write(frame)
        eventually(lambda: len(first) == 1)
        self.io.pause_capture()
        capture.peer.write(frame)
        eventually(lambda: len(echo.captured) == 2)
        self.assertEqual(len(first), 1)
        self.assertFalse(capture.terminated)
        self.assertTrue(worker.is_alive())
        self.io.start(second.append)
        self.assertIs(self.io._capture, capture)
        self.assertIs(self.io._capture_thread, worker)
        capture.peer.write(frame)
        eventually(lambda: len(second) == 1)
        self.assertEqual(first, [frame]);self.assertEqual(second, [frame])
        self.assertEqual(len(self.processes), 1)

    def test_aec_inflight_old_frame_not_delivered_to_new_callback(self):
        echo = self.enable_fake_aec()
        entered, proceed = threading.Event(), threading.Event()
        original_process = echo.process
        def blocked_process(pcm, captured_at=None):
            entered.set()
            if not proceed.wait(1):
                raise RuntimeError("test barrier timed out")
            return original_process(pcm, captured_at)
        first, second = [], []
        old_frame = b"\x01\0" * audio.FRAME_SAMPLES
        new_frame = b"\x02\0" * audio.FRAME_SAMPLES
        with mock.patch.object(echo, "process", side_effect=blocked_process):
            self.io.start(first.append)
            capture = self.io._capture
            capture.peer.write(old_frame)
            try:
                self.assertTrue(entered.wait(1))
                self.io.pause_capture()
                self.io.start(second.append)
            finally:
                proceed.set()
            eventually(lambda: len(echo.captured) == 1)
            capture.peer.write(new_frame)
            eventually(lambda: len(second) == 1)
        self.assertEqual(first, [])
        self.assertEqual(second, [new_frame])
        self.assertIs(self.io._capture, capture)
        self.assertEqual(self.errors, [])

    def test_aec_stop_closes_and_restart_rebuilds_context(self):
        original = self.enable_fake_aec()
        self.io.start(lambda pcm: None)
        old_capture = self.io._capture
        self.io.stop()
        self.assertTrue(original.closed)
        self.assertIsNone(self.io._aec)
        self.io.start(lambda pcm: None)
        self.assertIsNot(self.io._aec, original)
        self.assertFalse(self.io._aec.closed)
        self.assertIsNot(self.io._capture, old_capture)
        self.assertEqual(self.errors, [])

    def test_aec_reference_matches_actual_playback_bytes(self):
        echo = self.enable_fake_aec()
        first, second = b"\x01\x02" * 111, b"\xfe\xff" * 71
        self.io.play_pcm_stream(audio.PcmStreamChunk(first, 44100))
        eventually(lambda: len(self.processes) == 1)
        process = self.processes[0][1]
        self.assertEqual(process.peer.read(len(first)), first)
        eventually(lambda: sum(len(x[0]) for x in echo.rendered) == len(first))
        eventually(lambda: not self.io._inflight)
        self.io.play_pcm_stream(audio.PcmStreamChunk(second, 44100))
        self.assertEqual(process.peer.read(len(second)), second)
        eventually(lambda: sum(len(x[0]) for x in echo.rendered) == len(first)+len(second))
        self.assertEqual(b"".join(x[0] for x in echo.rendered), first+second)
        self.assertTrue(all(x[1] == 44100 and x[2] > 0 for x in echo.rendered))
        before = echo.resets
        self.io.interrupt()
        self.assertEqual(echo.resets, before+1)
        self.assertEqual(self.errors, [])

    def test_stream_chunks_reuse_process_exact_bytes_and_end_drain(self):
        first, second = b"\x01\x02" * 111, b"\xfe\xff" * 71
        self.io.play_pcm_stream(audio.PcmStreamChunk(first, 44100))
        eventually(lambda: len(self.processes) == 1)
        command, process = self.processes[0]
        self.assertEqual(command[command.index("-r") + 1], "44100")
        self.assertEqual(process.peer.read(len(first)), first)
        eventually(lambda: self.io.first_write_monotonic > 0)
        stamp = self.io.first_write_monotonic
        eventually(lambda: not self.io._inflight)
        self.assertTrue(self.io.playback_busy())
        self.assertFalse(process.stdin.closed)
        self.io.play_pcm_stream(audio.PcmStreamChunk(second, 44100))
        self.assertEqual(process.peer.read(len(second)), second)
        self.io.play_pcm_stream(audio.PcmStreamChunk(b"", 44100, True))
        eventually(lambda: process.stdin.closed)
        self.assertEqual(len(self.processes), 1)
        self.assertEqual(self.io.first_write_monotonic, stamp)
        self.assertTrue(self.io.playback_busy())
        process.returncode = 0
        eventually(lambda: not self.io.playback_busy())
        self.assertEqual(self.errors, [])

    def test_stream_interrupt_clears_state_and_new_utterance_timestamp(self):
        self.io.play_pcm_stream(audio.PcmStreamChunk(b"\0\1" * 8, 8000))
        eventually(lambda: self.io.first_write_monotonic > 0)
        old = self.processes[0][1]
        self.io.interrupt()
        self.assertTrue(old.terminated)
        self.assertFalse(self.io.playback_busy())
        self.assertEqual(self.io.first_write_monotonic, 0)
        self.io.play_pcm_stream(audio.PcmStreamChunk(b"\2\3", 16000, True))
        eventually(lambda: len(self.processes) == 2)
        process = self.processes[-1][1]
        self.assertEqual(process.peer.read(2), b"\2\3")
        eventually(lambda: process.stdin.closed)
        process.returncode = 0
        eventually(lambda: not self.io.playback_busy())

    def test_stream_missing_end_errors_and_reaps(self):
        self.io.play_pcm_stream(audio.PcmStreamChunk(b"\0\0", 8000))
        eventually(lambda: len(self.processes) == 1 and not self.io._inflight)
        process = self.processes[0][1]
        with self.io._lock:
            self.io._stream_deadline = time.monotonic() - 20
            self.io._play_until = time.monotonic() - 20
        eventually(lambda: bool(self.errors))
        self.assertIn("timed out", self.errors[0])
        self.assertTrue(process.terminated)
        self.assertFalse(self.io._stream_open)
        self.assertFalse(self.io.playback_busy())

    def test_stream_validation_limits_and_interleaving(self):
        for chunk in (audio.PcmStreamChunk(b"",8000), audio.PcmStreamChunk(b"x",8000),
                      audio.PcmStreamChunk(b"xx",8000,1), audio.PcmStreamChunk(b"xx",True)):
            with self.assertRaises(ValueError): self.io.play_pcm_stream(chunk)
        # Hold consumer to validate queue and cumulative budget deterministically.
        with self.io._lock:
            self.io.play_pcm_stream(audio.PcmStreamChunk(b"xx",8000))
            with self.assertRaises(audio.AudioError): self.io.play_pcm_stream(audio.PcmStreamChunk(b"xx",16000))
            with self.assertRaises(audio.AudioError): self.io.play(b"opus")
            with self.assertRaises(audio.AudioError): self.io.play_pcm(audio.PcmAudio(b"xx",8000))
            for _ in range(15): self.io.play_pcm_stream(audio.PcmStreamChunk(b"xx",8000))
            with self.assertRaisesRegex(audio.AudioError,"queue"): self.io.play_pcm_stream(audio.PcmStreamChunk(b"xx",8000))
            self.io.interrupt()
            self.io.play_pcm_stream(audio.PcmStreamChunk(bytes(8000*2*45),8000))
            with self.assertRaisesRegex(audio.AudioError,"45 seconds"): self.io.play_pcm_stream(audio.PcmStreamChunk(b"xx",8000))
            self.io.play_pcm_stream(audio.PcmStreamChunk(b"",8000,True))
            with self.assertRaises(audio.AudioError): self.io.play_pcm_stream(audio.PcmStreamChunk(b"xx",8000))
            self.io.interrupt()

    def test_pcm_native_rate_exact_bytes_and_wait_for_drain(self):
        pcm = b"\x00\x10\xff\x7f\x00\x80" * 71
        with mock.patch.object(FakeCodec, "decode", side_effect=AssertionError("lossy decode")):
            self.io.play_pcm(audio.PcmAudio(pcm, 8000))
            eventually(lambda: len(self.processes) == 1)
            command, process = self.processes[0]
            self.assertEqual(command[command.index("-r") + 1], "8000")
            self.assertEqual(process.peer.read(len(pcm)), pcm)
            eventually(lambda: process.stdin.closed)
            self.assertTrue(self.io.playback_busy())
            process.returncode = 0
            eventually(lambda: not self.io.playback_busy())
        self.assertEqual(self.errors, [])

    def test_pcm_drain_allows_audio_buffered_in_large_pipe(self):
        clock = [100.0]
        with mock.patch.object(audio, "time", mock.Mock(monotonic=lambda: clock[0])), \
                mock.patch.object(audio.os, "write", side_effect=lambda fd, data: len(data)):
            self.io.play_pcm(audio.PcmAudio(b"x\0" * (8000 * 8), 8000))
            eventually(lambda: len(self.processes) == 1 and self.processes[0][1].stdin.closed)
            process = self.processes[0][1]
            clock[0] = 104.0
            time.sleep(.05)
            self.assertEqual(self.errors, [])
            self.assertTrue(self.io.playback_busy())
            clock[0] = 108.5
            process.returncode = 0
            eventually(lambda: not self.io.playback_busy())

    def test_pcm_interrupt_discards_blocked_old_audio(self):
        self.io.play_pcm(audio.PcmAudio(b"x\0" * 80000, 8000))
        eventually(lambda: len(self.processes) == 1)
        old = self.processes[0][1]
        self.io.interrupt()
        self.assertTrue(old.terminated)
        self.io.play_pcm(audio.PcmAudio(b"y\0" * 80, 8000))
        eventually(lambda: len(self.processes) == 2)
        new = self.processes[1][1]
        self.assertEqual(new.peer.read(160), b"y\0" * 80)
        eventually(lambda: new.stdin.closed)
        new.returncode = 0
        eventually(lambda: not self.io.playback_busy())
        self.assertEqual(self.errors, [])

    def test_pcm_bounds_and_no_overlapping_utterances(self):
        for packet in (audio.PcmAudio(b"x", 8000), audio.PcmAudio(b"xx", True),
                       audio.PcmAudio(b"xx", 12345), audio.PcmAudio(b"xx" * (8000 * 45 + 1), 8000)):
            with self.assertRaises(ValueError):
                self.io.play_pcm(packet)
        with mock.patch.object(self.io, "_ensure_started"):
            self.io.play_pcm(audio.PcmAudio(b"xx", 8000))
            with self.assertRaises(audio.AudioError):
                self.io.play_pcm(audio.PcmAudio(b"yy", 8000))

    def test_construct_does_not_open_microphone(self):
        self.assertEqual(self.processes, [])
        self.assertFalse(self.io.playback_busy())

    def test_capture_reassembles_partial_reads_and_stops_separately(self):
        frames = []
        self.io.start(frames.append)
        capture = self.processes[0][1]
        capture.peer.write(b"a" * 17)
        time.sleep(0.02)
        self.assertEqual(frames, [])
        capture.peer.write(b"b" * (audio.FRAME_BYTES - 17))
        eventually(lambda: len(frames) == 1)
        self.assertEqual(frames[0], b"a" * 17 + b"b" * (audio.FRAME_BYTES - 17))
        self.io.stop_capture()
        self.assertTrue(capture.terminated)
        self.io.play(b"x")
        eventually(lambda: len(self.processes) == 2)
        self.assertEqual(self.errors, [])

    def test_capture_eof_reports_error_and_reaps_process(self):
        self.io.start(lambda frame: None)
        capture = self.processes[0][1]
        capture.peer.close()
        eventually(lambda: bool(self.errors))
        self.assertIn("closed its stream", self.errors[0])
        self.assertTrue(capture.terminated)

    def test_play_without_microphone_interrupt_and_new_generation(self):
        self.io.play(b"x")
        eventually(lambda: len(self.processes) == 1)
        command, process = self.processes[0]
        self.assertEqual(command[0], "aplay")
        eventually(lambda: bool(select.select([process.peer], [], [], 0)[0]))
        self.assertEqual(process.peer.read(100), b"x" * 100)
        self.assertTrue(self.io.playback_busy())
        self.io.interrupt()
        self.assertTrue(process.terminated)
        self.assertFalse(self.io.playback_busy())
        self.io.play(b"y")
        eventually(lambda: len(self.processes) == 2)
        next_process = self.processes[1][1]
        eventually(lambda: bool(select.select([next_process.peer], [], [], 0)[0]))
        self.assertEqual(next_process.peer.read(100), b"y" * 100)

    def test_interrupt_discards_inflight_packet_waiting_for_writable_pipe(self):
        real_select = select.select
        writable = threading.Event()

        def gated_select(readers, writers, errors, timeout):
            if writers and not writable.is_set():
                return [], [], []
            return real_select(readers, writers, errors, timeout)

        with mock.patch.object(audio.select, "select", side_effect=gated_select):
            self.io.play(b"old")
            eventually(lambda: self.io._inflight)
            old = self.processes[0][1]
            self.io.interrupt()
            self.assertTrue(old.terminated)
            self.io.play(b"new")
            writable.set()
            eventually(lambda: len(self.processes) == 2)
            new = self.processes[1][1]
            eventually(lambda: bool(real_select([new.peer], [], [], 0)[0]))
            self.assertEqual(new.peer.read(300), b"new" * 100)
            self.assertEqual(old.peer.read(), b"")

    def test_playback_child_failure_is_reported_when_queue_empty(self):
        self.io.play(b"x")
        eventually(lambda: len(self.processes) == 1)
        self.processes[0][1].returncode = 1
        eventually(lambda: bool(self.errors))
        self.assertIn("aplay exited", self.errors[0])

    def test_queue_bound_is_explicit_and_interrupt_clears_it(self):
        self.io = audio.AudioIO({"playback_queue_frames": 1})
        with mock.patch.object(self.io, "_ensure_started"):
            self.io.play(b"x")
            with self.assertRaisesRegex(audio.AudioError, "queue is full"):
                self.io.play(b"y")
            self.io.interrupt()
            self.io.play(b"z")
            generation, packet = self.io._queue.get_nowait()
            self.assertEqual((generation, packet), (1, b"z"))

    def test_missing_dependencies_are_actionable(self):
        with mock.patch.object(audio, "prerequisites", return_value={"aplay": None}):
            with self.assertRaisesRegex(audio.AudioError, "aplay"):
                self.io.play(b"x")

    def test_device_is_a_single_argument(self):
        self.io = audio.AudioIO({"capture_device": "hw:0,0; echo unsafe"})
        self.io.start(lambda frame: None)
        self.assertEqual(self.processes[0][0][3], "hw:0,0; echo unsafe")

    def test_negotiated_output_rate_preserves_capture_rate(self):
        self.io.configure_output(24000)
        self.io.start(lambda frame: None)
        capture_command = self.processes[0][0]
        self.assertEqual(capture_command[capture_command.index("-r") + 1], "16000")
        self.io.play(b"x")
        eventually(lambda: len(self.processes) == 2)
        playback_command = self.processes[1][0]
        self.assertEqual(playback_command[playback_command.index("-r") + 1], "24000")
        self.assertEqual(self.io._codec.decoder_sample_rate, 24000)
        with self.assertRaisesRegex(audio.AudioError, "Interrupt"):
            self.io.configure_output(48000)
        codec = self.io._codec
        self.io.interrupt()
        self.io.configure_output(48000)
        self.assertTrue(codec.closed)
        self.assertEqual(self.io._codec.decoder_sample_rate, 48000)

    def test_output_sample_rate_validation(self):
        for rate in (0, 22050, "24000", 24000.0, True):
            with self.assertRaises(ValueError):
                self.io.configure_output(rate)
            with self.assertRaises(ValueError):
                audio.AudioIO({"output_sample_rate": rate})
        configured = audio.AudioIO({"output_sample_rate": 24000})
        self.assertEqual(configured.output_sample_rate, 24000)
        configured.stop()

    def test_validation(self):
        for value in (0, 201, True, "16"):
            with self.assertRaises(ValueError):
                audio.AudioIO({"playback_queue_frames": value})
        for packet in (b"", b"x" * 4097, "text"):
            with self.assertRaises(ValueError):
                self.io.play(packet)

    def test_stop_is_idempotent_and_threads_exit(self):
        self.io.start(lambda frame: None)
        worker = self.io._capture_thread
        output = self.io._output_thread
        codec = self.io._codec
        self.io.stop()
        self.io.stop()
        self.assertFalse(worker.is_alive())
        self.assertFalse(output.is_alive())
        self.assertTrue(codec.closed)
        self.assertEqual(self.errors, [])


class CodecTests(unittest.TestCase):
    @unittest.skipUnless(audio.ctypes.util.find_library("opus"), "libopus not installed")
    def test_decode_negotiated_sample_rate(self):
        for rate in audio.OUTPUT_SAMPLE_RATES:
            codec = audio.OpusCodec(decoder_sample_rate=rate)
            try:
                packet = codec.encode(bytes(audio.FRAME_BYTES))
                self.assertEqual(len(codec.decode(packet)), rate * 60 // 1000 * 2)
            finally:
                codec.close()

    @unittest.skipUnless(audio.ctypes.util.find_library("opus"), "libopus not installed")
    def test_real_libopus_roundtrip_and_closed_validation(self):
        codec = audio.OpusCodec()
        try:
            packet = codec.encode(bytes(audio.FRAME_BYTES))
            self.assertLess(len(packet), audio.FRAME_BYTES)
            self.assertEqual(len(codec.decode(packet)), audio.FRAME_BYTES)
            codec.reset_decoder()
            with self.assertRaises(ValueError):
                codec.encode(b"short")
            with self.assertRaises(ValueError):
                codec.decode(b"")
        finally:
            codec.close()
        codec.close()
        with self.assertRaises(audio.AudioError):
            codec.encode(bytes(audio.FRAME_BYTES))
        with self.assertRaises(audio.AudioError):
            codec.decode(b"x")


if __name__ == "__main__":
    unittest.main()
