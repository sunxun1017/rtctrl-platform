#!/usr/bin/env python3
"""Explicit Buildroot service control; never installs an init script or changes networking."""
import argparse
import fcntl
import json
import logging
import logging.handlers
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid

SCRIPT = str(Path(__file__).resolve())
STOP_GRACE = 7.0


def process_info(pid):
    try:
        raw = Path("/proc/%d/stat" % int(pid)).read_text()
        tail = raw[raw.rfind(")") + 2:].split()
        return {"start": tail[19], "state": tail[0]}
    except (OSError, ValueError, IndexError):
        return None


def identity_alive(pid, start):
    info = process_info(pid)
    return bool(info and info["state"] != "Z" and info["start"] == start)


def supervisor_alive(record):
    if not re.fullmatch(r"[0-9a-f]{32}", str(record.get("instance", ""))):
        return False
    if not identity_alive(record.get("pid", 0), record.get("start")):
        return False
    try:
        args = Path("/proc/%d/cmdline" % record["pid"]).read_bytes().split(b"\0")
        return (SCRIPT.encode() in args and b"_supervise" in args and
                str(record.get("instance", "")).encode() in args)
    except OSError:
        return False


def child_alive(record):
    pid = record.get("child_pid", 0)
    if not identity_alive(pid, record.get("child_start")):
        return False
    try:
        return os.getpgid(pid) == pid
    except ProcessLookupError:
        return False


def read_record(directory):
    try:
        record = json.loads((directory / "service.json").read_text())
        return record if isinstance(record, dict) else {}
    except (OSError, ValueError):
        return {}


def write_record(directory, record):
    temporary = directory / ("state-" + record["instance"] + ".tmp")
    fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(record, stream)
        stream.write("\n")
    os.replace(str(temporary), str(directory / "service.json"))


def read_environment(filename):
    result = {}
    if filename:
        path = Path(filename)
        meta = path.stat()
        if not stat.S_ISREG(meta.st_mode) or meta.st_mode & 0o077:
            raise ValueError("Environment file must be a regular file with mode 0600")
        if meta.st_uid != os.geteuid():
            raise ValueError("Environment file must belong to the current service user")
        if meta.st_size > 16384:
            raise ValueError("Environment file exceeds 16 KiB")
        for line in path.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError("Environment file requires literal KEY=VALUE lines")
            if "\x00" in value or len(value.encode()) > 4096:
                raise ValueError("Invalid environment value")
            result[key] = value
    return result


def stop_owned(record):
    if supervisor_alive(record):
        os.kill(record["pid"], signal.SIGTERM)
        deadline = time.monotonic() + STOP_GRACE + 2
        while supervisor_alive(record) and time.monotonic() < deadline:
            time.sleep(.05)
    if child_alive(record):
        os.killpg(record["child_pid"], signal.SIGTERM)
        deadline = time.monotonic() + 1
        while child_alive(record) and time.monotonic() < deadline:
            time.sleep(.05)
        if child_alive(record):
            os.killpg(record["child_pid"], signal.SIGKILL)
    if supervisor_alive(record):
        os.kill(record["pid"], signal.SIGKILL)
    deadline = time.monotonic() + 1
    while (supervisor_alive(record) or child_alive(record)) and time.monotonic() < deadline:
        time.sleep(.05)
    if supervisor_alive(record) or child_alive(record):
        raise RuntimeError("Owned processes did not stop within deadline")


