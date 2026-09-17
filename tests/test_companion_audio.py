"""Audio contract tests: fake processes and pipes, never real sound devices."""
import importlib.util
import os
from pathlib import Path
import select
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
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
