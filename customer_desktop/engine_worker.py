"""Isolated engine host. Keeps the public launcher, watchdog and IPC contract intact.

Windows cancellation is an attempt-specific file, independent of console signals/stdin.
The halt latch is cooperative; the deadline is a backstop for blocking device calls.
"""

import json
import os
from pathlib import Path
import sys
import threading
import time


def monitor_stop(path, grace=10):
    first = None
    while True:
        if Path(path).exists():
            from taktik.core.shared.diagnostics import run_halt

            run_halt.demander_arret("customer_stop", "Operator requested stop")
            from bridges.common.signal_handler import _workflow

            if _workflow is not None:
                try:
                    _workflow.stop()
                except Exception:
                    pass
            if first is None:
                first = time.monotonic()
                print(json.dumps({"type": "status", "status": "stopping"}), flush=True)
            if time.monotonic() - first >= grace:
                # No claim of clean cancellation: the GUI records needs_review.
                os._exit(124)
        time.sleep(0.15)


def prepare_database():
    from taktik.core.database.local.versions.runner import migrate_database

    result = migrate_database(
        os.environ["TAKTIK_DB_PATH"],
        applied_by="customer-desktop",
        backup_dir=str(Path(os.environ["TAKTIK_DB_PATH"]).parent / "backups"),
    )
    print(
        json.dumps(
            {
                "type": "database_ready",
                "success": result.success,
                "message": result.message,
            }
        ),
        flush=True,
    )
    return 0 if result.success else 1


def main():
    # Frozen Windows executables can ignore PYTHONIOENCODING during boot.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if "--prepare-db" in sys.argv:
        return prepare_database()
    from customer_desktop.licensing import LicenseManager
    from customer_desktop.paths import data_root

    try:
        manager = LicenseManager(data_root())
        status = manager.check()
        if "--license-status" in sys.argv:
            print(
                json.dumps(
                    dict(
                        machine_id=manager.machine_id,
                        valid=status.valid,
                        message=status.message,
                        expires_at=status.expires_at,
                    ),
                    ensure_ascii=False,
                ),
                flush=True,
            )
            return 0
        if not status.valid:
            raise ValueError(status.message)
    except Exception as exc:
        print(
            json.dumps(
                dict(
                    type="error", error_code="CUSTOMER_LICENSE_INVALID", error=str(exc)
                ),
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 3
    threading.Thread(target=monitor_license, args=(manager,), daemon=True).start()
    gate = os.environ.get("TAKTIK_CUSTOMER_GATE")
    if gate:
        deadline = time.monotonic() + 15
        while not Path(gate).exists():
            if time.monotonic() >= deadline:
                return 126
            time.sleep(0.05)
    stop = os.environ.get("TAKTIK_CUSTOMER_STOP")
    if stop:
        threading.Thread(target=monitor_stop, args=(stop,), daemon=True).start()
    os.environ["TAKTIK_CUSTOMER_EVENTS"] = "1"
    if len(sys.argv) >= 3 and sys.argv[1] in ("tiktok_bridge", "tiktok_publish_bridge"):
        from customer_desktop.orientation import lock_portrait

        try:
            payload = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
            lock_portrait(
                os.environ.get("ADBUTILS_ADB_PATH", "adb"), payload.get("deviceId")
            )
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "type": "error",
                        "error_code": "CUSTOMER_PORTRAIT_LOCK_FAILED",
                        "error": f"Không khóa được màn hình dọc: {exc}",
                    }
                ),
                flush=True,
            )
            return 1
        print(
            json.dumps(
                {
                    "type": "log",
                    "level": "info",
                    "message": "Đã khóa màn hình dọc, tắt tự động xoay trên điện thoại.",
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    ime_path = os.environ.get("TAKTIK_CUSTOMER_IME_STATE")
    if ime_path and len(sys.argv) >= 3:
        from customer_desktop.keyboard import capture_keyboard

        payload = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
        serial = payload.get("deviceId")
        adb = os.environ.get("ADBUTILS_ADB_PATH", "adb")
        chosen = capture_keyboard(adb, serial, ime_path)
        needs_text = (
            sys.argv[1] == "tiktok_publish_bridge"
            and bool(payload.get("caption") or payload.get("hashtags"))
            or payload.get("commentProbability", 0) > 0
        )
        if needs_text and not chosen:
            print(
                json.dumps(
                    {
                        "type": "error",
                        "error_code": "CUSTOMER_KEYBOARD_MISSING",
                        "error": "Thiếu bàn phím Taktik/ADB tương thích. Vào Điện thoại, chọn máy rồi bấm Cài ADBKeyboard.",
                    }
                ),
                flush=True,
            )
            return 1
        if chosen:
            os.environ["TAKTIK_KEYBOARD_IME"] = chosen
    # Do not import workflows into the GUI. The standard launcher installs crash
    # hooks and the owner watchdog before importing the selected bridge.
    from bridges.launcher import main as launch

    launch()
    return 0


def monitor_license(manager):
    """Expiry is cooperative first; blocking RPCs have a bounded exit fallback."""
    while True:
        time.sleep(2)
        status = manager.check()
        if status.valid:
            continue
        print(
            json.dumps(
                dict(
                    type="error",
                    error_code="CUSTOMER_LICENSE_INVALID",
                    error=status.message,
                ),
                ensure_ascii=False,
            ),
            flush=True,
        )
        from taktik.core.shared.diagnostics import run_halt

        run_halt.demander_arret("license_invalid", status.message)
        try:
            from bridges.common.signal_handler import _workflow

            if _workflow is not None:
                _workflow.stop()
        finally:
            time.sleep(10)
            os._exit(125)


if __name__ == "__main__":
    raise SystemExit(main())
