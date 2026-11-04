"""Per-phone choices apply only to newly submitted, immutable job snapshots."""

import json
import time
from copy import deepcopy

import pytest

from customer_desktop.adb_server import AdbEndpoint
from customer_desktop.domain import build_browse
from customer_desktop.paths import prepare_paths
from customer_desktop.services import DesktopService, import_specs
from customer_desktop.storage import Store

LITE = "com.ss.android.ugc.tiktok.lite"
FULL = "com.ss.android.ugc.trill"
APPS = [dict(package=LITE, version="47.5.3"), dict(package=FULL, version="47.6.3")]


def discover(store, apps=APPS):
    store.discover(
        [
            dict(
                serial="phone",
                model="Fixture",
                connection="online",
                package=LITE,
                version="47.5.3",
                applications=apps,
            )
        ]
    )


def test_choice_survives_refresh_restart_missing_app_and_does_not_edit_old_jobs(
    tmp_path,
):
    store = Store(tmp_path)
    discover(store)
    snapshot = {"deviceId": "phone", "maxVideos": 7}
    store.enqueue([dict(serial="phone", kind="browse", payload=snapshot)], "legacy")
    before = store.jobs()[0]["snapshot"]
    store.select_tiktok_app("phone", FULL)
    discover(store)
    d = store.devices()[0]
    assert (d["package"], d["version"]) == (FULL, "47.6.3")
    assert store.jobs()[0]["snapshot"] == before
    store.db.close()
    store = Store(tmp_path)
    discover(store, APPS[:1])
    assert store.devices()[0]["package"] == FULL  # no silent fallback after uninstall
    assert store.devices()[0]["version"] == ""
    assert store.jobs()[0]["snapshot"] == before
    store.select_tiktok_app("phone", "")
    assert store.devices()[0]["package"] == LITE
    with pytest.raises(ValueError):
        store.select_tiktok_app("phone", "not.installed")
    store.db.close()


def test_new_submission_freezes_choice_before_background_import_and_keeps_route(
    app, tmp_path
):
    s = DesktopService(prepare_paths(tmp_path), prepare=False)
    s.timer.stop()
    discover(s.store)
    s.device_ports = {"phone": 5038}
    s.store.select_tiktok_app("phone", FULL)
    pending = []
    s.background = lambda fn, done, failed=None: pending.append((fn, done))
    recipe = dict(
        maxVideos=17,
        minWatchTime=2,
        maxWatchTime=9,
        browseProfile="natural",
        runDurationMinutes=3,
        likeProbability=12,
        maxLikesPerSession=4,
        commentProbability=5,
        maxCommentsPerSession=1,
        commentTexts=["Xin chào 한글"],
        followProbability=3,
        maxFollowsPerSession=1,
        pauseDurationMin=6,
        pauseDurationMax=11,
    )
    specs = [
        dict(serial="phone", kind="browse", payload=recipe, run_at=time.time() + 3600)
    ]
    untouched = deepcopy(specs)
    s.submit(specs)
    s.store.select_tiktok_app("phone", LITE)
    fn, done = pending.pop()
    done(fn())
    job = s.store.jobs()[0]
    payload = json.loads(job["snapshot"])
    assert payload == build_browse("phone", recipe) | {"packageName": FULL}
    assert job["state"] == "scheduled"
    assert specs == untouched
    assert isinstance(s.adb_for("phone"), AdbEndpoint)
    assert s.adb_for("phone").port == 5038
    assert s.store.devices()[0]["package"] == LITE
    s.store.db.close()


def test_missing_explicit_choice_blocks_new_job_without_changing_saved_job(
    app, tmp_path
):
    s = DesktopService(prepare_paths(tmp_path), prepare=False)
    s.timer.stop()
    discover(s.store)
    s.store.select_tiktok_app("phone", FULL)
    discover(s.store, APPS[:1])
    with pytest.raises(ValueError, match="không còn"):
        s.submit([dict(serial="phone", kind="browse", payload={})])
    assert s.store.jobs() == []
    assert not s.submitting
    s.store.db.close()


@pytest.mark.parametrize("package", [LITE, FULL])
def test_media_import_preserves_package_caption_and_hashtags(tmp_path, package):
    root = prepare_paths(tmp_path)
    media = tmp_path / "source.png"
    media.write_bytes(b"fixture media")
    ready, _ = import_specs(
        root,
        [
            dict(
                serial="phone",
                kind="publish",
                payload=dict(
                    localPath=str(media),
                    caption="Xin chào 한글",
                    hashtags=["#one", "#two"],
                    packageName=package,
                ),
            )
        ],
    )
    p = ready[0]["payload"]
    assert (p["packageName"], p["caption"], p["hashtags"]) == (
        package,
        "Xin chào 한글",
        ["#one", "#two"],
    )


def test_device_dialog_no_longer_changes_app_and_preserves_previous_choice(
    app, tmp_path
):
    from PySide6.QtWidgets import QComboBox, QDialogButtonBox
    from customer_desktop.ui import MainWindow

    s = DesktopService(prepare_paths(tmp_path), prepare=False)
    s.timer.stop()
    discover(s.store)
    window = MainWindow(s)
    window.selected_devices = lambda: s.store.devices()
    dialogs = []
    window.show_dialog = dialogs.append
    window.edit_device()
    dialog = dialogs.pop()
    assert dialog.findChild(QComboBox) is None
    dialog.findChild(QDialogButtonBox).accepted.emit()
    assert s.store.devices()[0]["selected_package"] == ""
    dialog.deleteLater()
    window.deleteLater()
    app.processEvents()
    s.store.db.close()
