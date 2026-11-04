"""ADB inventory runs in a worker thread with per-command timeouts."""

import re
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
import threading
import time

from customer_desktop.adb_server import AdbEndpoint, endpoint_environment, query_devices



def resolve_adb(configured=""):
    return str(configured or shutil.which("adb") or "adb")


def adb_run(adb, args, timeout=8):
    options = {}
    if getattr(adb, "port", None) is not None:
        options["env"] = {**os.environ, **endpoint_environment(adb.port)}
    result = subprocess.run(
        [str(adb), *args],
        capture_output=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        **options,
    )
    if result.returncode:
        raise RuntimeError(
            result.stderr.decode("utf-8", errors="replace").strip()
            or result.stdout.decode("utf-8", errors="replace").strip()
            or "ADB thất bại"
        )
    return result.stdout.decode("utf-8", errors="replace").strip()


class DeviceInventory:
    """Instance-owned TTL cache; scan lock serializes callers outside the GUI."""

    def __init__(self, ttl=60, max_workers=4, clock=None):
        self.ttl = ttl
        self.max_workers = max(1, min(4, int(max_workers)))
        self.clock = clock or time.monotonic
        self.cache = {}
        self.adb = None
        self.lock = threading.Lock()
        self.routes = {}

    @staticmethod
    def details(adb, serial):
        android = adb_run(
            adb, ["-s", serial, "shell", "getprop", "ro.build.version.release"]
        )
        packages = set(
            adb_run(adb, ["-s", serial, "shell", "pm", "list", "packages"]).splitlines()
        )
        candidates = (
            "com.ss.android.ugc.tiktok.lite",
            "com.zhiliaoapp.musically",
            "com.ss.android.ugc.trill",
        )
        package = next(
            (
                p
                for p in candidates
                if "package:" + p in packages
            ),
            "",
        )
        applications = []
        for installed in candidates:
            if "package:" + installed not in packages:
                continue
            detail = adb_run(
                adb, ["-s", serial, "shell", "dumpsys", "package", installed]
            )
            match = re.search(r"versionName=(\S+)", detail)
            code = re.search(r"versionCode=(\d+)", detail)
            applications.append(dict(
                package=installed,
                version=match.group(1) if match else "",
                version_code=code.group(1) if code else "",
            ))
        version = applications[0]["version"] if applications else ""
        return dict(android=android, package=package, version=version, applications=applications)

    def scan(self, adb, ports=None, start_if_missing=False):
        with self.lock:
            if ports is None:
                inventories = [(None, adb_run(adb, ["devices", "-l"]))]
            else:
                ports = tuple(dict.fromkeys(ports))
                inventories, failures, errors = [], [], []
                for port in ports:
                    try:
                        inventories.append((port, query_devices(port)))
                    except (OSError, RuntimeError) as exc:
                        failures.append(f"{port}: {exc}")
                        errors.append(exc)
                if not inventories:
                    if start_if_missing and ports and all(isinstance(exc, ConnectionRefusedError) for exc in errors):
                        # Preserve standalone cold startup, but never start optional
                        # servers while an existing Xiaowei endpoint is responding.
                        inventories = [(ports[0], adb_run(AdbEndpoint(adb, ports[0]), ["devices", "-l"]))]
                    else:
                        raise RuntimeError("Không đọc được các cổng ADB: " + "; ".join(failures))
            if self.adb != adb:
                self.cache.clear()
                self.routes.clear()
                self.adb = adb
            merged = {}
            rank = {"online": 3, "unauthorized": 2, "offline": 1}
            for port, text in inventories:
                for line in text.splitlines():
                    fields = line.split()
                    if len(fields) < 2 or fields[1] not in ("device", "offline", "unauthorized"):
                        continue
                    serial, state = fields[:2]
                    model = next((f[6:] for f in fields if f.startswith("model:")), serial)
                    device = dict(
                        serial=serial,
                        model=model,
                        connection="online" if state == "device" else state,
                    )
                    if port is not None:
                        device["adb_port"] = port
                    previous = merged.get(serial)
                    def priority(row):
                        return (rank[row["connection"]], row.get("adb_port") == self.routes.get(serial))
                    if previous is None or priority(device) > priority(previous):
                        merged[serial] = device
            devices = list(merged.values())
            online = {d["serial"] for d in devices if d["connection"] == "online"}
            self.cache = {
                serial: data for serial, data in self.cache.items() if serial in online
            }
            with ThreadPoolExecutor(
                max_workers=self.max_workers, thread_name_prefix="adb-inventory"
            ) as pool:
                pending = {}
                for d in devices:
                    if d["connection"] != "online":
                        continue
                    cached = self.cache.get(d["serial"])
                    port = d.get("adb_port")
                    if cached and cached[2] == port and self.clock() - cached[0] < self.ttl:
                        d.update(cached[1])
                    else:
                        pending[d["serial"]] = pool.submit(
                            self.details, AdbEndpoint(adb, port) if port is not None else adb, d["serial"]
                        )
                for d in devices:
                    future = pending.get(d["serial"])
                    if future is None:
                        continue
                    try:
                        data = future.result()
                        d.update(data)
                        self.cache[d["serial"]] = self.clock(), data, d.get("adb_port")
                    except (RuntimeError, OSError, subprocess.TimeoutExpired):
                        d["connection"] = "offline"
                        self.cache.pop(d["serial"], None)
            self.routes = {d["serial"]: d["adb_port"] for d in devices
                           if d["connection"] == "online" and "adb_port" in d}
            return devices


def scan_devices(adb, *, inventory=None, ports=None, start_if_missing=False):
    return (inventory or DeviceInventory()).scan(adb, ports=ports, start_if_missing=start_if_missing)
