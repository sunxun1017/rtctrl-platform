"""Serialized companion state machine; all device work stays outside realtime control."""
import json
import queue
import struct
import threading
import time

AUDIO_PARAMS = {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60}
SILENCE_FRAME = bytes(1920)
SILENCE_FRAME_INTERVAL = 0.06
SILENCE_TAIL_FRAMES = 20
EMOTIONS = {"neutral", "happy", "sad", "angry", "surprised", "excited", "thinking", "sleepy"}

class Companion:
    def __init__(self, config, audio_factory=None, codec_factory=None, transport_factory=None):
        self.config = config
        self.audio_factory = audio_factory
        self.codec_factory = codec_factory
        self.transport_factory = transport_factory
        self.events = queue.Queue(maxsize=48)
        self.overflow = threading.Event()
        self.stopping = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.audio = self.codec = self.transport = None
        self.generation = 0
        self.capture_epoch = 0
        self.turn_audio_frames_sent = 0
        self.turn_audio_frames_received = 0
        self.silence_remaining = 0
        self.silence_due = 0.
        self.session = ""
        self.deadline = 0.
        self.demo_due = 0.
        self.demo_phase = 0
        self.tts_ended = False
        self.accept_audio = False
        self.data = {
            "state": "offline", "emotion": "neutral", "transcript": "", "reply": "",
            "error": "", "connected": False, "muted": True, "voice_progress": "idle",
            "face": {"available": False, "reason": "尚未连接视觉服务"},
            "metrics": {"audio_frames_sent": 0, "audio_frames_received": 0, "queue_overflows": 0,
                        "capture_peak_amplitude": 0},
            "capabilities": {"mode": config["mode"], "voice": "push-to-talk",
                "wake_word": False, "aec": False, "automatic_barge_in": False,
                "actuator_control": False, "face": "external-read-only"},
        }

    def start(self):
        self.thread = threading.Thread(target=self._run, name="companion", daemon=True)
        self.thread.start()

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.data))

    def _set(self, **values):
        with self.lock:
            self.data.update(values)

    def post(self, kind, payload=None, generation=None):
        try:
            self.events.put_nowait((kind, payload, generation, None))
        except queue.Full:
            self.overflow.set()

    def action(self, action, timeout=12):
        result = queue.Queue(maxsize=1)
        try:
            self.events.put(("action", action, None, result), timeout=.2)
        except queue.Full:
            raise ValueError("设备繁忙，请稍后重试")
        try:
            ok, value = result.get(timeout=timeout)
        except queue.Empty:
            raise ValueError("操作超时，请查看当前状态")
        if not ok:
            raise ValueError(value)
        return value

    def close(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=20)
            if self.thread.is_alive():
                raise RuntimeError("companion shutdown timed out")

    def _run(self):
        try:
            while not self.stopping.is_set():
                if self.overflow.is_set():
                    self.overflow.clear()
                    with self.lock:
                        self.data["metrics"]["queue_overflows"] += 1
                    self._fail("处理队列已满，会话已停止；请降低负载后重新连接")
                try:
                    wait = .05
                    if self.silence_remaining:
                        wait = min(wait, max(0., self.silence_due - time.monotonic()))
                    kind, payload, generation, result = self.events.get(timeout=wait)
                except queue.Empty:
                    self._safe_tick()
                    continue
                try:
                    if generation is not None and generation != self.generation:
                        continue
                    if kind == "action":
                        self._action(payload)
                    elif kind == "message":
                        self._message(payload)
                    elif kind == "pcm":
                        if self.data["state"] == "listening" and not self.data["muted"] and payload[0] == self.capture_epoch:
                            pcm = payload[1]
                            peak = max((abs(value[0]) for value in struct.iter_unpack(
                                "<h", pcm[:len(pcm) // 2 * 2])), default=0)
                            with self.lock:
                                self.data["metrics"]["capture_peak_amplitude"] = max(
                                    self.data["metrics"]["capture_peak_amplitude"], peak)
                            self.transport.send(self.codec.encode(pcm))
                            self.turn_audio_frames_sent += 1
                            with self.lock:
                                self.data["metrics"]["audio_frames_sent"] += 1
                    elif kind == "error":
                        self._fail(str(payload))
                    elif kind == "face":
                        self._set(face=payload)
                    if result:
                        result.put((True, self.snapshot()))
                except ValueError as exc:
                    if result:
                        result.put((False, str(exc)))
                    else:
                        self._fail("后端协议或音频数据无效")
                except Exception:
                    self._fail("设备或网络操作失败，请检查音频设备、依赖和后端配置")
                    if result:
                        result.put((False, self.data["error"]))
                self._safe_tick()
        finally:
            self._release()
            self._set(state="offline", connected=False)

    def _safe_tick(self):
        try:
            self._tick()
        except Exception:
            self._fail("会话维护失败，已停止录放音；请重新连接")

    def _release(self):
        self.generation += 1
        self.accept_audio = False
        self.deadline = self.demo_due = 0
        self.silence_remaining = 0
        self.silence_due = 0.
        self.tts_ended = False
        for name in ("transport", "audio", "codec"):
            resource = getattr(self, name)
            setattr(self, name, None)
            if resource:
                try:
                    resource.close() if name != "audio" else resource.stop()
                except Exception:
                    pass
        self.session = ""

    def _fail(self, reason):
        self._release()
        self._set(state="error", connected=False, error=reason, emotion="neutral", voice_progress="failed")

    def _send(self, kind, **fields):
        if self.transport:
            self.transport.send(dict(type=kind, session_id=self.session, **fields))

    def _idle(self, progress="idle"):
        self.deadline = 0
        self._set(state="muted" if self.data["muted"] else "idle", emotion="neutral", voice_progress=progress)

    def _action(self, action):
        if action == "connect":
            if self.data["connected"] or self.data["state"] == "connecting":
                return
            self._release()
            self._set(state="connecting", error="", transcript="", reply="", voice_progress="idle")
            if self.config["mode"] == "demo":
                self.session = "demo"
                self._set(connected=True)
                self._idle()
                return
            if self.audio_factory is None:
                from .audio import AudioIO, OpusCodec
                from .transport import CloudTransport
                self.audio_factory, self.codec_factory, self.transport_factory = AudioIO, OpusCodec, CloudTransport
            generation = self.generation
            self.codec = self.codec_factory()
            self.audio = self.audio_factory(self.config, on_error=lambda e: self.post(
                "error", "音频设备失败，请检查声卡与 ALSA 配置", generation))
            self.transport = self.transport_factory(self.config,
                lambda value: self.post("message", value, generation),
                lambda e: self.post("error", "语音连接已断开，请重新连接", generation))
            self.transport.connect()
            self.transport.send({"type": "hello", "version": 1, "transport": "websocket",
                                 "device_id": self.config["device_id"], "audio_params": AUDIO_PARAMS})
            self.deadline = time.monotonic() + self.config["network_timeout_s"] + 3
        elif action == "disconnect":
            self._release()
            self._set(state="offline", connected=False, emotion="neutral", voice_progress="idle")
        elif action == "mute":
            reconnect = self._interrupt()
            self._set(muted=True)
            if reconnect:
                self._action("connect")
            elif self.data["connected"]:
                self._idle()
        elif action == "unmute":
            if self.data["muted"]:
                self._set(muted=False)
                if self.data["connected"]:
                    self._idle()
        elif action == "listen":
            if not self.data["connected"]:
                raise ValueError("请先连接语音服务")
            if self.data["muted"]:
                raise ValueError("麦克风已静音，请先取消静音")
            if self.data["state"] == "listening":
                return
            if self.data["state"] not in ("idle", "muted"):
                raise ValueError("请先停止当前回答，再开始新一轮对话")
            self._interrupt()
            self.capture_epoch += 1
            epoch = self.capture_epoch
            self.turn_audio_frames_sent = 0
            self.turn_audio_frames_received = 0
            with self.lock:
                self.data["metrics"]["capture_peak_amplitude"] = 0
            self._set(state="listening", transcript="", reply="", error="", emotion="neutral", voice_progress="recording")
            self._send("listen", state="start", mode=self.config.get("listen_mode", "manual"))
            generation = self.generation
            if self.audio:
                self.audio.start(lambda pcm: self.post("pcm", (epoch, pcm), generation))
            self.deadline = time.monotonic() + self.config["max_listen_s"]
        elif action == "stop":
            if self.data["state"] != "listening":
                return
            self.capture_epoch += 1
            if self.audio:
                self.audio.stop_capture()
            if self.config["mode"] == "live" and self.turn_audio_frames_sent == 0:
                # Sending listen/stop with no PCM can leave the backend waiting
                # indefinitely. Fence late replies by closing this connection.
                try:
                    self._send("abort", reason="no_audio")
                except Exception:
                    pass  # Local cleanup is still required if the peer is gone.
                self._fail("未采集到音频，请检查麦克风和 ALSA 设备配置后重新连接")
                return
            if self.config["mode"] == "live" and self.config.get("listen_mode", "manual") == "realtime":
                self.silence_remaining = SILENCE_TAIL_FRAMES
                self.silence_due = time.monotonic() + SILENCE_FRAME_INTERVAL
            else:
                self._send("listen", state="stop")
            self._set(state="thinking", emotion="thinking", voice_progress="waiting_reply" if self.data["transcript"] else "waiting_recognition")
            self.deadline = time.monotonic() + self.config["response_timeout_s"]
            if self.config["mode"] == "demo":
                self._set(transcript="演示：你好，介绍一下你自己。", voice_progress="waiting_reply")
                self.demo_phase, self.demo_due = 1, time.monotonic() + .5
        elif action == "interrupt":
            reconnect = self._interrupt()
            if reconnect:
                self._action("connect")
            elif self.data["connected"]:
                self._idle()
        else:
            raise ValueError("不支持的操作")

    def _interrupt(self):
        active = self.data["connected"] and self.data["state"] in ("listening", "thinking", "speaking")
        self.capture_epoch += 1
        self.accept_audio = False
        self.demo_due = self.deadline = 0
        self.silence_remaining = 0
        self.silence_due = 0.
        self.tts_ended = False
        if self.audio:
            self.audio.stop_capture()
            self.audio.interrupt()
        if active:
            try:
                self._send("abort", reason="user")
            finally:
                if self.config["mode"] == "live":
                    # Protocol v1 has no turn IDs. A fresh connection is the fence
                    # against late replies from the interrupted turn.
                    self._release()
                    self._set(state="offline", connected=False)
            return self.config["mode"] == "live"
        return False

    def _message(self, value):
        if isinstance(value, bytes):
            if self.accept_audio and not self.data["muted"] and self.audio:
                if len(value) > 4096:
                    raise ValueError("oversized audio")
                self.audio.play(value)
                self.turn_audio_frames_received += 1
                self._set(voice_progress="receiving_audio")
                with self.lock:
                    self.data["metrics"]["audio_frames_received"] += 1
            return
        if not isinstance(value, dict):
            raise ValueError("message must be an object")
        kind = value.get("type")
        if kind == "hello":
            if self.data["state"] != "connecting":
                return
            sample_rate, session = validate_hello(value)
            self.audio.configure_output(sample_rate)
            self.session = session
            self._set(connected=True)
            self._idle()
            return
        if not self.data["connected"] or (value.get("session_id") not in (None, self.session)):
            return
        if kind == "stt" and self.data["state"] in ("listening", "thinking", "speaking"):
            self._set(transcript=self._text(value.get("text", "")))
            if self.data["state"] == "thinking" and self.data["transcript"] and not self.data["reply"]:
                self._set(voice_progress="waiting_reply")
        elif kind == "llm" and self.data["state"] in ("thinking", "speaking"):
            emotion = value.get("emotion", "neutral")
            self._set(emotion=emotion if emotion in EMOTIONS else "neutral")
            if "text" in value:
                self._set(reply=self._text(value["text"]))
                if self.data["reply"] and self.data["state"] == "thinking":
                    self._set(voice_progress="waiting_audio")
        elif kind == "tts":
            state = value.get("state")
            if state == "start" and self.data["state"] in ("listening", "thinking") and not self.data["muted"]:
                self.capture_epoch += 1
                if self.audio:
                    self.audio.stop_capture()
                self.silence_remaining = 0
                self.silence_due = 0.
                self.accept_audio = True
                self.tts_ended = False
                self._set(state="speaking", voice_progress="waiting_audio")
                self.deadline = time.monotonic() + self.config["response_timeout_s"]
            elif state == "stop" and self.data["state"] == "speaking":
                self.accept_audio = False
                self.tts_ended = True
            elif state == "sentence_start" and self.data["state"] == "speaking":
                self._set(reply=self._text(value.get("text", "")))
        elif kind == "error":
            self._fail("后端返回错误，请检查服务与认证配置")
        # Remote messages can never arm or command an actuator.

    @staticmethod
    def _text(value):
        if not isinstance(value, str) or len(value) > 4096:
            raise ValueError("invalid text")
        return value

    def _tick(self):
        now = time.monotonic()
        if self.silence_remaining and now >= self.silence_due:
            if self.data["state"] == "thinking" and self.data["connected"] and not self.data["muted"]:
                self.transport.send(self.codec.encode(SILENCE_FRAME))
                with self.lock:
                    self.data["metrics"]["audio_frames_sent"] += 1
                self.silence_remaining -= 1
                # Never burst to catch up after a delayed event-loop iteration.
                self.silence_due = time.monotonic() + SILENCE_FRAME_INTERVAL if self.silence_remaining else 0.
            else:
                self.silence_remaining = 0
                self.silence_due = 0.
        if self.demo_due and now >= self.demo_due:
            if self.demo_phase == 1:
                self._set(state="speaking", emotion="happy", voice_progress="receiving_audio",
                    reply="你好！我是设备交互助手。语音、表情与视觉状态可以在这里协同工作。当前是演示模式，没有采集或播放真实音频。")
                self.demo_phase, self.demo_due = 2, now + 2
            else:
                self.demo_due = 0
                self._idle()
        if self.tts_ended and self.audio and not self.audio.playback_busy():
            self.tts_ended = False
            self._idle("complete")
        if self.deadline and now >= self.deadline:
            if self.data["state"] == "listening":
                self._action("stop")
            else:
                self._fail(self._timeout_reason())

    def _timeout_reason(self):
        if self.data["state"] == "connecting":
            return "语音握手超时，请检查后端地址和设备认证后重新连接"
        stage = self.data["voice_progress"]
        if stage == "waiting_recognition":
            detail = "已上传录音，但未收到识别结果；请检查录音电平和后端识别服务"
        elif stage == "waiting_reply":
            detail = "已收到识别文字，但未收到回答；请检查后端对话服务"
        elif stage == "waiting_audio":
            detail = "后端已进入回复阶段，但未收到语音音频；请检查后端语音合成服务"
        elif self.turn_audio_frames_received:
            detail = "已收到部分语音，但回复未正常结束；请检查后端连接"
        else:
            detail = "语音服务未按时完成回复，请检查后端状态"
        return detail + "。会话超时，已停止录放音；请重新连接"

def validate_hello(value):
    params = value.get("audio_params", AUDIO_PARAMS)
    if not isinstance(params, dict) or any(params.get(k, v) != v for k, v in AUDIO_PARAMS.items() if k != "sample_rate"):
        raise ValueError("unsupported audio format")
    rate = params.get("sample_rate", 16000)
    if type(rate) is not int or rate not in (16000, 24000, 48000):
        raise ValueError("unsupported playback sample rate")
    session = value.get("session_id")
    if not isinstance(session, str) or not session or len(session) > 256:
        raise ValueError("invalid session")
    return rate, session
