import json
import os
from pathlib import Path
import sys
import time
import uuid
import pytest
from PySide6.QtCore import QObject, Signal, QLockFile
from PySide6.QtTest import QTest
from customer_desktop.paths import prepare_paths
from customer_desktop.runner import Runner
from customer_desktop.process_guard import process_identity
from customer_desktop.services import DesktopService


def until(app, predicate, seconds=8):
    end = time.monotonic() + seconds
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        QTest.qWait(10)
    assert predicate(), "Async operation did not finish"


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("success", "succeeded"),
        ("missing", "needs_review"),
        ("error", "needs_review"),
        ("wait", "needs_review"),
        ("child", "needs_review"),
    ],
)
def test_real_qprocess_stop_and_evidence(app, tmp_path, mode, expected):
    root = prepare_paths(tmp_path)
    job = dict(id=uuid.uuid4().hex, serial="fixture", kind="publish", snapshot="{}")
    aid = uuid.uuid4().hex
    worker = Path(__file__).with_name("fake_worker.py")
    r = Runner(
        root,
        job,
        aid,
        root / "logs" / job["id"] / aid,
        "adb",
        command=(sys.executable, ["-u", str(worker), mode]),
    )
    results = []
    events = []
    r.done.connect(lambda *args: results.append(args))
    r.events.connect(events.extend)
    r.start()
    if mode in ("wait", "child"):
        until(app, lambda: r.gate_path.exists())
        if mode == "child":
            until(app, lambda: any(e.get("type") == "fixture_child" for e in events))
        r.stop()
    until(app, lambda: bool(results))
    assert results[0][0] == expected
    assert any(e.get("message") == "Xin chào 한글" for e in events)
    assert (r.directory / "stdout.jsonl").is_file()
    if mode == "child":
        pid = next(e["pid"] for e in events if e.get("type") == "fixture_child")
        assert process_identity(pid) is None


class FakeRunner(QObject):
    events = Signal(list)
    started = Signal(int, str)
    done = Signal(str, str, dict)
    created = []

    def __init__(self, root, job, aid, directory, adb, parent=None):
        super().__init__(parent)
        self.job = job
        self.stopped = False
        self.created.append(self)

    def start(self):
        self.started.emit(0, "fixture")

    def stop(self):
        self.stopped = True

    def complete(self, state="succeeded"):
        if self.stopped:
            state = "needs_review"
        self.done.emit(state, "fixture", {"state": state})


def test_service_serial_queue_hold_cancel(app, tmp_path):
    FakeRunner.created = []
    s = DesktopService(
        prepare_paths(tmp_path), runner_factory=FakeRunner, prepare=False
    )
    s.timer.stop()
    s.store.discover(
        [dict(serial=x, connection="online", package="test") for x in ("a", "b")]
    )
    s.store.set_setting("max_parallel", 2)
    s.store.set_setting("launch_interval", 0)
    s.submit(
        [
            dict(serial=x, kind="browse", payload={"maxVideos": 1})
            for x in ("a", "a", "b")
        ],
        "submission",
    )
    until(app, lambda: not s.submitting)
    s.tick()

    def both_running():
        s.tick()
        return len(s.runners) == 2

    until(app, both_running)
    assert len({r.job["serial"] for r in s.runners.values()}) == 2
    a = next(r for r in s.runners.values() if r.job["serial"] == "a")
    s.stop_serial("a")
    assert a.stopped and not s.manual_ready("a")
    a.complete()
    until(app, lambda: s.manual_ready("a"))
    s.tick()
    assert not any(r.job["serial"] == "a" for r in s.runners.values())
    waiting = next(j for j in s.store.jobs() if j["state"] == "queued")
    s.cancel(waiting["id"])
    s.release_serial("a")
    s.tick()
    assert not any(r.job["serial"] == "a" for r in s.runners.values())
    for r in list(s.runners.values()):
        r.complete()
    until(app, lambda: not s.runners)
    assert any(j["serial"] == "b" and j["state"] == "succeeded" for j in s.store.jobs())
    s.store.close()


def test_recovery_waits_for_live_identity(app, tmp_path, monkeypatch):
    root = prepare_paths(tmp_path)
    from customer_desktop.storage import Store

    store = Store(root)
    store.discover([dict(serial="a", connection="online")])
    jid = store.enqueue([dict(serial="a", kind="browse", payload={})], "x")[0]
    job = store.claim(1)[0]
    aid = store.attempt(job, root / "logs" / "x")
    store.started(aid, 123, "creation")
    store.close()
    monkeypatch.setattr(
        "customer_desktop.services.process_identity", lambda pid: "creation"
    )
    s = DesktopService(root, prepare=False)
    s.timer.stop()
    s.tick()
    assert s.store.job(jid)["state"] == "validating"
    monkeypatch.setattr("customer_desktop.services.process_identity", lambda pid: None)
    s.tick()
    until(app, lambda: s.store.job(jid)["state"] == "needs_review")
    assert s.store.devices()[0]["hold"]
    assert s.store.attempts(jid)[0]["ended"]
    s.store.close()


def test_single_instance_lock_and_support_redaction(app, tmp_path):
    root = prepare_paths(tmp_path)
    a = QLockFile(str(root / "desktop.lock"))
    b = QLockFile(str(root / "desktop.lock"))
    assert a.tryLock(0)
    assert not b.tryLock(0)
    a.unlock()
    assert b.tryLock(0)
    b.unlock()
    s = DesktopService(root, prepare=False)
    s.timer.stop()
    s.store.discover([dict(serial="PRIVATE_SERIAL", connection="online")])
    s.store.enqueue(
        [
            dict(
                serial="PRIVATE_SERIAL",
                kind="publish",
                payload={
                    "caption": "PRIVATE_CAPTION",
                    "botUsername": "PRIVATE_ACCOUNT",
                },
            )
        ],
        "x",
    )
    import zipfile

    path = s.support_export()
    with zipfile.ZipFile(path) as archive:
        content = archive.read("diagnostics.json").decode()
    assert "PRIVATE_" not in content
    s.store.close()


