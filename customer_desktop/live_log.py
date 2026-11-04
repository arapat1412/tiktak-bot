"""Bounded, polling live log viewer. No producer touches a Qt widget."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QCheckBox,
    QPushButton,
    QPlainTextEdit,
)

from customer_desktop import console


class LiveLogPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cursor = 0
        self._cutoff = 0
        self._dirty = True
        self._devices = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        title = QLabel("Nhật ký trực tiếp")
        title.setObjectName("subtitle")
        toolbar.addWidget(title)
        self.device_filter = QComboBox()
        self.device_filter.setAccessibleName("Lọc nhật ký theo điện thoại")
        self.device_filter.addItem("Tất cả máy", None)
        self.device_filter.setMinimumWidth(150)
        self.device_filter.setMaximumWidth(240)
        self.device_filter.currentIndexChanged.connect(self.redraw)
        toolbar.addWidget(self.device_filter)
        self.errors_only = QCheckBox("Cảnh báo / lỗi")
        self.errors_only.toggled.connect(self.redraw)
        toolbar.addWidget(self.errors_only)
        toolbar.addStretch()
        self.paused = QCheckBox("Tạm dừng xem")
        self.paused.setToolTip("Chỉ tạm dừng hiển thị, tác vụ vẫn tiếp tục chạy.")
        self.paused.toggled.connect(self.redraw)
        toolbar.addWidget(self.paused)
        self.auto_scroll = QCheckBox("Cuộn theo log")
        self.auto_scroll.setChecked(True)
        toolbar.addWidget(self.auto_scroll)
        self.clear_button = QPushButton("Xóa hiển thị")
        self.clear_button.clicked.connect(self.clear_view)
        toolbar.addWidget(self.clear_button)
        layout.addLayout(toolbar)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(1000)
        self.output.setAccessibleName("Nhật ký hoạt động điện thoại")
        self.output.setPlaceholderText("Nhật ký sẽ xuất hiện khi tác vụ bắt đầu…")
        layout.addWidget(self.output)
        note = QLabel(
            "Hiển thị tối đa 1.000 dòng gần nhất · Nhật ký gốc vẫn được lưu trong file."
        )
        note.setObjectName("muted")
        layout.addWidget(note)
        self.setMinimumHeight(150)
        self.setMaximumHeight(250)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def redraw(self, *_):
        self._dirty = True
        self.refresh()

    def refresh(self):
        if self.paused.isChecked():
            return
        records = console.records_after(self._cutoff if self._dirty else self._cursor)
        if not records and not self._dirty:
            return
        for serial in dict.fromkeys(record["serial"] for record in records):
            if serial not in self._devices and len(self._devices) < 256:
                self._devices.add(serial)
                self.device_filter.addItem(
                    "Ứng dụng" if serial == "APP" else serial, serial
                )
        if records:
            self._cursor = records[-1]["sequence"]
        selected = self.device_filter.currentData()
        visible = [
            record
            for record in records
            if (selected is None or record["serial"] == selected)
            and (
                not self.errors_only.isChecked()
                or record["level"] in ("WARNING", "ERROR", "CRITICAL")
            )
        ]
        text = "\n".join(console.format_record(record) for record in visible[-1000:])
        bar = self.output.verticalScrollBar()
        position = bar.value()
        if self._dirty:
            self.output.setPlainText(text)
        elif text:
            self.output.appendPlainText(text)
        self._dirty = False
        bar.setValue(bar.maximum() if self.auto_scroll.isChecked() else position)

    def clear_view(self):
        records = console.records_after()
        if records:
            self._cutoff = self._cursor = records[-1]["sequence"]
        self.output.clear()
        self._dirty = False
