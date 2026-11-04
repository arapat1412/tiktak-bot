from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QVBoxLayout

from customer_desktop.theme import STYLE
from customer_desktop.widgets import EmptyState, Section, StatusBadge


def test_style_covers_existing_and_new_object_names():
    for name in (
        "brand",
        "eyebrow",
        "sidebarNote",
        "pageTitle",
        "dialogTitle",
        "banner",
        "card",
        "statNumber",
        "subtitle",
        "muted",
        "section",
        "sectionTitle",
        "statusBadge",
        "emptyState",
        "selectionBar",
        "dialogSummary",
    ):
        assert f"#{name}" in STYLE
    assert '__CHECKMARK__' in STYLE
    assert "#365ff5" in STYLE


def test_static_section_exposes_body_and_muted_description(app):
    section = Section("Thông tin", "Mô tả ngắn")
    assert section.objectName() == "section"
    assert isinstance(section.body, QVBoxLayout)
    assert section.body.parent() is section.content
    title = section.findChild(QLabel, "sectionTitle")
    assert title is not None
    assert title.text() == "Thông tin"
    description = section.findChild(QLabel, "muted")
    assert description is not None
    assert description.wordWrap()
    assert description.text() == "Mô tả ngắn"
    assert section.isExpanded()


def test_collapsible_section_keeps_child_values_while_collapsed(app):
    section = Section("Nâng cao", "Tùy chọn", collapsible=True)
    field = QLineEdit("giá trị khách nhập")
    section.body.addWidget(field)
    assert not section.content.isHidden()
    section.setExpanded(False)
    assert not section.isExpanded()
    assert section.content.isHidden()
    assert field.text() == "giá trị khách nhập"
    section.setExpanded(True)
    assert section.isExpanded()
    assert not section.content.isHidden()
    assert field.text() == "giá trị khách nhập"


def test_collapsible_section_toggles_with_click_and_keyboard(app):
    section = Section("Tùy chỉnh", collapsible=True, expanded=True)
    button = section.findChild(QPushButton, "sectionTitle")
    assert button is not None
    assert button.isCheckable()
    assert button.isChecked()
    assert "Tùy chỉnh" in button.text()

    QTest.mouseClick(button, Qt.LeftButton)
    assert not section.isExpanded()
    assert not button.isChecked()
    assert section.content.isHidden()

    QTest.keyClick(button, Qt.Key_Space)
    assert section.isExpanded()
    assert button.isChecked()
    assert not section.content.isHidden()
    assert button.accessibleName() == "Tùy chỉnh"


def test_status_badge_updates_text_tone_and_accessible_name(app):
    badge = StatusBadge("Đang chạy", "info")
    assert badge.objectName() == "statusBadge"
    assert badge.text() == "Đang chạy"
    assert badge.property("tone") == "info"

    badge.set_status("Hoàn tất", "success")
    assert badge.text() == "Hoàn tất"
    assert badge.property("tone") == "success"
    assert badge.accessibleName() == "Hoàn tất"

    for tone in ("neutral", "success", "warning", "danger", "info"):
        badge.set_status("Trạng thái", tone)
        assert badge.text() == "Trạng thái"
        assert badge.property("tone") == tone

    badge.set_status("Không rõ", "không hợp lệ")
    assert badge.property("tone") == "neutral"
    assert badge.text() == "Không rõ"

    badge.setText("Engine sẵn sàng")
    assert badge.accessibleName() == "Engine sẵn sàng"


def test_empty_state_updates_title_and_description(app):
    empty = EmptyState("Chưa có máy", "Kết nối USB để bắt đầu.")
    assert empty.objectName() == "emptyState"
    assert empty.title_label.text() == "Chưa có máy"
    assert empty.description_label.text() == "Kết nối USB để bắt đầu."
    assert empty.description_label.wordWrap()

    empty.set_content("Chưa có tác vụ", "Tác vụ mới sẽ xuất hiện tại đây.")
    assert empty.title_label.text() == "Chưa có tác vụ"
    assert empty.description_label.text() == "Tác vụ mới sẽ xuất hiện tại đây."

    empty.set_content("Chỉ có tiêu đề", "")
    assert empty.title_label.text() == "Chỉ có tiêu đề"
    assert empty.description_label.text() == ""
    assert empty.description_label.isHidden()
