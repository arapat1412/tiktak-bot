import json
import os
import socket
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from customer_desktop import adb_server, devices
from customer_desktop.adb_server import AdbEndpoint
from customer_desktop.paths import prepare_paths
from customer_desktop.runner import Runner, environment
from customer_desktop.services import DesktopService


@contextmanager
def protocol_server(response):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    errors = []

    def serve():
        try:
            with listener.accept()[0] as connection:
                message = b""
                while len(message) < 18:
                    message += connection.recv(18 - len(message))
                assert message == b"000ehost:devices-l"
                for chunk in response:
                    connection.sendall(chunk)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1]
    finally:
        listener.close()
        thread.join(2)
        assert not thread.is_alive()
        assert not errors


def test_smart_socket_handles_fragmented_inventory_without_cli():
    body = b"phone\tdevice model:Fixture\n"
    response = b"OKAY" + f"{len(body):04x}".encode() + body
    with protocol_server([response[i:i+1] for i in range(len(response))]) as port:
        assert adb_server.query_devices(port) == body.decode()


def test_closed_local_port_is_refused_before_default_probe_timeout():
    # Keep the port reserved without listening. On Windows refusal takes about
    # two seconds; a two-second deadline incorrectly reports TimeoutError and
    # prevents the existing cold-start path from launching ADB.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        with pytest.raises(ConnectionRefusedError):
            adb_server.query_devices(reserved.getsockname()[1])


@pytest.mark.parametrize("response", [b"FAIL0004oops", b"OKAYxxxx", b"OKAY0005abc", b"HTTP"])
def test_smart_socket_rejects_failure_malformed_eof_and_non_adb(response):
    with protocol_server([response]) as port:
        with pytest.raises(RuntimeError):
            adb_server.query_devices(port)


def test_process_discovery_includes_only_local_adb_listeners(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args[0])
        assert kwargs["timeout"] == 2 and kwargs["check"]
        if args[0] == "tasklist":
            return SimpleNamespace(stdout=b'"adb.exe","123","Console","1","200 K"\n')
        return SimpleNamespace(stdout=(
            b" TCP 127.0.0.1:5040 0.0.0.0:0 LISTENING 123\n"
            b" TCP 127.0.0.1:5041 0.0.0.0:0 ESTABLISHED 123\n"
            b" TCP 192.168.0.2:5042 0.0.0.0:0 LISTENING 123\n"
            b" TCP 127.0.0.1:5043 0.0.0.0:0 LISTENING 999\n"
        ))

    monkeypatch.setattr(adb_server.subprocess, "run", run)
    assert adb_server._windows_adb_ports() == [5040]
    assert calls == ["tasklist", "netstat"]


def test_discovery_does_not_treat_forwarded_socket_as_server(monkeypatch):
    monkeypatch.setattr(adb_server, "_windows_adb_ports", lambda: [5037, 5038, 5040, 17912])

    def query(port, timeout):
        assert timeout <= 0.25
        if port == 17912:
            raise RuntimeError("HTTP is not ADB")
        return ""

    monkeypatch.setattr(adb_server, "query_devices", query)
    assert adb_server.discover_server_ports(5038) == (5038, 5037, 5040)


def test_discovery_failure_keeps_known_and_configured_ports(monkeypatch):
    monkeypatch.setattr(adb_server.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        subprocess.TimeoutExpired("tasklist", 2)
    ))
    assert adb_server.discover_server_ports(5044) == (5044, 5037, 5038)


def fake_metadata(calls):
    def run(adb, args, timeout=8):
        assert args[0] == "-s", "Inventory must not launch the ADB CLI"
        calls.append((adb.port, args[1]))
        if "getprop" in args:
            return "11"
        if "list" in args:
            return "package:com.ss.android.ugc.tiktok.lite"
        return "versionName=47.5.3"
    return run


