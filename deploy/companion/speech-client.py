#!/usr/bin/env python3
"""One bounded request to the warm speech worker; never prints user data."""
import argparse
import json
import socket
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("--operation", choices=("asr", "tts", "health"), required=True)
    parser.add_argument("--input")
    parser.add_argument("--output")
    parser.add_argument("--text")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    payload = json.dumps({key: value for key, value in vars(args).items()
                          if key not in ("socket", "timeout") and value is not None}, ensure_ascii=False).encode() + b"\n"
    if len(payload) > 16384 or not 0 < args.timeout <= 180:
        return 2
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(args.timeout)
            connection.connect(args.socket)
            connection.sendall(payload)
            result = bytearray()
            while b"\n" not in result:
                block = connection.recv(1024)
                if not block or len(result) + len(block) > 4096:
                    raise ValueError("Invalid worker response")
                result.extend(block)
            response = json.loads(result.split(b"\n", 1)[0])
            if not response.get("ok"):
                raise ValueError("Speech operation failed")
            if args.operation == "health":
                print(json.dumps(response))
        return 0
    except Exception:
        print("local speech worker request failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
