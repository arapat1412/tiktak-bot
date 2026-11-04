import json
from types import SimpleNamespace

import pytest

from customer_desktop import orientation


@pytest.mark.parametrize("mode,rotation,expected", [
    ("LOCKED", "0", True), ("FREE", "0", False), ("LOCKED", "1", False),
])
def test_legacy_android_lock_verified_on_default_display(monkeypatch, mode, rotation, expected):
    calls = []

    def adb(path, args):
        assert args[:3] == ["-s", "legacy-phone", "shell"]
        calls.append(args[3:])
        if args[3:] == ["wm", "user-rotation", "lock", "0"]:
            raise RuntimeError("Unknown command: user-rotation")
        if args[3:] == ["dumpsys", "window"]:
            return (
                "  Display: mDisplayId=0 stacks=6\n"
                f"    mUserRotationMode=USER_ROTATION_{mode} mUserRotation=ROTATION_{rotation}\n"
                "  Display: mDisplayId=1\n"
                "    mUserRotationMode=USER_ROTATION_LOCKED mUserRotation=ROTATION_0\n"
            )
        if args[3:6] == ["settings", "get", "system"]:
            return "0"
        return ""

    monkeypatch.setattr(orientation, "adb_run", adb)
    if expected:
        assert orientation.lock_portrait("adb", "legacy-phone")
    else:
        with pytest.raises(RuntimeError, match="chưa khóa"):
            orientation.lock_portrait("adb", "legacy-phone")
    assert calls[:2] == [["wm", "user-rotation", "lock", "0"],
                         ["wm", "set-user-rotation", "lock", "0"]]
    assert ["wm", "user-rotation"] not in calls


@pytest.mark.parametrize("message", ["device offline", "Permission denied", "ADB thất bại"])
def test_real_adb_failure_never_attempts_legacy_command(monkeypatch, message):
    calls = []

    def adb(path, args):
        calls.append(args)
        raise RuntimeError(message)

    monkeypatch.setattr(orientation, "adb_run", adb)
    with pytest.raises(RuntimeError, match=message):
        orientation.lock_portrait("adb", "phone")
    assert len(calls) == 1


def test_legacy_setter_refusal_still_aborts(monkeypatch):
    def adb(path, args):
        if "set-user-rotation" in args:
            raise RuntimeError("Permission denied")
        raise RuntimeError("Unknown command: user-rotation")

    monkeypatch.setattr(orientation, "adb_run", adb)
    with pytest.raises(RuntimeError, match="Permission denied"):
        orientation.lock_portrait("adb", "phone")


@pytest.mark.parametrize("policy,expected", [
    ("mUserRotationMode=1 mUserRotation=0", True),
    ("mUserRotationMode=USER_ROTATION_LOCKED mUserRotation=ROTATION_0", True),
    ("mUserRotationMode=0 mUserRotation=0", False),
    ("mUserRotationMode=1 mUserRotation=1", False),
    ("mUserRotationMode=1 mUserRotation=10", False),
    ("", False),
])
def test_pre_wm_android_settings_fallback_verifies_policy(monkeypatch, policy, expected):
    calls = []

    def adb(path, args):
        assert path == "customer-adb"
        assert args[:3] == ["-s", "note8", "shell"]
        command = args[3:]
        calls.append(command)
        if command[0] == "wm":
            raise RuntimeError("Unknown command: " + command[1])
        if command[:3] == ["settings", "get", "system"]:
            return "0"
        if command == ["dumpsys", "window", "policy"]:
            return policy
        return ""

    monkeypatch.setattr(orientation, "adb_run", adb)
    monkeypatch.setattr(orientation.time, "sleep", lambda _: None)
    if expected:
        assert orientation.lock_portrait("customer-adb", "note8")
    else:
        with pytest.raises(RuntimeError, match="chưa khóa"):
            orientation.lock_portrait("customer-adb", "note8")
    assert ["settings", "put", "system", "accelerometer_rotation", "0"] in calls
    assert ["settings", "put", "system", "user_rotation", "0"] in calls
    assert calls.count(["dumpsys", "window", "policy"]) == (1 if expected else 5)


