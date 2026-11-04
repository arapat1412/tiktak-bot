"""Multi-device admission and isolation, without any real ADB or public actions."""

import json
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QTest

from customer_desktop.capacity import (
    capacity_reason,
    parallel_limit,
    launch_interval,
    MIB,
)
from customer_desktop.paths import prepare_paths
from customer_desktop.services import DesktopService
from customer_desktop.storage import ACTIVE


def wait(app, condition, seconds=5):
    import time

    end = time.monotonic() + seconds
    while not condition() and time.monotonic() < end:
        app.processEvents()
        QTest.qWait(2)
    assert condition()


class Worker(QObject):
    events = Signal(list)
    started = Signal(int, str)
    done = Signal(str, str, dict)

    def __init__(self, root, job, aid, directory, adb, parent=None):
        super().__init__(parent)
        self.job, self.aid = job, aid
        self.stopped = False
        self.tracker = SimpleNamespace(stats={})

    def start(self):
        self.started.emit(0, "fixture")

    def stop(self):
        self.stopped = True

    def complete(self, state="succeeded"):
        if self.stopped:
            state = "needs_review"
        self.done.emit(state, "fixture", {"state": state})


def service(tmp_path, count=50, timed_minutes=0):
    now = [100.0]
    s = DesktopService(
        prepare_paths(tmp_path),
        runner_factory=Worker,
        prepare=False,
        clock=lambda: now[0],
    )
    s.timer.stop()
    s.capacity, s.capacity_at = {"reason": ""}, now[0]
    s.next_capacity = float("inf")
    s.store.discover(
        [
            dict(serial=f"fake-{i:02}", connection="online", package="fixture")
            for i in range(count)
        ]
    )
    s.store.set_setting("max_parallel", 50)
    specs = [
        dict(
            serial=d["serial"],
            kind="browse",
            payload={"maxVideos": 1}
            | (
                {"browseProfile": "natural", "runDurationMinutes": timed_minutes}
                if timed_minutes
                else {}
            ),
        )
        for d in s.store.devices()
    ]
    s.store.enqueue(specs + specs, "load")
    return s, now


def dispatch(app, s, now):
    # A fresh sample each step; test clock advances faster than physical time.
    s.capacity_at = now[0]
    s.tick()
    wait(app, lambda: not s.validating)


def cleanup(app, s):
    for runner in list(s.runners.values()):
        runner.complete()
    wait(app, lambda: not s.runners and not s.tasks)
    s.store.close()
    s.deleteLater()


def test_fifty_serials_start_staggered_cap_and_hold_until_cleanup(app, tmp_path):
    s, now = service(tmp_path)
    for i in range(50):
        dispatch(app, s, now)
        assert len(s.runners) == i + 1
        dispatch(app, s, now)  # same moment must not start another
        assert len(s.runners) == i + 1
        now[0] += 2
    assert len({r.job["serial"] for r in s.runners.values()}) == 50
    dispatch(app, s, now)
    assert len(s.runners) == 50
    s.store.set_setting("max_parallel", 3)  # lowering cap never kills active jobs
    dispatch(app, s, now)
    assert len(s.runners) == 50
    first = next(iter(s.runners.values()))
    s.stop_serial(first.job["serial"])
    assert first.stopped
    assert not s.manual_ready(first.job["serial"])
    first.complete()
    wait(app, lambda: s.manual_ready(first.job["serial"]))
    assert s.store.job(first.job["id"])["state"] == "needs_review"
    assert next(d for d in s.store.devices() if d["serial"] == first.job["serial"])[
        "hold"
    ]
    dispatch(app, s, now)
    assert len(s.runners) == 49
    cleanup(app, s)


def test_fifty_worker_events_are_batched_and_final_events_persist(app, tmp_path):
    s, now = service(tmp_path)
    for _ in range(50):
        dispatch(app, s, now)
        now[0] += 2
    statements = []
    s.store.db.set_trace_callback(statements.append)
    for r in s.runners.values():
        r.events.emit(
            [dict(type="log", message="fixture", number=i) for i in range(20)]
        )
    assert not any(q.startswith("INSERT OR IGNORE INTO job_events") for q in statements)
    s.flush_events()
    assert sum(q == "BEGIN IMMEDIATE" for q in statements) == 1
    assert s.store.db.execute("SELECT COUNT(*) FROM job_events").fetchone()[0] == 1000
    r = next(iter(s.runners.values()))
    r.events.emit([dict(type="video_result", stats={"videos_watched": 1})])
    aid = r.aid
    r.complete()
    wait(app, lambda: r.job["id"] not in s.runners)
    last = s.store.rows(
        "SELECT * FROM job_events WHERE attempt_id=? ORDER BY seq DESC LIMIT 1", (aid,)
    )[0]
    assert last["seq"] == 20 and json.loads(last["payload"])["type"] == "video_result"
    cleanup(app, s)


