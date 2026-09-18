"""Local ASR/TTS subprocesses with text-only, bounded Qianfan HTTPS inference.

Commands exchange private temporary files, never shell fragments. Lightweight
clients call the resident speech worker; model inference is serialized.
"""
import http.client
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import threading
import time
import uuid
import wave
from urllib.parse import urlsplit

from .audio import OpusCodec, FRAME_BYTES, PcmAudio


class LocalVoiceTransport:
    def __init__(self, config, on_message, on_error):
        self.config = dict(config)
        self.on_message, self.on_error = on_message, on_error
        self._lock = threading.RLock()
        self._generation = 0
        self._closed = True
        self._pcm = bytearray()
        self._recording = False
        self._process = None
        self._worker = None
        self._codec = None
        self._http = None
        self._session = uuid.uuid4().hex

    @staticmethod
    def _command(value):
        if (not isinstance(value, list) or not value or len(value) > 64 or
                any(not isinstance(x, str) or not x or len(x) > 4096 or "\x00" in x for x in value) or
                not os.path.isabs(value[0]) or not os.access(value[0], os.X_OK)):
            raise ValueError("Local speech command requires an absolute executable and bounded argument list")
        return value

    def connect(self):
        worker_socket = self.config.get("local_speech_socket", "")
        if worker_socket:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
                    peer.settimeout(1)
                    peer.connect(worker_socket)
                    peer.sendall(b'{"operation":"health"}\n')
                    response = peer.recv(4096)
                    health = json.loads(response)
                    if not health.get("ok") or not health.get("ready"):
                        raise ValueError("Worker not ready")
            except (OSError, ValueError):
                raise ValueError("本地语音模型仍在加载，请稍后重试") from None
            if health.get("busy"):
                raise ValueError("本地模型仍在处理上一轮，请稍后重试")
        self._command(self.config.get("local_asr_command"))
        self._command(self.config.get("local_tts_command"))
        name = self.config.get("qianfan_token_env", "BAIDU_QIANFAN_API_KEY")
        token = os.environ.get(name, "")
        if not token or len(token) > 4096 or "\n" in token or "\r" in token:
            raise ValueError("Qianfan API key environment variable is missing or invalid")
        with self._lock:
            if not self._closed:
                raise RuntimeError("Local voice already connected")
            self._codec = OpusCodec()
            self._closed = False

    def _active(self, generation):
        return not self._closed and generation == self._generation

    def _emit(self, generation, value):
        with self._lock:
            if self._active(generation):
                if isinstance(value, dict):
                    value["session_id"] = self._session
                self.on_message(value)

    def send(self, value):
        with self._lock:
            if self._closed:
                raise RuntimeError("Local voice is closed")
            if isinstance(value, bytes):
                if self._recording:
                    pcm = self._codec.decode(value)
                    limit = int(min(60, self.config.get("max_listen_s", 15)) * 32000)
                    if len(self._pcm) + len(pcm) > limit + 3840:
                        raise ValueError("Local recording exceeds configured duration")
                    self._pcm.extend(pcm)
                return
            kind, state = value.get("type"), value.get("state")
            if kind == "hello":
                self._emit(self._generation, {"type": "hello", "audio_params": {
                    "format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60}})
            elif kind == "abort":
                self._cancel()
            elif kind == "listen" and state == "start":
                if self._worker and self._worker.is_alive():
                    raise RuntimeError("Previous local voice task is still stopping")
                self._cancel()
                self._codec.reset_decoder()
                self._recording = True
            elif kind == "listen" and state == "stop" and self._recording:
                self._recording = False
                pcm = bytes(self._pcm)
                self._pcm.clear()
                generation = self._generation
                self._worker = threading.Thread(target=self._run, args=(generation, pcm),
                                                name="companion-local-voice", daemon=True)
                self._worker.start()

    @staticmethod
    def _terminate(process):
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)

    def _cancel(self):
        self._generation += 1
        self._recording = False
        self._pcm.clear()
        self._terminate(self._process)
        if self._http:
            self._http.close()

    def close(self):
        with self._lock:
            self._closed = True
            self._cancel()
            if self._codec:
                self._codec.close()
                self._codec = None

    def _execute(self, generation, template, timeout_key, **values):
        command = [item.format(**values) for item in self._command(template)]
        with self._lock:
            if not self._active(generation):
                raise RuntimeError("Local voice cancelled")
            # Do not pass cloud credentials to model helpers.
            env = {key: os.environ[key] for key in ("PATH", "LANG", "LD_LIBRARY_PATH") if key in os.environ}
            self._process = process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, start_new_session=True)
        try:
            process.wait(timeout=min(120, max(1, self.config.get(timeout_key, 90))))
            if process.returncode:
                raise RuntimeError("Local speech model failed; check model installation")
        except subprocess.TimeoutExpired:
            self._terminate(process)
            raise RuntimeError("Local speech model timed out") from None
        finally:
            # A helper must not leave model children alive after its leader exits.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            with self._lock:
                if self._process is process:
                    self._process = None
        if not self._active(generation):
            raise RuntimeError("Local voice cancelled")

    def _reply(self, text):
        token = os.environ.get(self.config.get("qianfan_token_env", "BAIDU_QIANFAN_API_KEY"), "")
        payload = json.dumps({"model": self.config.get("qianfan_model", "ernie-4.5-turbo-32k"),
            "messages": [{"role": "system", "content": "请用自然口语中文回答，默认一到两句话、最多60个汉字，不使用Markdown。"},
                         {"role": "user", "content": text}], "max_tokens": 192,
            "stream": False}, ensure_ascii=False).encode("utf-8")
        proxy = self.config.get("qianfan_proxy_url", "")
        if proxy:
            parsed = urlsplit(proxy)
            if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") or
                    not parsed.port or parsed.username or parsed.password or parsed.path not in ("", "/") or
                    parsed.query or parsed.fragment):
                raise RuntimeError("本地语音：千帆代理配置无效")
            connection = http.client.HTTPSConnection(parsed.hostname, parsed.port, timeout=30)
            connection.set_tunnel("qianfan.baidubce.com", 443)
        else:
            connection = http.client.HTTPSConnection("qianfan.baidubce.com", timeout=30)
        with self._lock:
            if self._closed:
                connection.close()
                raise RuntimeError("Local voice cancelled")
            self._http = connection
        try:
            connection.request("POST", "/v2/chat/completions", body=payload,
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
            response = connection.getresponse()
            raw = response.read(65537)
            if response.status != 200 or len(raw) > 65536:
                raise RuntimeError("Qianfan request failed; check network, quota and API authorization")
            reply = json.loads(raw)["choices"][0]["message"]["content"]
            if not isinstance(reply, str) or not reply.strip() or len(reply) > 4096:
                raise ValueError("Invalid Qianfan reply")
            return reply.strip()[:120]
        except (OSError, ValueError, KeyError, IndexError, http.client.HTTPException):
            raise RuntimeError("Qianfan returned no usable reply") from None
        finally:
            connection.close()
            with self._lock:
                if self._http is connection:
                    self._http = None

    def _run(self, generation, pcm):
        stage = "录音"
        try:
            if not pcm:
                raise RuntimeError("No local microphone audio received")
            with tempfile.TemporaryDirectory(prefix="rtctrl-voice-") as directory:
                source, result, speech = [str(Path(directory) / name) for name in ("input.wav", "asr.json", "reply.wav")]
                with wave.open(source, "wb") as output:
                    output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                    output.writeframes(pcm)
                del pcm
                stage = "本地语音识别"
                self._execute(generation, self.config["local_asr_command"], "local_asr_timeout_s", input=source, output=result, text="")
                if Path(result).stat().st_size > 16384:
                    raise ValueError("Local ASR result too large")
                text = json.loads(Path(result).read_text(encoding="utf-8"))["text"]
                if not isinstance(text, str) or not text.strip() or len(text) > 4096:
                    raise RuntimeError("Local ASR did not recognize speech")
                self._emit(generation, {"type": "stt", "text": text.strip()})
                if not self._active(generation):
                    return
                stage = "千帆文字回答"
                reply = self._reply(text.strip())
                self._emit(generation, {"type": "llm", "text": reply, "emotion": "neutral"})
                stage = "本地语音合成"
                self._execute(generation, self.config["local_tts_command"], "local_tts_timeout_s", input=source, output=speech, text=reply)
                self._emit(generation, {"type": "tts", "state": "start"})
                self._emit(generation, {"type": "tts", "state": "sentence_start", "text": reply})
                stage = "本地音频输出"
                self._play(generation, speech)
                self._emit(generation, {"type": "tts", "state": "stop"})
        except Exception as error:
            with self._lock:
                if self._active(generation):
                    # Never surface response bodies, command arguments or user text.
                    self.on_error(stage + "失败或超时，请检查配置、模型和网络")

    def _play(self, generation, filename):
        with wave.open(filename, "rb") as source:
            rate = source.getframerate()
            if (source.getnchannels() != 1 or source.getsampwidth() != 2 or
                    rate not in (8000, 16000, 22050, 24000, 44100, 48000) or
                    source.getnframes() > rate * 45):
                raise ValueError("Unsupported or oversized synthesized WAV")
            # Own the bytes before the turn directory is removed. Playback uses
            # ALSA backpressure at the original rate, with no lossy codec stage.
            pcm = source.readframes(source.getnframes())
            audio = PcmAudio(pcm, rate)
            audio.validate()
            self._emit(generation, audio)
