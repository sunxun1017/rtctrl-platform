"""Strict deployment configuration. Credentials are supplied only by environment."""
import json
import math
from urllib.parse import urlsplit

DEFAULTS = {
    "wifi_enabled": False, "mode": "demo", "bind": "127.0.0.1", "port": 8090,
    "backend_url": "", "token_env": "RTCTRL_VOICE_TOKEN",
    "device_id": "rtctrl-rv1126b", "client_id": "rtctrl-companion",
    "allow_insecure_ws": False, "network_timeout_s": 5,
    "capture_device": "default", "playback_device": "default",
    "playback_queue_frames": 16, "max_listen_s": 30, "listen_mode": "manual",
    "response_timeout_s": 45, "face_url": "http://127.0.0.1:8080/status.json",
    "face_poll_s": 1, "face_stale_s": 5,
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
                "capture_device", "playback_device", "face_url"):
        if not isinstance(config[key], str) or len(config[key]) > 2048 or any(
                c in config[key] for c in "\r\n\x00"):
            raise ValueError("invalid " + key)
    if config["mode"] not in ("demo", "live"):
        raise ValueError("mode must be demo or live")
    if config["listen_mode"] not in ("manual", "realtime"):
        raise ValueError("listen_mode must be manual or realtime")
    if type(config["wifi_enabled"]) is not bool:
        raise ValueError("wifi_enabled must be boolean")
    if type(config["allow_insecure_ws"]) is not bool:
        raise ValueError("allow_insecure_ws must be boolean")
    for key, low, high in (("port", 1, 65535), ("playback_queue_frames", 2, 32),
                           ("network_timeout_s", 1, 15), ("max_listen_s", 1, 120),
                           ("response_timeout_s", 5, 120), ("face_poll_s", .2, 10),
                           ("face_stale_s", 1, 60)):
        value = config[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError("invalid " + key)
    for key in ("port", "playback_queue_frames"):
        if type(config[key]) is not int:
            raise ValueError(key + " must be an integer")
    if config["bind"] not in ("127.0.0.1", "localhost"):
        raise ValueError("bind must be loopback; use an SSH tunnel for remote control")
    if config["mode"] == "live":
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