def supervise(args, directory):
    os.umask(0o077)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    record = {"pid": os.getpid(), "start": process_info(os.getpid())["start"],
              "instance": args.instance, "status": "starting"}
    logger = logging.getLogger("companion-service")
    logger.setLevel(logging.INFO)
    handler = logging.handlers.RotatingFileHandler(directory / "service.log",
                                                   maxBytes=65536, backupCount=2)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    child = None
    try:
        extra = read_environment(args.env_file)
        environment = dict(os.environ, **extra)
        secrets = [value for key, value in environment.items()
                   if value and (key in extra or any(word in key.upper()
                       for word in ("TOKEN", "PASSWORD", "SECRET", "API_KEY")))]
        def emit(line):
            for value in secrets:
                line = line.replace(value, "[redacted]")
            logger.info("%s", line)
        child = subprocess.Popen(["/bin/sh", str(Path(args.bundle) / "run-companion.sh"),
                                  args.config], cwd=args.bundle, env=environment,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, start_new_session=True, bufsize=0)
        child_info = process_info(child.pid)
        if not child_info:
            raise RuntimeError("Child failed to start")
        record.update(child_pid=child.pid, child_start=child_info["start"],
                      status="running", bundle=args.bundle, config=args.config)
        write_record(directory, record)
        logger.info("service started")
        os.set_blocking(child.stdout.fileno(), False)
        selector = selectors.DefaultSelector()
        selector.register(child.stdout, selectors.EVENT_READ)
        pending = bytearray()
        dropping = False
        stopping_at = None
        while True:
            if stop.is_set() and stopping_at is None:
                stopping_at = time.monotonic()
                if child_alive(record):
                    os.killpg(child.pid, signal.SIGTERM)
            if stopping_at is not None and time.monotonic() - stopping_at >= STOP_GRACE:
                if child_alive(record):
                    os.killpg(child.pid, signal.SIGKILL)
            for key, _ in selector.select(.1):
                chunk = os.read(key.fd, 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                for piece in chunk.splitlines(keepends=True):
                    end = piece.endswith((b"\n", b"\r"))
                    if not dropping:
                        pending.extend(piece)
                        if len(pending) > 8192:
                            pending.clear()
                            dropping = True
                        elif end:
                            emit(pending.decode("utf-8", errors="replace").rstrip())
                            pending.clear()
                    if end and dropping:
                        logger.info("oversized child log line suppressed")
                        dropping = False
            if child.poll() is not None:
                break
        selector.close()
        if pending and not dropping:
            emit(pending.decode("utf-8", errors="replace"))
        code = child.wait(timeout=1)
        record.update(status="stopped" if stop.is_set() else "exited", exit_code=code)
        logger.info("service stopped; exit_code=%d", code)
    except Exception as error:
        record.update(status="failed", error=type(error).__name__)
        logger.error("supervisor failed: %s", type(error).__name__)
    finally:
        if child is not None:
            # The launcher execs the application. If it crashes before ALSA
            # helpers exit, reap its private group as well as the leader.
            current = process_info(child.pid)
            if current is None or current["start"] == record.get("child_start"):
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            if child.stdout:
                child.stdout.close()
        write_record(directory, record)
        handler.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status", "restart", "_supervise"))
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--bundle")
    parser.add_argument("--config")
    parser.add_argument("--env-file")
    parser.add_argument("--instance", help=argparse.SUPPRESS)
    args = parser.parse_args()
    directory = Path(args.state_dir).absolute()
    try:
        os.umask(0o077)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        meta = directory.lstat()
        if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.geteuid() or meta.st_mode & 0o077:
            raise ValueError("State directory must be owned by this user and mode 0700")
        if args.action == "_supervise":
            return supervise(args, directory)
        with (directory / "control.lock").open("a") as lock:
            lock_deadline = time.monotonic() + 12
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= lock_deadline:
                        raise RuntimeError("Service control is busy; retry after the current operation")
                    time.sleep(.05)
            record = read_record(directory)
            active = supervisor_alive(record) and child_alive(record)
            if args.action == "status":
                print(json.dumps({"status": "running" if active else (
                                      "stale" if record.get("status") == "running" else record.get("status", "stopped")),
                                  "running": active, "pid": record.get("pid"),
                                  "child_pid": record.get("child_pid"),
                                  "orphan": child_alive(record) and not supervisor_alive(record)}))
                return 0 if active else 3
            if args.action in ("stop", "restart"):
                stop_owned(record)
                print("stopped")
                if args.action == "stop":
                    return 0
            if args.action in ("start", "restart"):
                if active and args.action == "start":
                    print("already running")
                    return 0
                if supervisor_alive(record) or child_alive(record):
                    raise RuntimeError("Existing owned process requires explicit stop")
                if not args.bundle or not args.config:
                    raise ValueError("Start requires --bundle and --config")
                args.bundle = str(Path(args.bundle).resolve(strict=True))
                args.config = str(Path(args.config).resolve(strict=True))
                if not (Path(args.bundle) / "run-companion.sh").is_file() or not Path(args.config).is_file():
                    raise ValueError("Bundle launcher or config is missing")
                if args.env_file:
                    args.env_file = str(Path(args.env_file).resolve(strict=True))
                read_environment(args.env_file)
                instance = uuid.uuid4().hex
                command = [sys.executable, "-B", SCRIPT, "_supervise", "--state-dir", str(directory),
                           "--bundle", args.bundle, "--config", args.config, "--instance", instance]
                if args.env_file:
                    command += ["--env-file", args.env_file]
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           start_new_session=True, close_fds=True)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    record = read_record(directory)
                    if record.get("instance") == instance:
                        if record.get("status") == "running" and child_alive(record):
                            time.sleep(.2)
                            if child_alive(record) and supervisor_alive(record):
                                print("started; process is alive (application readiness is separate)")
                                return 0
                        if record.get("status") in ("failed", "exited"):
                            break
                    if process.poll() is not None:
                        break
                    time.sleep(.05)
                # Cancel only this launch, never whatever another PID record might name.
                if record.get("instance") == instance:
                    stop_owned(record)
                elif process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=1)
                raise RuntimeError("Start failed; inspect bounded service.log")
    except (OSError, ValueError, RuntimeError) as error:
        print("service control failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
