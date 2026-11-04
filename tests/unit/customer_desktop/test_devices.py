import threading
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from customer_desktop.devices import scan_devices, DeviceInventory


def test_adb_error_reports_stdout_when_android_omits_stderr(monkeypatch):
    from types import SimpleNamespace
    import pytest
    from customer_desktop.devices import adb_run

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=255, stdout=b"Unknown command: user-rotation\r\n", stderr=b""
    ))
    with pytest.raises(RuntimeError, match="Unknown command: user-rotation"):
        adb_run("adb", ["shell", "wm", "user-rotation"])


def test_inventory_prefers_lite_when_both_apps_are_installed(monkeypatch):
    def run(adb, args, timeout=8):
        if "getprop" in args:
            return "16"
        if "list" in args:
            return "package:com.zhiliaoapp.musically\r\npackage:com.ss.android.ugc.tiktok.lite\r\n"
        return "versionName=47.5.3" if args[-1] == "com.ss.android.ugc.tiktok.lite" else "versionName=47.6.3"

    monkeypatch.setattr("customer_desktop.devices.adb_run", run)
    assert DeviceInventory.details("adb", "phone") == {
        "android": "16", "package": "com.ss.android.ugc.tiktok.lite", "version": "47.5.3",
        "applications": [
            dict(package="com.ss.android.ugc.tiktok.lite", version="47.5.3", version_code=""),
            dict(package="com.zhiliaoapp.musically", version="47.6.3", version_code=""),
        ],
    }


def test_windows_crlf_package_inventory(monkeypatch):
    def run(adb, args, timeout=8):
        if args == ["devices", "-l"]:
            return "List of devices attached\r\ns device model:SO_52A\r\nu unauthorized\r\no offline\r\n"
        if "getprop" in args:
            return "12"
        if "list" in args:
            return "package:android\r\npackage:com.ss.android.ugc.trill\r\n"
        return "versionName=47.4.3\r\nversionCode=470403"

    monkeypatch.setattr("customer_desktop.devices.adb_run", run)
    devices = scan_devices("adb")
    assert devices[0]["package"] == "com.ss.android.ugc.trill"
    assert devices[0]["version"] == "47.4.3"
    assert [d["connection"] for d in devices] == ["online", "unauthorized", "offline"]


def fake_adb(states, calls, fail=None):
    def run(adb, args, timeout=8):
        assert timeout == 8
        calls.append((adb, tuple(args)))
        if args == ["devices", "-l"]:
            return "List of devices attached\n" + "\n".join(
                f"{serial} {state} model:Fixture" for serial, state in states.items()
            )
        if args[1] == fail:
            raise subprocess.TimeoutExpired("fixture-adb", 8)
        if "getprop" in args:
            return "12"
        if "list" in args:
            return "package:com.ss.android.ugc.trill\r\n"
        return "versionName=47.4.3"

    return run


def test_cache_ttl_reconnect_adb_path_and_missing_invalidation(monkeypatch):
    states = {"a": "device", "b": "device"}
    calls = []
    now = [10]
    monkeypatch.setattr("customer_desktop.devices.adb_run", fake_adb(states, calls))
    cache = DeviceInventory(clock=lambda: now[0])
    assert len(scan_devices("adb-A", inventory=cache)) == 2
    calls.clear()
    scan_devices("adb-A", inventory=cache)
    assert calls == [("adb-A", ("devices", "-l"))]
    now[0] += 60
    calls.clear()
    scan_devices("adb-A", inventory=cache)
    assert len(calls) == 7
    states["a"] = "unauthorized"
    scan_devices("adb-A", inventory=cache)
    states["a"] = "device"
    calls.clear()
    scan_devices("adb-A", inventory=cache)
    assert Counter(args[1] for _, args in calls if args[0] == "-s") == {"a": 3}
    states.pop("b")
    scan_devices("adb-A", inventory=cache)
    assert "b" not in cache.cache
    calls.clear()
    scan_devices("adb-B", inventory=cache)
    assert len(calls) == 4


def test_fifty_devices_have_at_most_four_detail_workers_and_stable_order(monkeypatch):
    states = {f"fixture-{i:02}": "device" for i in range(50)}
    calls = []
    lock = threading.Lock()
    gate = threading.Event()
    four_started = threading.Event()
    active = [0]
    peak = [0]
    underlying = fake_adb(states, calls)

    def run(adb, args, timeout=8):
        if "getprop" in args:
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
                if active[0] == 4:
                    four_started.set()
            assert gate.wait(3)
            with lock:
                active[0] -= 1
        return underlying(adb, args, timeout)

    monkeypatch.setattr("customer_desktop.devices.adb_run", run)
    cache = DeviceInventory()
    with ThreadPoolExecutor(max_workers=1) as owner:
        future = owner.submit(scan_devices, "adb", inventory=cache)
        try:
            assert four_started.wait(3)
            assert not future.done()
        finally:
            gate.set()
        devices = future.result(timeout=5)
    assert peak[0] == 4
    assert [d["serial"] for d in devices] == list(states)
    assert all(d["connection"] == "online" for d in devices)
    calls.clear()
    scan_devices("adb", inventory=cache)
    assert len(calls) == 1


def test_one_metadata_timeout_isolated_and_retried_next_scan(monkeypatch):
    states = {"a": "device", "b": "device", "c": "offline"}
    calls = []
    cache = DeviceInventory()
    monkeypatch.setattr(
        "customer_desktop.devices.adb_run", fake_adb(states, calls, fail="a")
    )
    devices = scan_devices("adb", inventory=cache)
    assert [d["connection"] for d in devices] == ["offline", "online", "offline"]
    assert "a" not in cache.cache
    calls.clear()
    monkeypatch.setattr("customer_desktop.devices.adb_run", fake_adb(states, calls))
    devices = scan_devices("adb", inventory=cache)
    assert devices[0]["connection"] == "online"
    assert len(calls) == 4  # cached healthy b, refresh only a


def test_no_tiktok_result_is_cached(monkeypatch):
    calls = []

    def run(adb, args, timeout=8):
        calls.append(args)
        return (
            "s device"
            if args == ["devices", "-l"]
            else "12" if "getprop" in args else "package:android"
        )

    monkeypatch.setattr("customer_desktop.devices.adb_run", run)
    cache = DeviceInventory()
    assert scan_devices("adb", inventory=cache)[0]["package"] == ""
    calls.clear()
    scan_devices("adb", inventory=cache)
    assert calls == [["devices", "-l"]]
