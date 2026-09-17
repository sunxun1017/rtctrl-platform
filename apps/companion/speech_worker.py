"""Warm, serialized local speech models behind a private Unix socket."""
import argparse
import array
import json
import os
from pathlib import Path
import select
import signal
import socket
import stat
import sys
import threading
import wave

REQUEST_LIMIT = 16384


class SpeechWorker:
    def __init__(self, engine, socket_path, temp_root="/tmp"):
        self.engine = engine
        self.socket_path = Path(socket_path)
        self.temp_root = Path(temp_root).resolve()
        self.busy = threading.Lock()
        self.stop = threading.Event()
        self.server = None
        self.job = None

    def _path(self, value, input_file=False):
        if not isinstance(value, str) or len(value) > 4096:
            raise ValueError("Invalid speech path")
        path = Path(value)
        if not path.is_absolute() or path.name in ("", ".", ".."):
            raise ValueError("Invalid speech path")
        parent = path.parent
        info = parent.lstat()
        if (parent.parent != self.temp_root or not parent.name.startswith("rtctrl-voice-") or
                not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or
                stat.S_IMODE(info.st_mode) != 0o700 or parent.resolve() != parent):
            raise ValueError("Speech path must be a private turn directory")
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise ValueError("Invalid speech file")
            if input_file and info.st_size > 2 * 1024 * 1024:
                raise ValueError("Speech input too large")
        elif input_file:
            raise ValueError("Speech input missing")
        return path

    @staticmethod
    def _send(peer, value):
        try:
            peer.sendall(json.dumps(value).encode() + b"\n")
        except OSError:
            pass

    @staticmethod
    def _connected(peer):
        ready, _, _ = select.select([peer], [], [], 0)
        if not ready:
            return True
        try:
            return bool(peer.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT))
        except OSError:
            return False

    def _request(self, peer):
        peer.settimeout(2)
        payload = bytearray()
        while b"\n" not in payload:
            block = peer.recv(min(4096, REQUEST_LIMIT + 1 - len(payload)))
            if not block:
                raise ValueError("Incomplete request")
            payload.extend(block)
            if len(payload) > REQUEST_LIMIT:
                raise ValueError("Request too large")
        line, remainder = bytes(payload).split(b"\n", 1)
        if remainder:
            raise ValueError("One request per connection")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("Request must be object")
        return value

    def _process(self, peer, request):
        try:
            operation = request.get("operation")
            output = self._path(request.get("output"))
            if operation == "asr":
                source = self._path(request.get("input"), input_file=True)
                result = self.engine.recognize(source)
                if not isinstance(result, str) or len(result) > 4096:
                    raise ValueError("Invalid recognition result")
            elif operation == "tts":
                text = request.get("text")
                if not isinstance(text, str) or not text.strip() or len(text) > 120:
                    raise ValueError("Invalid synthesis text")
                result = self.engine.synthesize(text)
            else:
                raise ValueError("Unsupported operation")
            if self.stop.is_set() or not self._connected(peer):
                return
            self._path(str(output))
            # No parent recreation: cancelled turns must stay deleted.
            descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as target:
                if operation == "asr":
                    target.write(json.dumps({"text": result}, ensure_ascii=False).encode())
                else:
                    pcm, rate = result
                    if rate not in (8000, 16000, 22050, 24000, 44100, 48000) or len(pcm) > rate * 2 * 45:
                        raise ValueError("Invalid synthesized audio")
                    with wave.open(target, "wb") as wav:
                        wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
                        wav.writeframes(pcm)
            self._send(peer, {"ok": True})
        except Exception:
            self._send(peer, {"ok": False, "error": "local speech operation failed"})
        finally:
            peer.close()
            self.busy.release()

    def serve(self):
        self.socket_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Reclaim only an owned stale socket, never a live worker or another file.
        if self.socket_path.exists() or self.socket_path.is_symlink():
            info = self.socket_path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise ValueError("Refusing unrelated speech socket path")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(.3)
                try:
                    probe.connect(str(self.socket_path))
                except ConnectionRefusedError:
                    current = self.socket_path.lstat()
                    if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                        raise ValueError("Speech socket changed")
                    self.socket_path.unlink()
                else:
                    raise ValueError("Speech worker already running")
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        owned_socket = self.socket_path.lstat()
        self.server.listen(4)
        self.server.settimeout(.2)
        print("speech worker ready", flush=True)
        try:
            while not self.stop.is_set():
                try:
                    peer, _ = self.server.accept()
                except socket.timeout:
                    continue
                try:
                    request = self._request(peer)
                    if request.get("operation") == "health":
                        self._send(peer, {"ok": True, "ready": True, "busy": self.busy.locked()})
                        peer.close()
                    elif request.get("operation") not in ("asr", "tts"):
                        raise ValueError("Unsupported operation")
                    elif not self.busy.acquire(blocking=False):
                        self._send(peer, {"ok": False, "error": "local speech worker busy"})
                        peer.close()
                    else:
                        self.job = threading.Thread(target=self._process, args=(peer, request), daemon=True)
                        self.job.start()
                except Exception:
                    self._send(peer, {"ok": False, "error": "invalid speech request"})
                    peer.close()
        finally:
            self.server.close()
            try:
                current = self.socket_path.lstat()
                if (current.st_dev, current.st_ino, current.st_uid) == (owned_socket.st_dev, owned_socket.st_ino, os.getuid()):
                    self.socket_path.unlink()
            except FileNotFoundError:
                pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--tts-kind", choices=("vits", "vits_aishell3"), default="vits")
    parser.add_argument("--sid", type=int, default=0)
    args = parser.parse_args()
    try:
        engine = SherpaEngine(Path(args.root), args.tts_kind, args.sid)
        worker = SpeechWorker(engine, args.socket)
        signal.signal(signal.SIGTERM, lambda *_: worker.stop.set())
        signal.signal(signal.SIGINT, lambda *_: worker.stop.set())
        worker.serve()
    except KeyboardInterrupt:
        pass
    except Exception:
        print("speech worker initialization failed", file=sys.stderr, flush=True)
        return 1
    return 0


