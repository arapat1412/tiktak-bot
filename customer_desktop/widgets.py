"""Reusable widgets for the customer desktop screens.

These widgets only manage layout and display state. They never read files,
start timers, or talk to a device.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

TONES = ("neutral", "success", "warning", "danger", "info")

TONE_LABELS = {
    "neutral": "Bình thường",
    "success": "Thành công",
    "warning": "Cần chú ý",
    "danger": "Lỗi",
    "info": "Thông tin",
}


class Section(QFrame):
    """A bordered group with a title, optional description, and body layout."""

    def __init__(
        self,
        title,
        description="",
        collapsible=False,
        expanded=True,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("section")
        self.collapsible = bool(collapsible)
        self._title = str(title)
        self._expanded = bool(expanded) if self.collapsible else True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        self.title_label = None
        self.toggle = None
        if self.collapsible:
            self.toggle = QPushButton()
            self.toggle.setObjectName("sectionTitle")
            self.toggle.setCheckable(True)
            self.toggle.setChecked(self._expanded)
            self.toggle.setCursor(Qt.PointingHandCursor)
            self.toggle.setFocusPolicy(Qt.StrongFocus)
            self.toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.toggle.toggled.connect(self.setExpanded)
            header.addWidget(self.toggle, 1)
        else:
            self.title_label = QLabel(self._title)
            self.title_label.setObjectName("sectionTitle")
            header.addWidget(self.title_label, 1)
        outer.addLayout(header)

        self.description_label = QLabel(str(description))
        self.description_label.setObjectName("muted")
        self.description_label.setWordWrap(True)
        self.description_label.setVisible(bool(description))
        outer.addWidget(self.description_label)

        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(8)
        outer.addWidget(self.content)

        self._sync_title()
        self.setExpanded(self._expanded)

    def _sync_title(self):
        if self.toggle is None:
            return
        marker = "▾" if self._expanded else "▸"
        self.toggle.setText(f"{marker} {self._title}")
        self.toggle.setAccessibleName(self._title)
        self.toggle.setAccessibleDescription(
            "Đang mở rộng" if self._expanded else "Đang thu gọn"
        )

    def setExpanded(self, expanded):
        if not self.collapsible:
            self._expanded = True
            self.content.setVisible(True)
            return
        self._expanded = bool(expanded)
        if self.toggle.isChecked() != self._expanded:
            self.toggle.blockSignals(True)
            self.toggle.setChecked(self._expanded)
            self.toggle.blockSignals(False)
        self.content.setVisible(self._expanded)
        self._sync_title()

    def isExpanded(self):
        return self._expanded


class StatusBadge(QLabel):
    """A text badge whose tone is exposed as a QSS property."""

    def __init__(self, text="", tone="neutral", parent=None):
        super().__init__(parent)
        self.setObjectName("statusBadge")
        self.setAlignment(Qt.AlignCenter)
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.set_status(text, tone)

    def setText(self, text):
        super().setText(str(text))
        self.setAccessibleName(self.text())

    def set_status(self, text, tone="neutral"):
        tone = tone if tone in TONES else "neutral"
        self.setText(text)
        self.setProperty("tone", tone)
        self.setAccessibleDescription(TONE_LABELS[tone])
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class EmptyState(QFrame):
    """A centered placeholder shown instead of an empty table or list."""

    def __init__(self, title, description="", parent=None):
        super().__init__(parent)
        self.setObjectName("emptyState")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)

        self.title_label = QLabel()
        self.title_label.setObjectName("emptyTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.description_label = QLabel()
        self.description_label.setObjectName("muted")
        self.description_label.setAlignment(Qt.AlignCenter)
        self.description_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.description_label)
        self.set_content(title, description)

    def set_content(self, title, description=""):
        self.title_label.setText(str(title))
        self.description_label.setText(str(description))
        self.description_label.setVisible(bool(description))
        self.setAccessibleName(str(title))
