"""Lock the addressed phone upright before automation computes any tap geometry."""

import re
import time

from customer_desktop.devices import adb_run


def lock_portrait(adb, serial):
    if not isinstance(serial, str) or not serial.strip():
        raise ValueError("Thiếu mã điện thoại để khóa màn hình dọc.")
    prefix = ["-s", serial, "shell"]
    # WindowManager also clears a rotation freeze left by an automation server.
    legacy = False
    settings_only = False
    try:
        adb_run(adb, [*prefix, "wm", "user-rotation", "lock", "0"])
    except RuntimeError as exc:
        if not re.search(r"Unknown command:\s*user-rotation\b", str(exc), re.I):
            raise
        # Samsung Android 10/11 exposes the older setter, with no query form.
        try:
            adb_run(adb, [*prefix, "wm", "set-user-rotation", "lock", "0"])
        except RuntimeError as legacy_exc:
            if not re.search(
                r"Unknown command:\s*set-user-rotation\b", str(legacy_exc), re.I
            ):
                raise
            # Older Android exposes neither wm setter. PhoneWindowManager reads
            # these same system settings to apply the user rotation lock.
            settings_only = True
        legacy = True
    adb_run(adb, [*prefix, "settings", "put", "system", "accelerometer_rotation", "0"])
    adb_run(adb, [*prefix, "settings", "put", "system", "user_rotation", "0"])
    sensor = adb_run(
        adb, [*prefix, "settings", "get", "system", "accelerometer_rotation"]
    )
    rotation = adb_run(adb, [*prefix, "settings", "get", "system", "user_rotation"])
    if settings_only:
        locked = False
        # The settings observer updates WindowManager asynchronously. Confirm its
        # applied policy, not just values written to the settings database.
        for attempt in range(5):
            policy = adb_run(adb, [*prefix, "dumpsys", "window", "policy"])
            locked = bool(re.search(
                r"\bmUserRotationMode=(?:1|USER_ROTATION_LOCKED)\s+"
                r"mUserRotation=(?:0|ROTATION_0)\b", policy,
            ))
            if locked:
                break
            if attempt < 4:
                time.sleep(0.2)
    elif legacy:
        dump = adb_run(adb, [*prefix, "dumpsys", "window"])
        display = re.search(
            r"^\s*Display:\s+mDisplayId=0\b(.*?)(?=^\s*Display:\s+mDisplayId=\d+\b|\Z)",
            dump, re.M | re.S,
        )
        locked = bool(display and re.search(
            r"mUserRotationMode=USER_ROTATION_LOCKED\s+mUserRotation=ROTATION_0\b",
            display.group(1),
        ))
    else:
        locked = adb_run(adb, [*prefix, "wm", "user-rotation"]).strip() == "lock 0"
    if sensor != "0" or rotation != "0" or not locked:
        raise RuntimeError(
            "Điện thoại chưa khóa được màn hình dọc. Kiểm tra kết nối ADB rồi thử lại."
        )
    return True
