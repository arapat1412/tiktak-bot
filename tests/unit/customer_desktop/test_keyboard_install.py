from pathlib import Path
from unittest.mock import Mock
import subprocess

import pytest
from PySide6.QtCore import Qt

from customer_desktop import keyboard
from customer_desktop.paths import prepare_paths
from customer_desktop.services import DesktopService
from customer_desktop.ui import MainWindow

IME = keyboard.COMPATIBLE[1]


@pytest.mark.parametrize("existing", [None, *keyboard.COMPATIBLE])
def test_install_or_reuse_and_enable_without_changing_default(
    tmp_path, monkeypatch, existing
):
    calls = []
    state = {"ime": existing, "enabled": False}
    apk = tmp_path / "ADBKeyboard.apk"
    apk.write_bytes(b"fixture")

    def adb(exe, args, timeout=8):
        assert exe == "adb-fixture" and args[:2] == ["-s", "phone-only"]
        calls.append(args)
        command = args[2:]
        if command == ["get-state"]:
            return "device"
        if command == ["shell", "ime", "list", "-s", "-a"]:
            return "stock/.Ime\r\n" + (state["ime"] or "")
        if command[:1] == ["install"]:
            assert not existing and command == ["install", "-r", str(apk)]
            assert timeout == 120
            state["ime"] = IME
            return "Performing Streamed Install\nSuccess"
        if command == ["shell", "ime", "enable", state["ime"]]:
            state["enabled"] = True
            return "enabled"
        if command == ["shell", "ime", "list", "-s"]:
            return state["ime"] if state["enabled"] else "stock/.Ime"
        pytest.fail(f"Unexpected command {args}")

    monkeypatch.setattr(keyboard, "adb_run", adb)
    result = keyboard.install_keyboard("adb-fixture", "phone-only", apk)
    assert result == {"ime": existing or IME, "already_installed": bool(existing)}
    assert sum("install" in args for args in calls) == (0 if existing else 1)
    assert not any("set" in args for args in calls)


@pytest.mark.parametrize(
    "failure", ["missing", "rejected", "timeout", "no_ime", "not_enabled", "offline"]
)
def test_install_never_reports_success_without_android_readback(
    tmp_path, monkeypatch, failure
):
    apk = tmp_path / "ADBKeyboard.apk"
    if failure != "missing":
        apk.write_bytes(b"fixture")
    installed = []

    def adb(exe, args, timeout=8):
        command = args[2:]
        if command == ["get-state"]:
            return "offline" if failure == "offline" else "device"
        if command == ["shell", "ime", "list", "-s", "-a"]:
            return "\n".join(installed)
        if command[0] == "install":
            if failure == "timeout":
                raise subprocess.TimeoutExpired(exe, timeout)
            if failure == "rejected":
                return "Failure [INSTALL_FAILED_USER_RESTRICTED]"
            if failure != "no_ime":
                installed.append(IME)
            return "Success"
        if command[:3] == ["shell", "ime", "enable"]:
            return "enabled"
        if command == ["shell", "ime", "list", "-s"]:
            return "stock/.Ime"
        pytest.fail(str(args))

    monkeypatch.setattr(keyboard, "adb_run", adb)
    with pytest.raises((ValueError, RuntimeError, subprocess.TimeoutExpired)):
        keyboard.install_keyboard("adb", "phone-only", apk)


def service(tmp_path):
    s = DesktopService(prepare_paths(tmp_path), prepare=False)
    s.timer.stop()
    s.store.set_setting("onboarded", True)
    s.refresh_devices = lambda: None
    s.store.discover([dict(serial="phone", connection="online", model="Fixture")])
    return s