def test_background_device_refresh_never_accesses_sqlite_from_worker(
    app, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "customer_desktop.services.scan_devices",
        lambda adb, **kwargs: [
            dict(serial="fixture", connection="online", package="test")
        ],
    )
    s = DesktopService(prepare_paths(tmp_path), prepare=False)
    s.timer.stop()
    s.refresh_devices()
    until(app, lambda: not s.scanning)
    assert s.store.devices()[0]["serial"] == "fixture"
    s.store.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object integration")
def test_gui_crash_kills_owned_worker_and_descendants(tmp_path):
    import subprocess

    script = Path(__file__).with_name("crash_owner.py")
    result = subprocess.run(
        [sys.executable, str(script), str(tmp_path)], capture_output=True, timeout=15
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    pids = json.loads((tmp_path / "pids.json").read_text())
    deadline = time.monotonic() + 3
    while (
        any(process_identity(pid) is not None for pid in pids.values())
        and time.monotonic() < deadline
    ):
        time.sleep(0.05)
    assert all(process_identity(pid) is None for pid in pids.values())


def test_wake_marks_schedules_overdue_and_stops_active_sessions(
    app, tmp_path, monkeypatch
):
    current = [time.time()]
    monkeypatch.setattr("customer_desktop.services.time.time", lambda: current[0])
    s = DesktopService(
        prepare_paths(tmp_path), runner_factory=FakeRunner, prepare=False
    )
    s.timer.stop()
    s.store.discover([dict(serial="a", connection="online", package="test")])
    s.submit(
        [
            dict(serial="a", kind="browse", payload={"maxVideos": 1}),
            dict(
                serial="a",
                kind="browse",
                payload={"maxVideos": 1},
                run_at=current[0] + 60,
            ),
        ],
        "wake",
    )
    until(app, lambda: not s.submitting)
    s.tick()
    until(app, lambda: len(s.runners) == 1)
    current[0] += 70
    s.tick()
    assert any(j["state"] == "overdue" for j in s.store.jobs())
    runner = next(iter(s.runners.values()))
    assert runner.stopped
    runner.complete()
    until(app, lambda: not s.runners)
    assert s.store.devices()[0]["hold"]
    s.store.close()


def test_slow_adb_does_not_block_qt_event_loop(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer

    def slow(adb, **kwargs):
        time.sleep(0.3)
        return []

    monkeypatch.setattr("customer_desktop.services.scan_devices", slow)
    s = DesktopService(prepare_paths(tmp_path), prepare=False)
    s.timer.stop()
    ticks = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    s.refresh_devices()
    until(app, lambda: not s.scanning)
    timer.stop()
    assert len(ticks) >= 10
    s.store.close()


def test_log_write_failure_still_finishes_worker_conservatively(
    app, tmp_path, monkeypatch
):
    root = prepare_paths(tmp_path)
    jid = uuid.uuid4().hex
    aid = uuid.uuid4().hex
    job = dict(id=jid, serial="fixture", kind="publish", snapshot="{}")
    worker = Path(__file__).with_name("fake_worker.py")
    r = Runner(
        root,
        job,
        aid,
        root / "logs" / jid / aid,
        "adb",
        command=(sys.executable, ["-u", str(worker), "success"]),
    )

    def full(*args):
        raise OSError("No space left on device")

    monkeypatch.setattr(r.stdout, "write", full)
    results = []
    r.done.connect(lambda *args: results.append(args))
    r.start()
    until(app, lambda: bool(results))
    assert results[0][0] == "needs_review" and r.io_error


def test_stop_works_when_stop_file_cannot_be_written(app, tmp_path, monkeypatch):
    root = prepare_paths(tmp_path)
    jid = uuid.uuid4().hex
    aid = uuid.uuid4().hex
    job = dict(id=jid, serial="fixture", kind="publish", snapshot="{}")
    worker = Path(__file__).with_name("fake_worker.py")
    r = Runner(
        root,
        job,
        aid,
        root / "logs" / jid / aid,
        "adb",
        command=(sys.executable, ["-u", str(worker), "wait"]),
    )
    original = Path.touch

    def touch(path, *args, **kwargs):
        if path.name == "stop.request":
            raise OSError("Disk is read only")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "touch", touch)
    results = []
    r.done.connect(lambda *args: results.append(args))
    r.start()
    until(app, lambda: r.gate_path.exists())
    r.stop()
    until(app, lambda: bool(results))
    assert results[0][0] == "needs_review" and r.io_error


def test_noisy_worker_is_contained_without_unbounded_pipe_memory(app, tmp_path):
    root = prepare_paths(tmp_path)
    jid, aid = uuid.uuid4().hex, uuid.uuid4().hex
    r = Runner(
        root,
        dict(id=jid, serial="fixture", kind="publish", snapshot="{}"),
        aid,
        root / "logs" / jid / aid,
        "adb",
        command=(
            sys.executable,
            ["-u", str(Path(__file__).with_name("fake_worker.py")), "flood"],
        ),
    )
    r.max_buffered = 1024
    results = []
    r.done.connect(lambda *args: results.append(args))
    r.start()
    until(app, lambda: bool(results))
    assert results[0][0] == "needs_review"
    assert r.output_overflow and r.stopped
    assert "vượt giới hạn" in results[0][1]