def test_cleanup_is_not_starved_by_busy_validation_pool(app, tmp_path):
    s, now = service(tmp_path, count=1)
    dispatch(app, s, now)
    release = threading.Event()
    for _ in range(3):
        s.background(lambda: release.wait(5), lambda _: None)
    try:
        r = next(iter(s.runners.values()))
        s.stop_serial(r.job["serial"])
        r.complete()
        wait(app, lambda: not s.runners, seconds=2)
        assert not release.is_set()
    finally:
        release.set()
        cleanup(app, s)


def test_resource_guard_blocks_new_starts_but_stops_work_and_stale_fails_closed(
    app, tmp_path
):
    s, now = service(tmp_path, count=2)
    dispatch(app, s, now)
    s.capacity = {"reason": "RAM trống thấp"}
    now[0] += 2
    dispatch(app, s, now)
    assert len(s.runners) == 1
    r = next(iter(s.runners.values()))
    s.stop_serial(r.job["serial"])
    assert r.stopped
    s.capacity = {"reason": ""}
    now[0] += 20
    s.tick()
    assert "cũ" in s.admission_reason
    assert len(s.runners) == 1
    dispatch(app, s, now)
    assert len(s.runners) == 2
    cleanup(app, s)


def test_inventory_failure_does_not_stop_other_devices(app, tmp_path, monkeypatch):
    s, now = service(tmp_path, count=3)
    for _ in range(3):
        dispatch(app, s, now)
        now[0] += 2
    monkeypatch.setattr(
        "customer_desktop.services.scan_devices",
        lambda *a, **kw: [
            dict(serial="fake-00", connection="offline"),
            *[
                dict(serial=f"fake-{i:02}", connection="online", package="fixture")
                for i in (1, 2)
            ],
        ],
    )
    s.refresh_devices()
    wait(app, lambda: not s.scanning)
    assert {r.job["serial"]: r.stopped for r in s.runners.values()} == {
        "fake-00": True,
        "fake-01": False,
        "fake-02": False,
    }
    cleanup(app, s)


def test_atomic_claim_batch_does_not_overreserve_or_duplicate_devices(tmp_path):
    s, _ = service(tmp_path)
    try:
        assert len(s.store.claim(50, max_new=2)) == 2
        assert len(s.store.claim(50, max_new=100)) == 48
        assert s.store.claim(50, max_new=2) == []
        rows = s.store.rows(
            "SELECT serial,COUNT(*) n FROM jobs WHERE state='validating' GROUP BY serial"
        )
        assert len(rows) == 50 and all(r["n"] == 1 for r in rows)
        assert len([j for j in s.store.jobs() if j["state"] in ACTIVE]) == 50
    finally:
        s.store.close()


@pytest.mark.parametrize(
    "value,expected", [(0, 1), (500, 50), (12, 12), (None, 1), ("bad", 1)]
)
def test_parallel_setting_is_bounded(value, expected):
    assert parallel_limit(value) == expected


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 61, "bad"])
def test_launch_setting_rejects_nonfinite_or_invalid(value):
    assert launch_interval(value) == 2


def test_resource_thresholds():
    assert "Đĩa" in capacity_reason(100 * MIB, 4096 * MIB, 8192 * MIB)
    assert "RAM" in capacity_reason(4096 * MIB, 100 * MIB, 8192 * MIB)
    assert "RAM" in capacity_reason(4096 * MIB, 600 * MIB, 32768 * MIB)
    assert capacity_reason(4096 * MIB, 2048 * MIB, 32768 * MIB) == ""


def test_probe_failure_and_recovery_never_claims_without_measurement(app, tmp_path):
    calls = [0]

    def probe(root):
        calls[0] += 1
        if calls[0] == 1:
            raise OSError("fixture capacity failure")
        return {"reason": ""}

    s, now = service(tmp_path, count=1)
    s.capacity_probe = probe
    s.capacity_at = None
    s.next_capacity = 0
    s.tick()
    wait(app, lambda: not s.capacity_pending)
    assert "Không đo" in s.admission_reason
    assert not s.runners and not s.validating
    now[0] += 5
    s.tick()
    wait(app, lambda: len(s.runners) == 1)
    cleanup(app, s)


