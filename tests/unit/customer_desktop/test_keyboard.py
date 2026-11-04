import json
import pytest
from customer_desktop.keyboard import capture_keyboard, restore_keyboard


def test_compatible_existing_keyboard_and_restore_after_force_stop(
    tmp_path, monkeypatch
):
    state = {"current": "gboard/.Ime"}
    calls = []

    def adb(adb, args):
        calls.append(args)
        if args[3:] == ["ime", "list", "-s", "-a"]:
            return "gboard/.Ime\r\ncom.android.adbkeyboard/.AdbIME"
        if args[3:] == ["settings", "get", "secure", "default_input_method"]:
            return state["current"]
        if args[3:5] == ["ime", "set"]:
            state["current"] = args[5]
            return "selected"
        raise AssertionError(args)

    monkeypatch.setattr("customer_desktop.keyboard.adb_run", adb)
    path = tmp_path / "keyboard.json"
    assert capture_keyboard("adb", "s", path) == "com.android.adbkeyboard/.AdbIME"
    state["current"] = "com.android.adbkeyboard/.AdbIME"
    assert restore_keyboard("adb", "s", tmp_path)
    assert state["current"] == "gboard/.Ime"
    assert (tmp_path / "keyboard-restored.json").exists()


def test_restore_never_uses_untrusted_ime_command(tmp_path, monkeypatch):
    (tmp_path / "keyboard.json").write_text(
        json.dumps({"serial": "s", "original": "bad; rm -rf"})
    )
    monkeypatch.setattr(
        "customer_desktop.keyboard.adb_run",
        lambda *args: pytest.fail("should not execute"),
    )
    with pytest.raises(ValueError):
        restore_keyboard("adb", "s", tmp_path)