# SherpaEngine is initialized only from main; tests use a small fake engine.

class SherpaEngine:
    def __init__(self, root, tts_kind="vits", sid=0):
        if tts_kind not in ("vits", "vits_aishell3") or not 0 <= sid < 174:
            raise ValueError("Unsupported local voice model or speaker")
        sys.path.insert(0, str(root / "python"))
        import sherpa_onnx
        asr_root = root / "sherpa-onnx-zipformer-ctc-small-zh-int8-2025-07-16"
        tts_root = root / "vits-icefall-zh-aishell3"
        self.asr = sherpa_onnx.OfflineRecognizer.from_zipformer_ctc(
            model=str(asr_root / "model.int8.onnx"), tokens=str(asr_root / "tokens.txt"), num_threads=2)
        self.tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(tts_root / "model.onnx"), lexicon=str(tts_root / "lexicon.txt"),
                tokens=str(tts_root / "tokens.txt")), num_threads=2),
            rule_fsts=",".join(str(tts_root / name) for name in
                              ("date.fst", "number.fst", "phone.fst", "new_heteronym.fst"))))
        self.sid = sid

    def recognize(self, path):
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            with wave.open(source, "rb") as wav:
                if (wav.getnchannels() != 1 or wav.getsampwidth() != 2 or
                        wav.getframerate() != 16000 or wav.getnframes() > 16000 * 60):
                    raise ValueError("Unsupported recognition WAV")
                samples = array.array("h", wav.readframes(wav.getnframes()))
        if sys.byteorder != "little":
            samples.byteswap()
        stream = self.asr.create_stream()
        stream.accept_waveform(16000, [value / 32768 for value in samples])
        self.asr.decode_stream(stream)
        text = stream.result.text
        del stream
        return text

    def synthesize(self, text):
        generated = self.tts.generate(text, sid=self.sid, speed=1.0)
        if len(generated.samples) > generated.sample_rate * 45:
            raise ValueError("Synthesized reply too long")
        pcm = array.array("h", (max(-32768, min(32767, int(value * 32767))) for value in generated.samples))
        if sys.byteorder != "little":
            pcm.byteswap()
        return pcm.tobytes(), generated.sample_rate


if __name__ == "__main__":
    sys.exit(main())