def test_shutdown_fifty_holds_all_and_releases_only_after_cleanup(app, tmp_path):
    s, now = service(tmp_path)
    for _ in range(50):
        dispatch(app, s, now)
        now[0] += 2
    s.shutdown()
    assert all(r.stopped for r in s.runners.values())
    assert all(d["hold"] for d in s.store.devices())
    ready = []
    s.closing_ready.connect(lambda: ready.append(True))
    for r in list(s.runners.values()):
        r.complete()
    wait(app, lambda: not s.runners and not s.tasks)
    s.tick()
    assert ready
    assert all(j["state"] in ("needs_review", "queued") for j in s.store.jobs())
    cleanup(app, s)


def test_stale_inventory_or_adb_error_blocks_admission(app, tmp_path):
    s, now = service(tmp_path, count=1)
    s.poll_devices = True
    s.next_inventory = float("inf")
    dispatch(app, s, now)
    assert not s.runners and "kết nối" in s.admission_reason
    s.inventory_at = now[0]
    s.inventory_error = "fixture ADB failed"
    dispatch(app, s, now)
    assert not s.runners and "ADB" in s.admission_reason
    s.inventory_error = ""
    dispatch(app, s, now)
    assert len(s.runners) == 1
    cleanup(app, s)


def test_fifty_timed_phones_overlap_without_settings_or_clock_advance(app, tmp_path):
    s, now = service(tmp_path, timed_minutes=30)
    s.store.set_setting("max_parallel", 1)
    s.store.set_setting("launch_interval", 60)
    s.next_launch = now[0] + 60  # Even an earlier ordinary launch cannot delay them.
    snapshots = {j["id"]: j["snapshot"] for j in s.store.jobs()}
    pending_counts = []
    original_background = s.background

    def background(*args, **kwargs):
        pending_counts.append(len(s.validating))
        original_background(*args, **kwargs)

    s.background = background
    try:
        s.tick()
        wait(app, lambda: len(s.runners) == 50 and not s.validating)
        assert now[0] == 100
        assert max(pending_counts) <= 4
        assert len({r.job["serial"] for r in s.runners.values()}) == 50
        assert all(
            json.loads(r.job["snapshot"])["runDurationMinutes"] == 30
            for r in s.runners.values()
        )
        assert s.store.setting("max_parallel") == 1
        assert s.store.setting("launch_interval") == 60
        assert s.next_launch == 160
        assert {j["id"]: j["snapshot"] for j in s.store.jobs()} == snapshots
        assert sum(j["state"] == "queued" for j in s.store.jobs()) == 50
    finally:
        cleanup(app, s)


def test_timed_batch_never_exceeds_fifty_and_refills_after_cleanup(app, tmp_path):
    s, now = service(tmp_path, count=55, timed_minutes=30)
    s.store.set_setting("max_parallel", 1)
    try:
        s.tick()
        wait(app, lambda: len(s.runners) == 50 and not s.validating)
        first = next(iter(s.runners.values()))
        first.complete()
        wait(app, lambda: len(s.runners) == 49 and not s.tasks)
        s.tick()
        wait(app, lambda: len(s.runners) == 50 and not s.validating)
        assert len({r.job["serial"] for r in s.runners.values()}) == 50
        assert first.job["serial"] not in {r.job["serial"] for r in s.runners.values()}
    finally:
        cleanup(app, s)


def test_timed_preparation_rechecks_resource_guard_and_stop(app, tmp_path):
    s, now = service(tmp_path, count=8, timed_minutes=30)
    s.store.set_setting("max_parallel", 1)

    class ResourceDrops(Worker):
        def start(self):
            super().start()
            s.capacity = {"reason": "RAM trống thấp"}

    s.runner_factory = ResourceDrops
    try:
        s.tick()
        wait(app, lambda: len(s.runners) == 1 and not s.validating and not s.tasks)
        assert sum(j["state"] == "queued" for j in s.store.jobs()) == 15
        s.stop_serial(next(iter(s.runners.values())).job["serial"])
        assert next(iter(s.runners.values())).stopped
        dispatch(app, s, now)
        assert len(s.runners) == 1
        s.capacity = {"reason": ""}
        s.runner_factory = Worker
        s.tick()
        wait(app, lambda: len(s.runners) == 8 and not s.validating)
    finally:
        cleanup(app, s)
