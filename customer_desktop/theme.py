"""Light Windows theme shared by every desktop screen.

The lead replaces __CHECKMARK__ with the absolute path of the bundled SVG
before applying the sheet, because Qt resolves url() relative to the process
working directory.
"""

STYLE = """
QWidget {
    font-family: "Segoe UI";
    font-size: 13px;
    color: #23304a;
}
QMainWindow, QDialog {
    background: #f5f7fb;
}
QStackedWidget {
    background: transparent;
}
QFrame#sidebar {
    background: #ffffff;
    border-right: 1px solid #e4e9f2;
}
QLabel#brand {
    color: #365ff5;
    font-size: 24px;
    font-weight: 800;
}
QLabel#eyebrow {
    color: #7a879e;
    font-size: 11px;
    padding-top: 2px;
}
QLabel#sidebarNote {
    color: #6b7890;
    font-size: 12px;
    padding-top: 14px;
}
QListWidget {
    border: 0;
    background: transparent;
    outline: 0;
}
QListWidget::item {
    color: #4a5872;
    padding: 9px 10px;
    border-radius: 8px;
    margin: 2px 0;
}
QListWidget::item:hover {
    background: #f2f5fb;
}
QListWidget::item:selected {
    background: #e7efff;
    color: #1c3f8f;
    font-weight: 600;
}
QLabel#pageTitle {
    font-size: 22px;
    font-weight: 700;
    color: #182741;
}
QLabel#dialogTitle {
    font-size: 20px;
    font-weight: 700;
    color: #182741;
}
QLabel#subtitle {
    color: #66748c;
    font-size: 13px;
}
QLabel#muted {
    color: #6b7890;
    font-size: 12px;
}
QLabel#banner {
    background: #eaf1ff;
    border: 1px solid #c9d9ff;
    border-radius: 8px;
    padding: 10px 12px;
    color: #274a93;
}
QFrame#card {
    background: #ffffff;
    border: 1px solid #e3e8f1;
    border-radius: 10px;
    padding: 8px;
}
QLabel#statNumber {
    font-size: 26px;
    font-weight: 700;
    color: #365ff5;
}
QFrame#section {
    background: #ffffff;
    border: 1px solid #e3e8f1;
    border-radius: 10px;
}
QLabel#sectionTitle {
    color: #1b2942;
    font-size: 15px;
    font-weight: 700;
}
QPushButton#sectionTitle {
    background: transparent;
    border: 0;
    border-radius: 6px;
    padding: 2px 0;
    color: #1b2942;
    font-size: 15px;
    font-weight: 700;
    text-align: left;
    min-height: 24px;
}
QPushButton#sectionTitle:hover {
    color: #365ff5;
}
QPushButton#sectionTitle:focus {
    border: 1px solid #365ff5;
    padding: 1px 4px;
}
QLabel#statusBadge {
    background: #f1f4f9;
    border: 1px solid #dde3ec;
    border-radius: 10px;
    padding: 3px 9px;
    color: #43516b;
    font-size: 12px;
    font-weight: 600;
}
QLabel#statusBadge[tone="success"] {
    background: #e8f7ee;
    border-color: #b7e4c7;
    color: #187a3c;
}
QLabel#statusBadge[tone="warning"] {
    background: #fff5e5;
    border-color: #f4d7a4;
    color: #8a5a00;
}
QLabel#statusBadge[tone="danger"] {
    background: #fdecec;
    border-color: #f3c2c2;
    color: #b3261e;
}
QLabel#statusBadge[tone="info"] {
    background: #eaf1ff;
    border-color: #c7d8ff;
    color: #1f4bb8;
}
QFrame#emptyState {
    background: #fbfcff;
    border: 1px dashed #cdd8ea;
    border-radius: 10px;
}
QFrame#emptyState QLabel#emptyTitle {
    color: #23304a;
    font-size: 16px;
    font-weight: 700;
}
#selectionBar {
    background: #eef3ff;
    border: 1px solid #d5e2ff;
    border-radius: 10px;
}
#selectionBar QLabel {
    color: #29457f;
}
QLabel#dialogSummary {
    background: #f7f9fc;
    border: 1px solid #e0e6f0;
    border-radius: 8px;
    padding: 9px 11px;
    color: #35425c;
    font-size: 12px;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #d5ddeb;
    border-radius: 7px;
    padding: 6px 12px;
    min-height: 20px;
    color: #26334d;
    font-weight: 600;
}
QPushButton:hover {
    background: #f3f6fc;
    border-color: #aebbd2;
}
QPushButton:pressed {
    background: #e8eef9;
}
QPushButton:focus {
    border-color: #365ff5;
}
QPushButton[primary="true"] {
    background: #365ff5;
    border-color: #365ff5;
    color: #ffffff;
}
QPushButton[primary="true"]:hover {
    background: #2b4fe0;
    border-color: #2b4fe0;
}
QPushButton[primary="true"]:pressed {
    background: #2544c4;
}
QPushButton[primary="true"]:focus {
    border-color: #1b2f7a;
}
QPushButton[danger="true"] {
    background: #ffffff;
    border-color: #f0b8b8;
    color: #b3261e;
}
QPushButton[danger="true"]:hover {
    background: #fdf1f1;
    border-color: #de8f8f;
}
QPushButton[danger="true"]:pressed {
    background: #fbe3e3;
}
QPushButton[danger="true"]:focus {
    border-color: #b3261e;
}
QPushButton:disabled {
    background: #eef1f6;
    border-color: #e0e5ee;
    color: #9aa5b8;
}
QPushButton[primary="true"]:disabled {
    background: #c8d3ee;
    border-color: #c8d3ee;
    color: #ffffff;
}
QPushButton[danger="true"]:disabled {
    background: #f4f1f1;
    border-color: #e6dede;
    color: #b8a9a9;
}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox,
QDateTimeEdit {
    background: #ffffff;
    border: 1px solid #d5ddeb;
    border-radius: 6px;
    padding: 6px 8px;
    min-height: 20px;
    selection-background-color: #365ff5;
    selection-color: #ffffff;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QDateTimeEdit:focus {
    border-color: #365ff5;
}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled,
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QDateTimeEdit:disabled {
    background: #f2f4f8;
    border-color: #e2e7ef;
    color: #9aa5b8;
}
QComboBox::drop-down, QDateTimeEdit::drop-down {
    border: 0;
    width: 28px;
}
QComboBox::down-arrow, QDateTimeEdit::down-arrow {
    image: url("__CHEVRON_DOWN__");
    width: 13px;
    height: 13px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button {
    width: 22px;
    border: 0;
    subcontrol-origin: border;
    subcontrol-position: top right;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    width: 22px;
    border: 0;
    subcontrol-origin: border;
    subcontrol-position: bottom right;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url("__CHEVRON_UP__");
    width: 11px;
    height: 11px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url("__CHEVRON_DOWN__");
    width: 11px;
    height: 11px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #d5ddeb;
    selection-background-color: #e7efff;
    selection-color: #1c3f8f;
    outline: 0;
}
QTableWidget, QTableView {
    background: #ffffff;
    alternate-background-color: #fbfcff;
    border: 1px solid #e3e8f1;
    border-radius: 10px;
    gridline-color: transparent;
    selection-background-color: #e4ecff;
    selection-color: #16295a;
}
QTableWidget::item, QTableView::item {
    border: 0;
    padding: 7px 8px;
}
QTableWidget::item:hover, QTableView::item:hover {
    background: #f3f7ff;
}
QTableWidget::item:selected, QTableView::item:selected {
    background: #e4ecff;
    color: #16295a;
}
QHeaderView::section {
    background: #f7f9fc;
    color: #4a5872;
    border: 0;
    border-bottom: 1px solid #e3e8f1;
    padding: 8px 9px;
    font-weight: 600;
}
QTableCornerButton::section {
    background: #f7f9fc;
    border: 0;
}
QScrollArea {
    border: 0;
    background: transparent;
}
QScrollArea > QWidget#qt_scrollarea_viewport {
    background: transparent;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px 1px;
}
QScrollBar::handle:vertical {
    background: #c6d0df;
    min-height: 28px;
    border-radius: 4px;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 1px 2px;
}
QScrollBar::handle:horizontal {
    background: #c6d0df;
    min-width: 28px;
    border-radius: 4px;
}
QScrollBar::handle:hover { background: #94a3b8; }
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
}
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QCheckBox, QRadioButton {
    spacing: 7px;
    padding: 2px;
}
QCheckBox::indicator, QTableView::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #9aa9c0;
    border-radius: 4px;
    background: #ffffff;
}
QCheckBox::indicator:hover, QTableView::indicator:hover {
    border-color: #365ff5;
}
QCheckBox::indicator:focus, QTableView::indicator:focus {
    border-color: #365ff5;
}
QCheckBox::indicator:checked, QTableView::indicator:checked {
    background: #365ff5;
    border-color: #365ff5;
    image: url("__CHECKMARK__");
}
QCheckBox::indicator:disabled, QTableView::indicator:disabled {
    background: #eef1f6;
    border-color: #cfd7e4;
}
QToolTip {
    background: #ffffff;
    color: #23304a;
    border: 1px solid #d5ddeb;
    padding: 5px 7px;
}
"""