@pytest.mark.parametrize("failed", [False, True])
def test_background_install_reserves_phone_and_releases_on_both_results(
    app, tmp_path, monkeypatch, failed
):
    s = service(tmp_path)
    pending, messages = [], []
    s.notice.connect(messages.append)
    batches = []
    s.keyboard_finished.connect(batches.append)
    monkeypatch.setattr(s, "background", lambda *args, **kw: pending.append(args))
    s.install_device_keyboard("phone")
    assert s.keyboard_installing == {"phone"}
    assert not s.manual_ready("phone")
    assert "bàn phím" in s.admission_reason
    s.store.claim = Mock(side_effect=AssertionError("must not claim during install"))
    s._admit_jobs()
    with pytest.raises(ValueError):
        s.install_device_keyboard("phone")
    if failed:
        pending[0][2]("USB disconnected")
        assert batches[-1][0]["status"] == "failed"
    else:
        pending[0][1]({"already_installed": False, "ime": IME})
        assert batches[-1][0]["status"] == "installed"
    assert not s.keyboard_installing and s.manual_ready("phone")
    s.store.close()


def test_installer_rejects_disconnected_or_active_phone(app, tmp_path, monkeypatch):
    s = service(tmp_path)
    monkeypatch.setattr(
        s, "background", Mock(side_effect=AssertionError("must not start"))
    )
    with pytest.raises(ValueError):
        s.install_device_keyboard("unknown")
    monkeypatch.setattr(s, "manual_ready", lambda serial: False)
    with pytest.raises(ValueError):
        s.install_device_keyboard("phone")
    assert not s.keyboard_installing
    s.store.close()


def test_button_accepts_one_online_idle_phone_even_without_tiktok(
    app, tmp_path, monkeypatch
):
    s = service(tmp_path)
    w = MainWindow(s)
    w.refresh_timer.stop()
    assert not w.keyboard_button.isEnabled()
    w.device_table.item(0, 0).setCheckState(Qt.Checked)
    assert w.keyboard_button.isEnabled()
    assert not w.browse_button.isEnabled()
    install = Mock()
    monkeypatch.setattr(s, "install_device_keyboards", install)
    w.keyboard_button.click()
    install.assert_called_once_with(["phone"])
    s.keyboard_installing.add("phone")
    w.update_selection()
    assert not w.keyboard_button.isEnabled()
    assert w.keyboard_button.text() == "Đang cài bàn phím…"
    s.keyboard_installing.clear()
    w.update_selection()
    assert w.keyboard_button.isEnabled()
    w.allow_close = True
    w.close()
    s.store.close()


def test_bundled_apk_matches_release_digest_and_includes_source():
    import hashlib
    import json
    import zipfile

    folder = Path(keyboard.__file__).parent / "resources" / "adb-keyboard"
    metadata = json.loads((folder / "provenance.json").read_text())
    assert (
        hashlib.sha256((folder / "ADBKeyboard.apk").read_bytes()).hexdigest()
        == metadata["apk_sha256"]
    )
    assert (
        hashlib.sha256((folder / "source.zip").read_bytes()).hexdigest()
        == metadata["source_sha256"]
    )
    assert (folder / "LICENSE").is_file()
    with zipfile.ZipFile(folder / "source.zip") as archive:
        assert archive.testzip() is None


