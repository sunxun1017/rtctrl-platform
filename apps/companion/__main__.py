import argparse
import ctypes.util
import importlib.util
import json
import shutil
import signal
import threading

from .config import load_config
from .core import AUDIO_PARAMS, Companion, validate_hello
from .monitor import Monitor
from .network import NetworkManager
from .device import DeviceManager
from .server import Server

def doctor(config):
    checks = {"python": True, "libopus": bool(ctypes.util.find_library("opus")),
              "arecord": bool(shutil.which("arecord")), "aplay": bool(shutil.which("aplay")),
              "websocket_client": importlib.util.find_spec("websocket") is not None,
              "ssl": importlib.util.find_spec("ssl") is not None}
    print(json.dumps({"checks": checks, "mode": config["mode"],
                      "note": "只检查依赖；未打开声卡、连接后端或验证板端性能"}, ensure_ascii=False))
    return 0 if all(checks.values()) or config["mode"] == "demo" else 1

def probe(config):
    from .transport import CloudTransport
    event = threading.Event()
    result = {"ok": False}
    def message(value):
        if isinstance(value, dict) and value.get("type") == "hello":
            params = value.get("audio_params", AUDIO_PARAMS)
            try:
                validate_hello(value)
                result["ok"] = True
                result["audio_params"] = params
            except ValueError:
                result["error"] = "unsupported hello"
            event.set()
    def error(_):
        event.set()
    transport = CloudTransport(config, message, error)
    try:
        transport.connect()
        transport.send({"type": "hello", "version": 1, "transport": "websocket",
                        "device_id": config["device_id"], "audio_params": AUDIO_PARAMS})
        event.wait(config["network_timeout_s"] + 3)
    except Exception as exc:
        result["error"] = type(exc).__name__
    finally:
        transport.close()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1

def main():
    parser = argparse.ArgumentParser(description="RV1126B 非实时语音与表情交互服务")
    parser.add_argument("--config")
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--probe", action="store_true", help="仅后端握手；不打开麦克风")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.doctor:
            return doctor(config)
        if args.probe:
            return probe(config)
        core = Companion(config)
        network = NetworkManager(enabled=config["wifi_enabled"])
        device = DeviceManager(enabled=config["device_settings_enabled"] and config["mode"] == "live")
        server = Server((config["bind"], config["port"]), core, network=network, device=device)
        monitor = Monitor(core)
        stopped = threading.Event()
        def stop(*_):
            stopped.set()
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        core.start()
        monitor.start()
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        print("Companion: http://%s:%s/ mode=%s" % (config["bind"], config["port"], config["mode"]), flush=True)
        try:
            stopped.wait()
        finally:
            server.shutdown()
            server.server_close()
            network.close()
            device.close()
            monitor.close()
            core.close()
            worker.join(timeout=2)
        return 0
    except (ValueError, OSError, ImportError) as exc:
        print("启动失败: " + type(exc).__name__ + "；请检查配置、端口及依赖")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
