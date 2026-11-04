"""Discover existing local ADB servers and select isolated per-operation endpoints."""

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
import json
import os
from pathlib import Path
import socket
import subprocess
import time


def server_port(value=5037):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("Cổng ADB phải là số nguyên từ 1 đến 65535.")
    try:
        port = int(value)
    except ValueError:
        raise ValueError("Cổng ADB phải là số nguyên từ 1 đến 65535.") from None
    if not 1 <= port <= 65535:
        raise ValueError("Cổng ADB phải là số nguyên từ 1 đến 65535.")
    return port


class AdbEndpoint(str):
    """An executable path compatible with existing callers, plus its server port."""

    def __new__(cls, executable, port):
        value = super().__new__(cls, str(executable))
        value._port = server_port(port)
        return value

    @property
    def port(self):
        return self._port


def endpoint_environment(port):
    port = server_port(port)
    return {
        "ANDROID_ADB_SERVER_HOST": "127.0.0.1",
        "ANDROID_ADB_SERVER_PORT": str(port),
        "ADB_SERVER_SOCKET": f"tcp:127.0.0.1:{port}",
    }


def configure_adb_server(port=5037):
    """CLI uses the socket; adbutils/uiautomator2 use the host/port variables.

    Called once at normal GUI startup. Children inherit the same endpoint,
    including engine preparation and keyboard recovery subprocesses.
    """
    os.environ.update(endpoint_environment(port))


def _read_exact(stream, count, deadline):
    chunks = bytearray()
    while len(chunks) < count:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("ADB server không phản hồi kịp thời.")
        stream.settimeout(remaining)
        chunk = stream.recv(count - len(chunks))
        if not chunk:
            raise RuntimeError("ADB server đóng kết nối trước khi trả đủ dữ liệu.")
        chunks.extend(chunk)
    return bytes(chunks)


def query_devices(port, timeout=4):
    """Read host:devices-l without starting, restarting or killing a server."""
    # Windows loopback refusal can take slightly over two seconds. Allow it to
    # arrive so cold startup distinguishes a missing server from a busy one.
    port = server_port(port)
    deadline = time.monotonic() + timeout
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as stream:
        stream.settimeout(timeout)
        stream.sendall(b"000ehost:devices-l")
        status = _read_exact(stream, 4, deadline)
        if status not in (b"OKAY", b"FAIL"):
            raise RuntimeError(f"Cổng ADB {port} trả về giao thức không hợp lệ.")
        try:
            size = int(_read_exact(stream, 4, deadline), 16)
        except ValueError:
            raise RuntimeError(f"Cổng ADB {port} trả về độ dài không hợp lệ.") from None
        body = _read_exact(stream, size, deadline).decode("utf-8", errors="replace")
        if status == b"FAIL":
            raise RuntimeError(f"ADB {port}: {body}")
        return body


def _windows_adb_ports():
    if os.name != "nt":
        return []
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        tasks = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq adb.exe", "/FO", "CSV", "/NH"],
            capture_output=True, timeout=2, creationflags=flags, check=True,
        ).stdout.decode("utf-8", errors="replace")
        pids = {row[1] for row in csv.reader(tasks.splitlines())
                if len(row) > 1 and row[0].casefold() == "adb.exe"}
        if not pids:
            return []
        connections = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"], capture_output=True,
            timeout=2, creationflags=flags, check=True,
        ).stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return []
    ports = set()
    for line in connections.splitlines():
        fields = line.split()
        if len(fields) != 5 or fields[0] != "TCP" or fields[3] != "LISTENING" or fields[4] not in pids:
            continue
        host, _, value = fields[1].rpartition(":")
        if host not in ("127.0.0.1", "0.0.0.0", "[::]", "[::1]"):
            continue
        try:
            ports.add(server_port(value))
        except ValueError:
            continue
    return sorted(ports)


def discover_server_ports(primary=5037):
    """Call in a background worker; tolerate unavailable process diagnostics."""
    known = list(dict.fromkeys((server_port(primary), 5037, 5038)))
    candidates = set(_windows_adb_ports()) - set(known)
    if not candidates:
        return tuple(known)
    # adb.exe also owns forwarded HTTP/stream sockets. Only add listeners that
    # actually speak the ADB host protocol; bound discovery even with many forwards.
    def probe(port):
        try:
            query_devices(port, timeout=0.25)
            return True
        except (OSError, RuntimeError):
            return False
    pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="adb-ports")
    pending = {pool.submit(probe, port): port for port in sorted(candidates)}
    found = []
    try:
        for future in as_completed(pending, timeout=2):
            if future.result():
                found.append(pending[future])
    except FuturesTimeout:
        pass
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    return tuple([*known, *sorted(found)])


def find_endpoint(adb, serial):
    """Locate an online device for recovery, including a move after a crash."""
    preferred = getattr(adb, "port", os.environ.get("ANDROID_ADB_SERVER_PORT", 5037))
    for port in discover_server_ports(preferred):
        try:
            inventory = query_devices(port)
        except (OSError, RuntimeError):
            continue
        for line in inventory.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[0] == serial and fields[1] == "device":
                return AdbEndpoint(adb, port)
    raise RuntimeError(f"Không tìm thấy điện thoại {serial} trên các cổng ADB đang chạy.")


def recovery_endpoint(adb, serial, directory):
    if not (Path(directory) / "keyboard.json").is_file():
        return adb
    try:
        saved = json.loads((Path(directory) / "adb-server.json").read_text(encoding="utf-8"))
        adb = AdbEndpoint(adb, saved["port"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return find_endpoint(adb, serial)

