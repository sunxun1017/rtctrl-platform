#!/usr/bin/env python3
"""QEMU checks echo suppression, invalid-input cleanup and exact TCP roundtrip."""
import hashlib
import os
from pathlib import Path
import pty
import select
import signal
import socket
import struct
import subprocess
import tempfile
import termios

root = Path.cwd()
binary = root/'outputs/rk3568-source-wifi-20261004/network-helper'
qemu = root/'.deps/qemu-user/root/usr/bin/qemu-aarch64-static'


def credential(path, input_line, success, stop_signal=None):
    existed = path.exists()
    previous = path.read_bytes() if existed else None
    master, slave = pty.openpty()
    old = termios.tcgetattr(slave)
    child = subprocess.Popen([str(qemu), str(binary), 'config', str(path)],
                             stdin=slave, stdout=slave, stderr=slave)
    output = b''
    while b'CREDENTIAL_INPUT_READY_ECHO_OFF' not in output:
        assert select.select([master], [], [], 5)[0]
        output += os.read(master, 4096)
    assert not (termios.tcgetattr(slave)[3] & termios.ECHO)
    if stop_signal:
        os.write(master, b'74657374:' + b'1' * 20)
        os.kill(child.pid, stop_signal)
    else:
        os.write(master, input_line)
    assert child.wait(timeout=5) == (0 if success else 1)
    while select.select([master], [], [], 0.1)[0]:
        output += os.read(master, 4096)
    assert input_line.strip() not in output, 'Sensitive input echoed'
    assert termios.tcgetattr(slave) == old, 'TTY settings not restored'
    if stop_signal:
        os.write(master, b'\n')
        assert select.select([slave], [], [], 1)[0]
        assert os.read(slave, 128) == b'\n', 'Sensitive prefix left in TTY queue'
    assert path.exists() == (success or existed)
    if existed:
        assert path.read_bytes() == previous, 'Existing file modified'
    if success:
        assert path.stat().st_mode & 0o777 == 0o600
    os.close(master)
    os.close(slave)


def receive(sock, count):
    data = b''
    while len(data) < count:
        part = sock.recv(count - len(data))
        assert part
        data += part
    return data


with tempfile.TemporaryDirectory() as folder:
    folder = Path(folder)
    dummy = b'74657374:' + b'1' * 64 + b'\n'
    credential(folder/'valid', dummy, True)
    # Exercise the actual minimal WPA parser with the runtime normalization;
    # the nonexistent interface prevents any host Wi-Fi operation.
    subprocess.run(['sed', '-i', '/^update_config=/d', str(folder/'valid')], check=True)
    parsed = subprocess.run([str(qemu), str(root/'outputs/rk3568-source-wifi-20261004/wpa_supplicant'),
                             '-i', 'cfg-test-none', '-D', 'nl80211', '-c', str(folder/'valid')],
                            capture_output=True, timeout=5)
    log = parsed.stdout + parsed.stderr
    assert b'Failed to read or parse configuration' not in log, log
    assert b'unknown global field' not in log, log
    credential(folder/'invalid', b'zz:not-a-key\n', False)
    credential(folder/'valid', dummy, False)
    for stop_signal in [signal.SIGINT, signal.SIGTERM, signal.SIGHUP]:
        credential(folder/('signal-' + str(stop_signal)), b'not-sent', False, stop_signal)
    interrupted = subprocess.Popen([str(qemu), str(binary), 'serve', str(folder/'transfer')],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert interrupted.stdout.readline().strip() == b'TRANSFER_SERVER_READY'
    with socket.create_connection(('127.0.0.1', 18765), timeout=5) as client:
        client.sendall(b'P' + struct.pack('!I', 1000) + b'partial')
    assert interrupted.wait(timeout=5) == 1
    assert not (folder/'transfer').exists(), 'Interrupted upload left a partial file'
    expected = b'Linux source Wi-Fi roundtrip\n' * 2048
    child = subprocess.Popen([str(qemu), str(binary), 'serve', str(folder/'transfer')],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert child.stdout.readline().strip() == b'TRANSFER_SERVER_READY'
    with socket.create_connection(('127.0.0.1', 18765), timeout=5) as client:
        client.sendall(b'P' + struct.pack('!I', len(expected)) + expected)
        assert receive(client, 3) == b'OK\n'
    with socket.create_connection(('127.0.0.1', 18765), timeout=5) as client:
        client.sendall(b'G')
        count = struct.unpack('!I', receive(client, 4))[0]
        assert receive(client, count) == expected
    assert child.wait(timeout=5) == 0
    assert (folder/'transfer').read_bytes() == expected
print('NETWORK_HELPER_QEMU_TESTS_PASSED')