def test_split_inventory_deduplicates_online_and_invalidates_moved_cache(monkeypatch):
    listings = {
        5037: "a device\nb device\nc device\nshared offline\n",
        5038: "d device\ne device\nf device\ng device\nshared device\n",
    }
    calls = []
    monkeypatch.setattr(devices, "query_devices", lambda port: listings[port])
    monkeypatch.setattr(devices, "adb_run", fake_metadata(calls))
    inventory = devices.DeviceInventory()
    found = inventory.scan("adb", ports=(5037, 5038))
    assert len(found) == 8 and all(d["connection"] == "online" for d in found)
    assert inventory.routes["shared"] == 5038
    calls.clear()
    inventory.scan("adb", ports=(5038, 5037))
    assert calls == []
    listings[5037] = listings[5037].replace("a device\n", "")
    listings[5038] += "a device\n"
    inventory.scan("adb", ports=(5037, 5038))
    assert calls == [(5038, "a")] * 3
    assert inventory.routes["a"] == 5038
    # Both online: retain the existing route despite changed scan priority.
    listings[5037] += "a device\n"
    inventory.scan("adb", ports=(5037, 5038))
    assert inventory.routes["a"] == 5038


def test_one_server_down_does_not_hide_healthy_phones(monkeypatch):
    def query(port):
        if port == 5037:
            raise ConnectionRefusedError("closed")
        return "a device\nb unauthorized\n"
    monkeypatch.setattr(devices, "query_devices", query)
    monkeypatch.setattr(devices, "adb_run", fake_metadata([]))
    found = devices.scan_devices("adb", ports=(5037, 5038))
    assert [(d["serial"], d["connection"]) for d in found] == [("a", "online"), ("b", "unauthorized")]
    with pytest.raises(RuntimeError, match="5037"):
        devices.scan_devices("adb", ports=(5037,))


def test_cold_start_opens_only_preferred_server_when_all_connections_refused(monkeypatch):
    monkeypatch.setattr(devices, "query_devices", lambda port: (_ for _ in ()).throw(
        ConnectionRefusedError("No server")
    ))
    seen = []
    def run(adb, args, **kwargs):
        seen.append((adb.port,args))
        return ""
    monkeypatch.setattr(devices,"adb_run",run)
    assert devices.scan_devices("adb",ports=(5038,5037),start_if_missing=True) == []
    assert seen == [(5038,["devices","-l"])]


def test_unresponsive_server_is_not_replaced_on_cold_start(monkeypatch):
    monkeypatch.setattr(devices, "query_devices", lambda port: (_ for _ in ()).throw(
        TimeoutError("busy")
    ))
    monkeypatch.setattr(devices,"adb_run",lambda *a,**kw:pytest.fail("Must not start server"))
    with pytest.raises(RuntimeError):
        devices.scan_devices("adb",ports=(5038,),start_if_missing=True)


def test_metadata_pool_bound_is_shared_across_ports(monkeypatch):
    monkeypatch.setattr(devices, "query_devices", lambda port: "\n".join(
        f"{port}-{i} device" for i in range(6)
    ))
    underlying = fake_metadata([])
    lock, gate, four = threading.Lock(), threading.Event(), threading.Event()
    active, peak = [0], [0]

    def run(adb, args, timeout=8):
        if "getprop" in args:
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
                if active[0] == 4:
                    four.set()
            assert gate.wait(3)
            with lock:
                active[0] -= 1
        return underlying(adb, args, timeout)

    monkeypatch.setattr(devices, "adb_run", run)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(devices.scan_devices, "adb", ports=(5037, 5038))
        try:
            assert four.wait(3)
        finally:
            gate.set()
        assert len(result.result(timeout=3)) == 12
    assert peak[0] == 4


def test_commands_on_two_ports_do_not_mutate_shared_environment(monkeypatch):
    monkeypatch.setenv("ANDROID_ADB_SERVER_PORT", "5999")
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:127.0.0.1:5999")
    calls = []

    def run(args, **kwargs):
        calls.append((args[2], kwargs["env"]))
        return SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr(devices.subprocess, "run", run)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda port: devices.adb_run(
            AdbEndpoint("adb", port), ["-s", str(port), "get-state"]
        ), (5037, 5038)))
    assert results == ["ok", "ok"]
    for serial, env in calls:
        assert env["ANDROID_ADB_SERVER_PORT"] == serial
        assert env["ADB_SERVER_SOCKET"] == f"tcp:127.0.0.1:{serial}"
    assert os.environ["ANDROID_ADB_SERVER_PORT"] == "5999"
    assert os.environ["ADB_SERVER_SOCKET"] == "tcp:127.0.0.1:5999"


