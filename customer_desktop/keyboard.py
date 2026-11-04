"""Remember and restore only this attempt's keyboard, including after a hard stop."""

import json
from pathlib import Path
import re
from customer_desktop.devices import adb_run

COMPATIBLE = ("com.alexal1.adbkeyboard/.AdbIME", "com.android.adbkeyboard/.AdbIME")
AUTOMATION = (*COMPATIBLE, "com.github.uiautomator/.AdbKeyboard")


def install_keyboard(adb, serial, apk=None):
    """Install/enable a compatible IME without changing the user's default keyboard."""
    if adb_run(adb, ["-s", serial, "get-state"]) != "device":
        raise ValueError("Điện thoại chưa sẵn sàng. Kiểm tra USB và quyền ADB.")
    installed = adb_run(
        adb, ["-s", serial, "shell", "ime", "list", "-s", "-a"]
    ).splitlines()
    chosen = next((ime for ime in COMPATIBLE if ime in installed), "")
    reused = bool(chosen)
    if not chosen:
        apk = (
            Path(apk)
            if apk
            else Path(__file__).parent
            / "resources"
            / "adb-keyboard"
            / "ADBKeyboard.apk"
        )
        if not apk.is_file():
            raise ValueError(
                "Thiếu ADBKeyboard.apk trong bộ tool. Hãy chép lại đầy đủ thư mục ứng dụng."
            )
        result = adb_run(adb, ["-s", serial, "install", "-r", str(apk)], timeout=120)
        if "Success" not in result.splitlines():
            raise RuntimeError("Không cài được ADBKeyboard: " + result)
        installed = adb_run(
            adb, ["-s", serial, "shell", "ime", "list", "-s", "-a"]
        ).splitlines()
        chosen = next((ime for ime in COMPATIBLE if ime in installed), "")
        if not chosen:
            raise RuntimeError(
                "Android chưa nhận bàn phím sau khi cài. Hãy kiểm tra điện thoại."
            )
    adb_run(adb, ["-s", serial, "shell", "ime", "enable", chosen])
    enabled = adb_run(adb, ["-s", serial, "shell", "ime", "list", "-s"]).splitlines()
    if chosen not in enabled:
        raise RuntimeError(
            "ADBKeyboard chưa được bật. Hãy mở khóa điện thoại và kiểm tra quyền cài đặt."
        )
    return {"ime": chosen, "already_installed": reused}


def capture_keyboard(adb, serial, path):
    installed = adb_run(
        adb, ["-s", serial, "shell", "ime", "list", "-s", "-a"]
    ).splitlines()
    current = adb_run(
        adb,
        ["-s", serial, "shell", "settings", "get", "secure", "default_input_method"],
    )
    original = (
        current
        if current not in AUTOMATION
        else next((i for i in installed if i not in AUTOMATION), "")
    )
    chosen = next((i for i in COMPATIBLE if i in installed), "")
    Path(path).write_text(
        json.dumps(dict(original=original, chosen=chosen, serial=serial)),
        encoding="utf-8",
    )
    return chosen


def restore_keyboard(adb, serial, directory):
    path = Path(directory) / "keyboard.json"
    if not path.exists():
        return True
    state = json.loads(path.read_text(encoding="utf-8"))
    ime = state.get("original", "")
    if state.get("serial") != serial or not re.fullmatch(
        r"[A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+", ime
    ):
        raise ValueError(
            "Không xác định được bàn phím gốc; hãy chọn lại bàn phím trên điện thoại."
        )
    if (
        adb_run(
            adb,
            [
                "-s",
                serial,
                "shell",
                "settings",
                "get",
                "secure",
                "default_input_method",
            ],
        )
        != ime
    ):
        adb_run(adb, ["-s", serial, "shell", "ime", "set", ime])
    if (
        adb_run(
            adb,
            [
                "-s",
                serial,
                "shell",
                "settings",
                "get",
                "secure",
                "default_input_method",
            ],
        )
        != ime
    ):
        raise ValueError(
            "Điện thoại chưa trả về bàn phím gốc; hãy kiểm tra bằng Xiaowei."
        )
    path.with_name("keyboard-restored.json").write_text(
        json.dumps({"restored": True}), encoding="utf-8"
    )
    return True
