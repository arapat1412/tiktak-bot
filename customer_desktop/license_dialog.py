"""Vietnamese activation and renewal window; no device discovery."""

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
)
from PySide6.QtCore import Qt
from customer_desktop.licensing import format_expiry


class LicenseDialog(QDialog):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("Kích hoạt bản quyền TAKTIK")
        self.resize(680, 460)
        layout = QVBoxLayout(self)
        title = QLabel("Kích hoạt / Gia hạn bản quyền")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        note = QLabel(
            "Gửi mã máy bên dưới cho người cấp key, sau đó dán key được cấp để kích hoạt. "
            "License dùng cho máy tính Windows này và có hiệu lực từ lúc cấp."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(QLabel("Mã máy tính"))
        row = QHBoxLayout()
        self.machine = QLineEdit(manager.machine_id)
        self.machine.setReadOnly(True)
        self.machine.setAccessibleName("Mã máy tính Windows")
        row.addWidget(self.machine, 1)
        self.copy_button = QPushButton("Sao chép mã máy")
        self.copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(manager.machine_id)
        )
        row.addWidget(self.copy_button)
        layout.addLayout(row)
        status = manager.check()
        text = status.message
        if status.valid:
            text += " Hết hạn: " + format_expiry(status.expires_at)
        self.status = QLabel(text)
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(QLabel("Key bản quyền"))
        self.key_input = QPlainTextEdit()
        self.key_input.setPlaceholderText("Dán key TK1.… vào đây")
        self.key_input.setAccessibleName("Key bản quyền")
        self.key_input.setMaximumBlockCount(100)
        layout.addWidget(self.key_input, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton("Đóng")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        self.activate_button = QPushButton("Kích hoạt / Gia hạn")
        self.activate_button.setProperty("primary", True)
        self.activate_button.clicked.connect(self.activate)
        buttons.addWidget(self.activate_button)
        layout.addLayout(buttons)

    def activate(self):
        try:
            token = self.key_input.toPlainText()
            if len(token) > 16384:
                raise ValueError("Key quá dài hoặc không đúng định dạng.")
            status = self.manager.activate(token)
            if not status.valid:
                raise ValueError(status.message)
        except Exception as exc:
            self.status.setText("Chưa kích hoạt được: " + str(exc))
            return
        self.status.setText(
            "Đã kích hoạt. Hết hạn: " + format_expiry(status.expires_at)
        )
        self.accept()
