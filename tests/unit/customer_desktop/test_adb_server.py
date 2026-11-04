import os

import pytest

from customer_desktop.adb_server import configure_adb_server, server_port
from customer_desktop.paths import prepare_paths
from customer_desktop.runner import environment
from customer_desktop.services import DesktopService
from customer_desktop.ui import MainWindow


@pytest.mark.parametrize("value", [0, 65536, -1, "abc", "5038.5", 5038.5, True, None])
def test_invalid_port_rejected_without_changing_endpoint(monkeypatch, value):
    monkeypatch.setenv("ANDROID_ADB_SERVER_PORT", "5037")
    with pytest.raises(ValueError):
        configure_adb_server(value)
    assert os.environ["ANDROID_ADB_SERVER_PORT"] == "5037"


def test_selected_endpoint_reaches_cli_and_engine_adbutils(monkeypatch, tmp_path):
    for key in ("ANDROID_ADB_SERVER_HOST", "ANDROID_ADB_SERVER_PORT", "ADB_SERVER_SOCKET"):
        monkeypatch.setenv(key, "old-endpoint")
    configure_adb_server("5038")
    env = environment(tmp_path, "adb")
    assert env.value("ANDROID_ADB_SERVER_HOST") == "127.0.0.1"
    assert env.value("ANDROID_ADB_SERVER_PORT") == "5038"
    assert env.value("ADB_SERVER_SOCKET") == "tcp:127.0.0.1:5038"
    # This constructs a client without connecting to a real server.
    from adbutils import AdbClient

    client = AdbClient()
    assert client.host == "127.0.0.1"
    assert client.port == 5038
    assert server_port() == 5037


def test_settings_persist_port_for_restart_without_switching_live_endpoint(
    app, tmp_path, monkeypatch
):
    monkeypatch.setenv("ANDROID_ADB_SERVER_PORT", "5037")
    service = DesktopService(prepare_paths(tmp_path), prepare=False)
    service.timer.stop()
    service.refresh_devices = lambda: None
    window = MainWindow(service)
    window.refresh_timer.stop()
    try:
        assert window.adb_port.value() == 5037
        window.adb_port.setValue(5038)
        window.save_settings()
        assert service.store.setting("adb_port") == 5038
        assert "mở lại" in window.banner.text()
        assert os.environ["ANDROID_ADB_SERVER_PORT"] == "5037"
        # The saved value is available to a new startup and Settings view.
        import sqlite3
        import json

        with sqlite3.connect(tmp_path / "app.db") as connection:
            assert json.loads(connection.execute(
                "SELECT value FROM settings WHERE key='adb_port'"
            ).fetchone()[0]) == 5038
    finally:
        window.allow_close = True
        window.close()
        service.store.close()

