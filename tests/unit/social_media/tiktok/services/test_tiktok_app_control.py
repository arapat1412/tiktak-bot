import subprocess

from taktik.core.social_media.tiktok.services.runtime.app_control import (
    TIKTOK_SPLASH_ACTIVITY,
    force_stop_app_package,
    launch_app_non_blocking,
    restart_tiktok_package,
)


def completed() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def test_launch_app_non_blocking_uses_explicit_activity_without_monkey():
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return completed()

    assert launch_app_non_blocking("device-1", "com.tiktok", run=fake_run)

    assert calls[0][0] == [
        "adb",
        "-s",
        "device-1",
        "shell",
        "am",
        "start",
        "-n",
        f"com.tiktok/{TIKTOK_SPLASH_ACTIVITY}",
    ]
    assert calls[0][1]["timeout"] == 5


def test_launch_app_non_blocking_falls_back_to_resolved_launcher_when_activity_fails():
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            raise TimeoutError("am timeout")
        return completed()

    assert launch_app_non_blocking("device-1", "com.tiktok", run=fake_run)

    assert calls[1] == [
        "adb",
        "-s",
        "device-1",
        "shell",
        "am",
        "start",
        "-a",
        "android.intent.action.MAIN",
        "-c",
        "android.intent.category.LAUNCHER",
        "-p",
        "com.tiktok",
    ]


def test_launch_app_non_blocking_returns_false_when_both_launchers_fail():
    messages = []

    def fake_run(_command, **_kwargs):
        raise OSError("adb unavailable")

    assert not launch_app_non_blocking(
        "device-1",
        "com.tiktok",
        run=fake_run,
        log=lambda level, message: messages.append((level, message)),
    )
    assert messages == [("debug", "[launch] non-fatal launch error: adb unavailable")]


def test_force_stop_app_package_uses_am_force_stop():
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return completed()

    assert force_stop_app_package("device-1", "com.tiktok", run=fake_run)

    assert calls[0][0] == [
        "adb",
        "-s",
        "device-1",
        "shell",
        "am",
        "force-stop",
        "com.tiktok",
    ]
    assert calls[0][1]["timeout"] == 10


class FakeDevice:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.calls = []

    def app_start(self, package_name, activity, stop=False):
        self.calls.append((package_name, activity, stop))
        if self.should_fail:
            raise RuntimeError("app_start failed")


def test_restart_tiktok_package_uses_uiautomator_start_first():
    device = FakeDevice()

    assert restart_tiktok_package(device, "device-1", "com.tiktok")

    assert device.calls == [("com.tiktok", TIKTOK_SPLASH_ACTIVITY, True)]


def test_restart_tiktok_package_falls_back_to_adb_launch(monkeypatch):
    device = FakeDevice(should_fail=True)
    calls = []
    messages = []

    def fake_stop(device_id, package_name, **kwargs):
        calls.append(("stop", device_id, package_name, kwargs))
        return True

    def fake_launch(device_id, package_name, **kwargs):
        calls.append(("launch", device_id, package_name, kwargs))
        return True

    monkeypatch.setattr(
        "taktik.core.social_media.tiktok.services.runtime.app_control.force_stop_app_package",
        fake_stop,
    )
    monkeypatch.setattr(
        "taktik.core.social_media.tiktok.services.runtime.app_control.launch_app_non_blocking",
        fake_launch,
    )

    assert restart_tiktok_package(
        device,
        "device-1",
        "com.tiktok",
        sleep=lambda _seconds: None,
        log=lambda level, message: messages.append((level, message)),
    )

    assert calls[0][0:3] == ("stop", "device-1", "com.tiktok")
    assert calls[1][0:3] == ("launch", "device-1", "com.tiktok")
    assert messages == [
        ("debug", "[launch] app_start failed (app_start failed), falling back to ADB am start")
    ]


def test_launch_activity_error_uses_fallback_and_never_reports_failed_launch_as_success():
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "Error: Activity not found")

    assert not launch_app_non_blocking("phone", "com.tiktok", run=run)
    assert len(calls) == 2
    assert all("monkey" not in call for call in calls)


def test_am_error_text_with_zero_exit_is_still_failure():
    def run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, "Error type 3", "")

    assert not launch_app_non_blocking("phone", "com.tiktok", run=run)
