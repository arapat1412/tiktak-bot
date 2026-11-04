import os
import sys
from PySide6.QtCore import QLockFile, QLocale
from PySide6.QtWidgets import QApplication, QMessageBox
from customer_desktop.paths import prepare_paths
from customer_desktop.services import DesktopService
from customer_desktop.ui import MainWindow, apply_style


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("TikTokKorean")
    app.setOrganizationName("TAKTIK Customer")
    QLocale.setDefault(QLocale("vi_VN"))
    apply_style(app)
    if "--smoke-report" in sys.argv:
        # Build verification: load the real Qt runtime/plugins and timezone data
        # without opening a customer database or touching a connected phone.
        import json
        from pathlib import Path
        from datetime import datetime
        import tempfile
        from PySide6.QtGui import QIcon
        from customer_desktop.ui import TZ, BrowseDialog
        from customer_desktop import ui as ui_module

        target = Path(sys.argv[sys.argv.index("--smoke-report") + 1])
        icon = QIcon(
            str(Path(ui_module.__file__).parent / "resources" / "check.svg")
        ).pixmap(16, 16)
        # Exercise the actual frozen form, using a temporary app database and no
        # MainWindow/discovery timer. This must never open a worker or touch ADB.
        with tempfile.TemporaryDirectory(prefix="taktik-form-smoke-") as temporary:
            service = DesktopService(prepare_paths(temporary), prepare=False)
            service.timer.stop()
            dialog = BrowseDialog(
                service, [dict(serial="fixture", name="Máy thử")], None
            )
            empty = dialog.values()
            dialog.comments.setPlainText("Nội dung thử 한글")
            filled = dialog.values()
            browse_ready = (
                empty.get("browseProfile") == filled.get("browseProfile") == "natural"
                and empty.get("likeProbability") == 25
                and empty.get("followProbability") == 5
                and empty.get("commentProbability") == 0
                and filled.get("commentProbability") == 8
                and filled.get("commentTexts") == ["Nội dung thử 한글"]
            )
            dialog.close()
            service.store.close()
        target.write_text(
            json.dumps(
                {
                    "qt_ready": True,
                    "timezone": TZ.key,
                    "utc_offset_seconds": datetime.now(TZ).utcoffset().total_seconds(),
                    "icon_ready": not icon.isNull(),
                    "frozen": bool(getattr(sys, "frozen", False)),
                    "browse_ready": browse_ready,
                }
            ),
            encoding="utf-8",
        )
        return 0 if not icon.isNull() and browse_ready else 2
    from customer_desktop import console

    # LiveLogPanel reads the shared history directly; no external console sink.
    app.aboutToQuit.connect(lambda: console.emit("Đang đóng ứng dụng…"))
    console.emit(
        "TAKTIK đang mở. Log trực tiếp; nhật ký chi tiết được lưu theo tác vụ."
    )
    try:
        root = prepare_paths()
        console.emit(f"Thư mục dữ liệu: {root}")
    except OSError as exc:
        console.emit(str(exc), level="ERROR")
        QMessageBox.critical(
            None,
            "Không mở được thư mục dữ liệu",
            "Kiểm tra dung lượng và quyền ghi thư mục dữ liệu.\n" + str(exc),
        )
        return 1
    lock = QLockFile(str(root / "desktop.lock"))
    # QLockFile checks process identity/name; never steal a live lock on a timer.
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        console.emit("Ứng dụng đã chạy; hãy dùng cửa sổ đang mở.", level="WARN")
        QMessageBox.information(
            None,
            "TAKTIK đang mở",
            "Ứng dụng đang chạy với thư mục dữ liệu này. Hãy dùng cửa sổ đang mở.",
        )
        return 1
    try:
        from customer_desktop.licensing import LicenseManager
        from customer_desktop.license_dialog import LicenseDialog

        manager = LicenseManager(root)
        if not manager.check().valid:
            if (
                LicenseDialog(manager).exec() != LicenseDialog.Accepted
                or not manager.check().valid
            ):
                console.emit(
                    "Chưa kích hoạt bản quyền; ứng dụng đã đóng.", level="WARN"
                )
                return 0
        service = DesktopService(root, license_manager=manager)
        from customer_desktop.adb_server import configure_adb_server

        configure_adb_server(service.store.setting("adb_port", 5037))
        service.notice.connect(lambda text: console.emit(text, level="WARN"))
        window = MainWindow(service)
        window.show()
        result = app.exec()
        service.store.close()
        return result
    except Exception as exc:
        console.emit(str(exc), level="ERROR")
        QMessageBox.critical(
            None,
            "Không mở được TAKTIK",
            "Không mở được dữ liệu ứng dụng. Dữ liệu được giữ nguyên.\n" + str(exc),
        )
        return 1
    finally:
        lock.unlock()
        console.emit("Ứng dụng đã đóng.")
        console.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