def test_batch_sequential_deduplicated_skips_busy_offline_and_continues_after_failure(
    app, tmp_path, monkeypatch
):
    s = service(tmp_path)
    s.store.discover(
        [
            dict(
                serial=serial,
                connection="offline" if serial == "offline" else "online",
                model="Fixture",
            )
            for serial in ("a", "b", "c", "busy", "offline")
        ]
    )
    original_ready = s.manual_ready
    monkeypatch.setattr(
        s, "manual_ready", lambda serial: serial != "busy" and original_ready(serial)
    )
    pending, batches, calls = [], [], []
    s.keyboard_finished.connect(batches.append)
    monkeypatch.setattr(s, "background", lambda *args, **kw: pending.append(args))

    def install(adb, serial):
        calls.append(serial)
        if serial == "b":
            raise RuntimeError("INSTALL_FAILED_USER_RESTRICTED")
        return {"already_installed": serial == "a", "ime": IME}

    monkeypatch.setattr("customer_desktop.services.install_keyboard", install)
    selected = ["a", "busy", "offline", "b", "a", "c"]
    s.install_device_keyboards(selected)
    assert s.keyboard_installing == {"a", "b", "c"}
    assert len(pending) == 1  # only one worker submitted at a time
    with pytest.raises(ValueError):
        s.install_device_keyboards(["phone"])
    while pending:
        work, done, fail = pending.pop(0)
        try:
            value = work()
        except RuntimeError as exc:
            fail(str(exc))
        else:
            done(value)
        assert len(pending) <= 1
    assert calls == ["a", "b", "c"]
    assert not s.keyboard_installing
    assert [r["serial"] for r in batches[0]] == ["a", "busy", "offline", "b", "c"]
    assert [r["status"] for r in batches[0]] == [
        "existing",
        "skipped",
        "skipped",
        "failed",
        "installed",
    ]
    assert "INSTALL_FAILED_USER_RESTRICTED" in batches[0][3]["message"]
    s.store.close()


def test_batch_shutdown_skips_remaining_and_releases_reservation(
    app, tmp_path, monkeypatch
):
    s = service(tmp_path)
    s.store.discover(
        [
            dict(serial="phone", connection="online", model="Fixture"),
            dict(serial="other", connection="online", model="Fixture"),
        ]
    )
    pending, batches = [], []
    s.keyboard_finished.connect(batches.append)
    monkeypatch.setattr(s, "background", lambda *args, **kw: pending.append(args))
    s.install_device_keyboards(["phone", "other"])
    s.closing = True
    pending[0][1]({"already_installed": True, "ime": IME})
    assert not s.keyboard_installing
    assert len(pending) == 1
    assert [r["status"] for r in batches[0]] == ["existing", "skipped"]
    s.store.close()


def test_all_selected_offline_reports_skipped_without_worker(
    app, tmp_path, monkeypatch
):
    s = service(tmp_path)
    s.store.discover([dict(serial="phone", connection="offline", model="Fixture")])
    batches = []
    s.keyboard_finished.connect(batches.append)
    monkeypatch.setattr(
        s, "background", Mock(side_effect=AssertionError("no ADB worker permitted"))
    )
    s.install_device_keyboards(["phone", "unknown"])
    assert len(batches[0]) == 2 and all(r["status"] == "skipped" for r in batches[0])
    assert not s.keyboard_installing
    with pytest.raises(ValueError):
        s.install_device_keyboards([])
    s.store.close()


def test_select_all_submits_every_checked_device_and_displays_per_device_results(
    app, tmp_path, monkeypatch
):
    s = service(tmp_path)
    s.store.discover(
        [
            dict(serial="phone", connection="online", model="Fixture"),
            dict(serial="other", connection="offline", model="Fixture"),
        ]
    )
    w = MainWindow(s)
    w.refresh_timer.stop()
    w.select_all_visible(True)
    assert w.keyboard_button.isEnabled()
    assert "2 máy" in w.keyboard_button.text()
    selected = w.selected_serials()
    install = Mock()
    monkeypatch.setattr(s, "install_device_keyboards", install)
    w.keyboard_button.click()
    install.assert_called_once_with(selected)
    s.keyboard_finished.emit(
        [
            dict(serial="phone", status="existing", message="Enabled"),
            dict(serial="other", status="skipped", message="Offline"),
        ]
    )
    assert len(w.dialogs) == 1
    from PySide6.QtWidgets import QTableWidget

    rows = w.dialogs[0].findChild(QTableWidget)
    assert rows.rowCount() == 2
    assert rows.item(0, 1).text() == "Đã có sẵn"
    assert rows.item(1, 1).text() == "Bỏ qua"
    w.dialogs[0].accept()
    w.allow_close = True
    w.close()
    s.store.close()
