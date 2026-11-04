import json
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal

from customer_desktop.adapters.taktik.protocol import ResultTracker
from customer_desktop.paths import prepare_paths
from customer_desktop.services import DesktopService
from customer_desktop.storage import Store
from customer_desktop.ui import MainWindow


class ProfileRunner(QObject):
    events = Signal(list)
    started = Signal(int, str)
    done = Signal(str, str, dict)

    def __init__(self, root, job, aid, directory, adb, parent=None):
        super().__init__(parent)
        self.job = job
        self.stopped = False
        self.tracker = ResultTracker(job["kind"])

    def start(self):
        pass


def launch_service(tmp_path, monkeypatch):
    s = DesktopService(
        prepare_paths(tmp_path), runner_factory=ProfileRunner, prepare=False
    )
    s.timer.stop()
    s.store.set_setting("onboarded", True)
    s.refresh_devices = lambda: None
    s.store.discover(
        [
            dict(serial=serial, connection="online", package="fixture")
            for serial in ("a", "b")
        ]
    )
    monkeypatch.setattr(DesktopService, "admission_reason", property(lambda self: ""))
    specs = [
        dict(serial=serial, kind="browse", payload={"maxVideos": 1})
        for serial in ("a", "b")
    ]
    s.store.enqueue(specs, "profiles")
    for job in s.store.claim(2):
        s._launch(job)
    return s


def profile(username):
    return {
        "type": "bot_profile",
        "profile": {"username": username, "display_name": "이름"},
    }


def test_real_runner_event_updates_correct_device_and_visible_account(
    app, tmp_path, monkeypatch
):
    s = launch_service(tmp_path, monkeypatch)
    snapshots = [j["snapshot"] for j in s.store.jobs()]
    a = next(r for r in s.runners.values() if r.job["serial"] == "a")
    b = next(r for r in s.runners.values() if r.job["serial"] == "b")
    s.store.save_device("a", "Custom phone", "Group", "manual-label", hold=True)
    a.events.emit([profile("@own.a") | {"deviceId": "b"}])
    b.events.emit([profile("own_b")])
    devices = {d["serial"]: d for d in s.store.devices()}
    assert devices["a"]["account"] == "own.a"
    assert devices["b"]["account"] == "own_b"
    assert (devices["a"]["name"], devices["a"]["group_name"], devices["a"]["hold"]) == (
        "Custom phone",
        "Group",
        1,
    )
    assert snapshots == [j["snapshot"] for j in s.store.jobs()]
    w = MainWindow(s)
    w.refresh_timer.stop()
    assert {w.device_table.item(row, 3).text() for row in range(2)} == {
        "@own.a",
        "@own_b",
    }
    a.events.emit([profile("changed.a")])
    w.refresh()
    assert "@changed.a" in {w.device_table.item(row, 3).text() for row in range(2)}
    w.allow_close = True
    w.close()
    s.flush_events()
    s.store.close()
    reopened = Store(tmp_path)
    assert {d["serial"]: d["account"] for d in reopened.devices()} == {
        "a": "changed.a",
        "b": "own_b",
    }
    reopened.close()


def test_visited_profiles_logs_and_stopped_or_removed_workers_do_not_assign(
    app, tmp_path, monkeypatch
):
    s = launch_service(tmp_path, monkeypatch)
    a = next(r for r in s.runners.values() if r.job["serial"] == "a")
    a.events.emit(
        [
            {"type": "profile_captured", "username": "someone.else"},
            {"type": "video_info", "author": "someone.else"},
            {"type": "log", "message": "Bot account: @not.evidence"},
            {"type": "bot_profile", "profile": None},
        ]
    )
    assert all(not d["account"] for d in s.store.devices())
    a.stopped = True
    a.events.emit([profile("stopped")])
    a.stopped = False
    s.runners.pop(a.job["id"])
    a.events.emit([profile("stale")])
    assert all(not d["account"] for d in s.store.devices())
    s.flush_events()
    s.store.close()


@pytest.mark.parametrize(
    "value", [None, {}, [], "", "@", "two words", "a/b", "a\\b", "name\nnext", "a" * 65]
)
def test_malformed_account_does_not_clear_existing_label(tmp_path, value):
    store = Store(prepare_paths(tmp_path))
    store.discover([dict(serial="a", connection="online")])
    store.save_device("a", "Phone", "Group", "existing")
    assert not store.observe_account("a", value)
    assert store.devices()[0]["account"] == "existing"
    store.close()


def test_restart_backfills_latest_own_profile_only_and_preserves_manual_labels(
    tmp_path,
):
    store = Store(prepare_paths(tmp_path))
    store.discover(
        [dict(serial=serial, connection="online") for serial in ("a", "b", "c")]
    )
    store.save_device("b", "B", "", "manual")
    for serial in ("a", "b", "c"):
        jid = store.enqueue([dict(serial=serial, kind="browse", payload={})], serial)[0]
        aid = store.attempt(store.job(jid), Path(tmp_path) / serial)
        events = [
            profile("old." + serial),
            profile("latest." + serial),
            {"type": "profile_captured", "username": "other.account"},
        ]
        if serial == "c":
            events = [{"type": "profile_captured", "username": "other.account"}]
        store.events(aid, events, 0)
    store.close()
    reopened = Store(tmp_path)
    assert {d["serial"]: d["account"] for d in reopened.devices()} == {
        "a": "latest.a",
        "b": "manual",
        "c": "",
    }
    assert not reopened.observe_account("a", "@latest.a")
    reopened.close()


def test_large_avatar_keeps_compact_username_event_for_restart(
    app, tmp_path, monkeypatch
):
    s = launch_service(tmp_path, monkeypatch)
    a = next(r for r in s.runners.values() if r.job["serial"] == "a")
    event = profile("large.avatar")
    event["profile"]["profile_pic_base64"] = "x" * 20000
    a.events.emit([event])
    s.flush_events()
    payload = json.loads(
        s.store.rows("SELECT payload FROM job_events WHERE type='bot_profile'")[0][
            "payload"
        ]
    )
    assert payload["profile"] == {"username": "large.avatar"}
    assert len(json.dumps(payload)) < 8192
    s.store.db.execute("UPDATE devices SET account='' WHERE serial='a'")
    s.store.db.commit()
    s.store.close()
    reopened = Store(tmp_path)
    assert (
        next(d["account"] for d in reopened.devices() if d["serial"] == "a")
        == "large.avatar"
    )
    reopened.close()


@pytest.mark.parametrize("inside", [True, False])
def test_legacy_oversized_profile_recovers_only_from_local_bounded_raw_log(
    tmp_path, inside
):
    root = prepare_paths(tmp_path / "app")
    store = Store(root)
    store.discover([dict(serial="a", connection="online")])
    jid = store.enqueue([dict(serial="a", kind="browse", payload={})], "legacy")[0]
    directory = (root / "logs" / "job" / "attempt") if inside else tmp_path / "outside"
    directory.mkdir(parents=True)
    event = profile("legacy.owner")
    event["profile"]["profile_pic_base64"] = "x" * 20000
    (directory / "stdout.jsonl").write_text(
        json.dumps(event)
        + "\n"
        + json.dumps({"type": "profile_captured", "username": "other.person"})
        + "\n",
        encoding="utf-8",
    )
    aid = store.attempt(store.job(jid), directory)
    store.events(
        aid, [{"type": "bot_profile", "raw_log": "stdout.jsonl", "bytes": 21000}], 0
    )
    store.close()
    reopened = Store(root)
    assert reopened.devices()[0]["account"] == ("legacy.owner" if inside else "")
    reopened.close()
