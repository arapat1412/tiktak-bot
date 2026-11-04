"""Application selection owned by a task form, resolved against each phone's inventory."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QVBoxLayout, QWidget

LITE = "com.ss.android.ugc.tiktok.lite"


class TikTokAppChoice(QWidget):
    changed = Signal()

    def __init__(self, devices, parent=None):
        super().__init__(parent)
        self.devices = devices
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.mode = QComboBox()
        self.mode.setAccessibleName("Ứng dụng TikTok muốn chạy")
        self.mode.addItem("TikTok Lite", "lite")
        self.mode.addItem("TikTok thường", "standard")
        self.mode.addItem("Chọn riêng từng máy", "")
        form = QFormLayout()
        form.addRow("Ứng dụng", self.mode)
        layout.addLayout(form)
        self.details = QWidget()
        rows = QFormLayout(self.details)
        rows.setContentsMargins(0, 0, 0, 0)
        self.phones = {}
        variants = set()
        for device in devices:
            combo = QComboBox()
            combo.addItem("Giữ mặc định hiện tại", "")
            apps = device.get("applications", [])
            for app in apps:
                package = app["package"]
                name = "TikTok Lite" if package == LITE else "TikTok thường"
                combo.addItem(f"{name} {app.get('version', '')}", package)
            current = device.get("package", "")
            if (
                current
                and current == device.get("selected_package")
                and combo.findData(current) < 0
            ):
                combo.addItem("Ứng dụng đã chọn chưa có trên máy", current)
            combo.setCurrentIndex(max(0, combo.findData(current)))
            variants.add(
                "lite"
                if current == LITE
                else "standard" if current in {a["package"] for a in apps} else ""
            )
            combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
            self.phones[device["serial"]] = combo
            rows.addRow(device.get("name", device["serial"]), combo)
        layout.addWidget(self.details)
        mode = next(iter(variants)) if len(variants) == 1 else ""
        self.mode.setCurrentIndex(self.mode.findData(mode))
        self.initial_choice = dict(
            mode=mode,
            packages={
                serial: combo.currentData() for serial, combo in self.phones.items()
            },
        )
        self.mode.currentIndexChanged.connect(self._changed)
        self._changed()

    def _changed(self):
        self.details.setVisible(not self.mode.currentData())
        self.changed.emit()

    def packages(self, serials=None):
        result = {}
        variant = self.mode.currentData()
        for device in self.devices:
            if serials is not None and device["serial"] not in serials:
                continue
            apps = device.get("applications", [])
            installed = [a["package"] for a in apps]
            if variant:
                candidates = [
                    p for p in installed if (p == LITE) == (variant == "lite")
                ]
                current = device.get("package")
                package = (
                    current if current in candidates else next(iter(candidates), "")
                )
            else:
                package = self.phones[device["serial"]].currentData()
                if not package:
                    continue  # Preserve legacy defaults when inventory has not been refreshed.
            if not package or package not in installed:
                name = device.get("name", device["serial"])
                raise ValueError(
                    f"{name}: chưa có ứng dụng đã chọn. Hãy cài ứng dụng hoặc làm mới kết nối."
                )
            result[device["serial"]] = package
        return result

    def saved_choice(self):
        return dict(mode=self.mode.currentData(), packages=self.packages())

    def load_choice(self, choice):
        if not isinstance(choice, dict) or choice.get("mode") not in (
            "",
            "lite",
            "standard",
        ):
            raise ValueError("Lựa chọn ứng dụng không hợp lệ.")
        packages = choice.get("packages", {})
        if not isinstance(packages, dict) or any(
            not isinstance(serial, str) or not isinstance(package, str)
            for serial, package in packages.items()
        ):
            raise ValueError("Lựa chọn ứng dụng theo máy không hợp lệ.")
        for serial, package in packages.items():
            if serial in self.phones:
                combo = self.phones[serial]
                index = combo.findData(package)
                if index < 0:
                    combo.addItem("Ứng dụng đã chọn chưa có trên máy", package)
                    index = combo.count() - 1
                combo.setCurrentIndex(index)
        self.mode.setCurrentIndex(self.mode.findData(choice["mode"]))