def test_pre_wm_android_waits_for_applied_policy(monkeypatch):
    policies = iter(["mUserRotationMode=0 mUserRotation=0", "mUserRotationMode=1 mUserRotation=0"])
    waits = []

    def adb(path, args):
        if args[3] == "wm":
            raise RuntimeError("Unknown command: " + args[4])
        if args[3:] == ["dumpsys", "window", "policy"]:
            return next(policies)
        return "0"

    monkeypatch.setattr(orientation, "adb_run", adb)
    monkeypatch.setattr(orientation.time, "sleep", waits.append)
    assert orientation.lock_portrait("adb", "note8")
    assert waits == [0.2]


@pytest.mark.parametrize("failed_command", ["put", "get", "dumpsys"])
def test_pre_wm_android_propagates_settings_and_policy_failure(monkeypatch, failed_command):
    def adb(path, args):
        if args[3] == "wm":
            raise RuntimeError("Unknown command: " + args[4])
        if failed_command in args:
            raise RuntimeError("Permission denied")
        return "0"

    monkeypatch.setattr(orientation, "adb_run", adb)
    with pytest.raises(RuntimeError, match="Permission denied"):
        orientation.lock_portrait("adb", "note8")


def test_portrait_lock_addresses_only_selected_serial_and_reads_back(monkeypatch):
    calls = []

    def adb(adb_path, args):
        assert adb_path == "adb-custom"
        assert args[:3] == ["-s", "phone-b", "shell"]
        calls.append(args)
        if args[-1] in ("accelerometer_rotation", "user_rotation"):
            return "0"
        if args[-1] == "user-rotation":
            return "lock 0"
        return ""

    monkeypatch.setattr(orientation, "adb_run", adb)
    assert orientation.lock_portrait("adb-custom", "phone-b")
    assert len(calls) == 6
    assert calls[0][-4:] == ["wm", "user-rotation", "lock", "0"]


@pytest.mark.parametrize("serial", [None, "", " "])
def test_missing_serial_never_falls_through_to_adb_default_phone(monkeypatch, serial):
    monkeypatch.setattr(orientation, "adb_run", lambda *a: pytest.fail("ADB called"))
    with pytest.raises(ValueError):
        orientation.lock_portrait("adb", serial)


@pytest.mark.parametrize(
    "sensor,rotation,window",
    [("1", "0", "lock 0"), ("0", "1", "lock 1"), ("0", "0", "free")],
)
def test_android_refusal_is_not_reported_as_locked(
    monkeypatch, sensor, rotation, window
):
    def adb(_path, args):
        if args[-1] == "accelerometer_rotation":
            return sensor
        if args[-1] == "user_rotation":
            return rotation
        return window

    monkeypatch.setattr(orientation, "adb_run", adb)
    with pytest.raises(RuntimeError):
        orientation.lock_portrait("adb", "phone")


@pytest.mark.parametrize(
    "valid,lock_ok,expected",
    [
        (False, True, ["license"]),
        (True, False, ["license", "portrait"]),
        (True, True, ["license", "portrait", "workflow"]),
    ],
)
def test_engine_locks_after_license_and_before_workflow(
    monkeypatch, tmp_path, valid, lock_ok, expected
):
    from customer_desktop import engine_worker, licensing, paths
    import bridges.launcher

    config = tmp_path / "run.json"
    config.write_text(json.dumps({"deviceId": "selected-phone"}))
    order = []

    def check():
        order.append("license")
        return SimpleNamespace(valid=valid, message="invalid")

    monkeypatch.setattr(
        licensing, "LicenseManager", lambda root: SimpleNamespace(check=check)
    )
    monkeypatch.setattr(paths, "data_root", lambda: tmp_path)
    monkeypatch.setattr(
        engine_worker.sys, "argv", ["engine", "tiktok_bridge", str(config)]
    )
    monkeypatch.setattr(engine_worker.threading.Thread, "start", lambda self: None)
    for key in (
        "TAKTIK_CUSTOMER_GATE",
        "TAKTIK_CUSTOMER_STOP",
        "TAKTIK_CUSTOMER_IME_STATE",
    ):
        monkeypatch.delenv(key, raising=False)

    def lock(adb, serial):
        order.append("portrait")
        assert serial == "selected-phone"
        if not lock_ok:
            raise OSError("device refused")

    monkeypatch.setattr(orientation, "lock_portrait", lock)
    monkeypatch.setattr(bridges.launcher, "main", lambda: order.append("workflow"))
    assert engine_worker.main() == (3 if not valid else (1 if not lock_ok else 0))
    assert order == expected
