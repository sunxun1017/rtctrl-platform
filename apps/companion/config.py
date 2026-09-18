"""Strict deployment configuration. Credentials are supplied only by environment."""
import json
import math
import os
from urllib.parse import urlsplit

DEFAULTS = {
    "device_settings_enabled": False, "wifi_enabled": False, "mode": "demo", "bind": "127.0.0.1", "port": 8090,
    "backend_url": "", "token_env": "RTCTRL_VOICE_TOKEN",
    "device_id": "rtctrl-rv1126b", "client_id": "rtctrl-companion",
    "allow_insecure_ws": False, "network_timeout_s": 5,
    "capture_device": "default", "playback_device": "default",
    "playback_queue_frames": 16, "max_listen_s": 30, "listen_mode": "manual",
    "response_timeout_s": 45, "face_url": "http://127.0.0.1:8080/status.json",
    "face_poll_s": 1, "face_stale_s": 5,
    "voice_backend": "android", "qianfan_model": "ernie-4.5-turbo-32k",
    "qianfan_token_env": "BAIDU_QIANFAN_API_KEY", "qianfan_proxy_url": "",
    "local_asr_backend": "cpu", "local_asr_command": [], "local_tts_command": [],
    "local_asr_timeout_s": 60, "local_tts_timeout_s": 90,
    "local_speech_root": "", "local_speech_socket": "", "local_tts_kind": "vits", "local_tts_speaker": 0, "local_speech_threads": 2,

}

def load_config(path=None):
    values = {}
    if path:
        with open(path, encoding="utf-8") as stream:
            values = json.load(stream)
    return validate(values)

def validate(values):
    if not isinstance(values, dict):
        raise ValueError("configuration must be an object")
    unknown = set(values) - set(DEFAULTS)
    if unknown:
        raise ValueError("unknown configuration keys: " + ", ".join(sorted(unknown)))
    config = dict(DEFAULTS, **values)
    for key in ("bind", "backend_url", "token_env", "device_id", "client_id",
                "capture_device", "playback_device", "face_url", "qianfan_model",
                "qianfan_token_env", "qianfan_proxy_url", "local_speech_root", "local_speech_socket"):
        if not isinstance(config[key], str) or len(config[key]) > 2048 or any(
                c in config[key] for c in "\r\n\x00"):
            raise ValueError("invalid " + key)
    if config["mode"] not in ("demo", "live"):
        raise ValueError("mode must be demo or live")
    if config["voice_backend"] not in ("android", "local"):
        raise ValueError("voice_backend must be android or local")
    if config["local_asr_backend"] not in ("cpu", "rknn"):
        raise ValueError("local_asr_backend must be cpu or rknn")
    for key in ("local_asr_command", "local_tts_command"):
        command = config[key]
        if not isinstance(command, list) or len(command) > 64 or any(
                not isinstance(arg, str) or len(arg) > 4096 or any(c in arg for c in "\r\n\x00") for arg in command):
            raise ValueError("invalid " + key)
        if command and not os.path.isabs(command[0]):
            raise ValueError(key + " needs an absolute executable path")
    if type(config["local_speech_threads"]) is not int or config["local_speech_threads"] not in (1, 2):
        raise ValueError("local_speech_threads must be 1 or 2")
    if config["local_tts_kind"] not in ("vits", "vits_aishell3"):
        raise ValueError("unsupported local_tts_kind")
    if type(config["local_tts_speaker"]) is not int or not 0 <= config["local_tts_speaker"] < 174:
        raise ValueError("invalid local_tts_speaker")
    if bool(config["local_speech_root"]) != bool(config["local_speech_socket"]):
        raise ValueError("local_speech_root and local_speech_socket must be configured together")
    if config["local_speech_root"] and not all(os.path.isabs(config[k]) for k in ("local_speech_root", "local_speech_socket")):
        raise ValueError("local speech paths must be absolute")
    if config["qianfan_proxy_url"]:
        proxy = urlsplit(config["qianfan_proxy_url"])
        if (proxy.scheme != "http" or proxy.hostname not in ("127.0.0.1", "localhost") or
                not proxy.port or proxy.username or proxy.password or proxy.path not in ("", "/") or proxy.query or proxy.fragment):
            raise ValueError("qianfan_proxy_url must be a credential-free loopback HTTP CONNECT proxy")
    if config["listen_mode"] not in ("manual", "realtime"):
        raise ValueError("listen_mode must be manual or realtime")
    for key in ("wifi_enabled", "device_settings_enabled"):
        if type(config[key]) is not bool:
            raise ValueError(key + " must be boolean")
    if type(config["allow_insecure_ws"]) is not bool:
        raise ValueError("allow_insecure_ws must be boolean")
    for key, low, high in (("port", 1, 65535), ("playback_queue_frames", 2, 32),
                           ("network_timeout_s", 1, 15), ("max_listen_s", 1, 120),
                           ("response_timeout_s", 5, 240), ("local_asr_timeout_s", 1, 120),
                           ("local_tts_timeout_s", 1, 120), ("face_poll_s", .2, 10),
                           ("face_stale_s", 1, 60)):
        value = config[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError("invalid " + key)
    for key in ("port", "playback_queue_frames"):
        if type(config[key]) is not int:
            raise ValueError(key + " must be an integer")
    if config["bind"] not in ("127.0.0.1", "localhost"):
        raise ValueError("bind must be loopback; use an SSH tunnel for remote control")
    if config["mode"] == "live" and config["voice_backend"] == "local":
        if config["listen_mode"] != "manual":
            raise ValueError("local voice requires manual push-to-talk")
        if not config["local_asr_command"] or not config["local_tts_command"]:
            raise ValueError("local voice requires ASR and TTS commands")
        if not config["qianfan_model"] or not config["qianfan_token_env"]:
            raise ValueError("local voice requires Qianfan model and token environment name")
    if config["mode"] == "live" and config["voice_backend"] == "android":
        url = urlsplit(config["backend_url"])
        if url.scheme not in ("ws", "wss") or not url.hostname or url.username or url.password:
            raise ValueError("live mode needs a ws/wss backend URL without credentials")
        if url.scheme == "ws" and not config["allow_insecure_ws"]:
            raise ValueError("ws requires explicit allow_insecure_ws; prefer wss")
    if config["face_url"]:
        url = urlsplit(config["face_url"])
        if url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost") or url.username:
            raise ValueError("face_url must point to a local http service")
    return config