@pytest.mark.parametrize("port", [5037, 5038])
def test_child_cli_and_adbutils_receive_same_port(tmp_path, port):
    env = environment(tmp_path, AdbEndpoint("adb", port))
    command = ("import json,os; from adbutils import AdbClient; "
               "print(json.dumps([AdbClient().port,os.environ['ADB_SERVER_SOCKET']]))")
    result = subprocess.run([sys.executable, "-c", command], capture_output=True,
                            env={key:env.value(key) for key in env.keys()}, timeout=10, check=True)
    assert json.loads(result.stdout) == [port, f"tcp:127.0.0.1:{port}"]


def test_recovery_uses_saved_endpoint_but_finds_device_after_move(tmp_path, monkeypatch):
    (tmp_path / "keyboard.json").write_text("{}")
    (tmp_path / "adb-server.json").write_text('{"port":5038}')
    seen = []
    monkeypatch.setattr(adb_server, "discover_server_ports", lambda primary: (primary, 5037))

    def query(port):
        seen.append(port)
        return "phone offline" if port == 5038 else "phone device"

    monkeypatch.setattr(adb_server, "query_devices", query)
    target = adb_server.recovery_endpoint(AdbEndpoint("adb", 5040), "phone", tmp_path)
    assert target.port == 5037 and seen == [5038, 5037]


def test_runner_pins_endpoint_and_records_it_for_crash_recovery(app, tmp_path):
    root = prepare_paths(tmp_path)
    folder = root / "logs/job/attempt"
    job = dict(id="job", serial="phone", kind="browse", snapshot='{"maxVideos":1}')
    runner = Runner(root, job, "attempt", folder, AdbEndpoint("adb", 5037))
    try:
        assert runner.p.processEnvironment().value("ANDROID_ADB_SERVER_PORT") == "5037"
        assert json.loads((folder / "adb-server.json").read_text()) == {"port":5037}
        assert runner.adb.port == 5037
    finally:
        runner.stdout.close()
        runner.stderr.close()
        runner.deleteLater()
        app.processEvents()


def test_service_launch_and_keyboard_batch_use_each_devices_route(app, tmp_path, monkeypatch):
    seen = []
    def factory(root, job, attempt, directory, adb, parent):
        seen.append((job["serial"], adb.port))
        raise RuntimeError("Fixture stops before creating a real worker")

    service = DesktopService(prepare_paths(tmp_path), runner_factory=factory, prepare=False)
    service.timer.stop()
    monkeypatch.setattr(DesktopService, "admission_reason", property(lambda self: ""))
    service.store.discover([dict(serial=s,connection="online",package="fixture") for s in ("a","b")])
    service.device_ports = {"a":5037,"b":5038}
    service.store.enqueue([dict(serial=s,kind="browse",payload={"maxVideos":1}) for s in ("a","b")],"fixture")
    try:
        for job in service.store.claim(2):
            service._launch(job)
        assert seen == [("a",5037),("b",5038)]
        seen.clear()
        monkeypatch.setattr("customer_desktop.services.install_keyboard", lambda adb, serial: (
            seen.append((serial,adb.port)) or {"already_installed":True}
        ))
        monkeypatch.setattr(service,"background",lambda fn,done,fail,**kw:done(fn()))
        service.install_device_keyboards(["a","b"])
        assert seen == [("a",5037),("b",5038)]
    finally:
        service.store.close()


def test_route_move_stops_only_affected_worker(app, tmp_path, monkeypatch):
    service = DesktopService(prepare_paths(tmp_path), prepare=False)
    service.timer.stop()
    stopped = []
    service.runners = {
        "ja":SimpleNamespace(job={"serial":"a"},adb=AdbEndpoint("adb",5037)),
        "jb":SimpleNamespace(job={"serial":"b"},adb=AdbEndpoint("adb",5038)),
    }
    monkeypatch.setattr(service,"stop_serial",stopped.append)
    monkeypatch.setattr(service,"background",lambda fn,done,fail,**kw:done(fn()))
    monkeypatch.setattr("customer_desktop.services.discover_server_ports",lambda p:(5037,5038))
    monkeypatch.setattr("customer_desktop.services.scan_devices",lambda *a,**kw:[
        dict(serial="a",connection="online",adb_port=5038),
        dict(serial="b",connection="online",adb_port=5038),
    ])
    try:
        service.refresh_devices()
        assert stopped == ["a"]
        assert service.adb_for("a").port == 5038
    finally:
        service.runners.clear()
        service.store.close()
