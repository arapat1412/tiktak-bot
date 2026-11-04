"""Vietnamese Qt Widgets client. Device control stays in isolated engine processes."""

from datetime import datetime
import json
from pathlib import Path
import time
import uuid
from zoneinfo import ZoneInfo

# Preload Qt6Svg on Windows before QIcon/QSS discovers SVG plugins. Otherwise
# plugin loading can miss the DLL even when it is present in the bundle.
from PySide6 import QtSvg  # noqa: F401
from PySide6.QtCore import Qt, QDateTime, QTimer, QUrl, QSignalBlocker
from PySide6.QtGui import QDesktopServices, QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from customer_desktop.domain import (
    ACTIVE_STATES,
    STATE_LABELS,
    build_browse,
    natural_browse_options,
    BROWSE_ADVANCED_DEFAULTS,
)
from customer_desktop.theme import STYLE
from customer_desktop.widgets import Section, StatusBadge, EmptyState
from customer_desktop.live_log import LiveLogPanel
from customer_desktop.capacity import MAX_PARALLEL, parallel_limit, launch_interval
from customer_desktop.app_choice import TikTokAppChoice

TZ = ZoneInfo("Asia/Bangkok")


def apply_style(app):
    # Do not inherit the host's dark palette under a light Widgets stylesheet.
    palette = QPalette()
    for role, color in (
        (QPalette.Window, "#f4f6fb"),
        (QPalette.WindowText, "#25314b"),
        (QPalette.Base, "#ffffff"),
        (QPalette.AlternateBase, "#f8faff"),
        (QPalette.Text, "#25314b"),
        (QPalette.Button, "#ffffff"),
        (QPalette.ButtonText, "#25314b"),
        (QPalette.Highlight, "#365cce"),
        (QPalette.HighlightedText, "#ffffff"),
        (QPalette.PlaceholderText, "#77859d"),
    ):
        palette.setColor(role, QColor(color))
    app.setStyle("Fusion")
    app.setPalette(palette)
    app.setStyleSheet(
        STYLE.replace(
            "__CHECKMARK__",
            (Path(__file__).parent / "resources" / "check.svg").as_posix(),
        )
        .replace(
            "__CHEVRON_DOWN__",
            (Path(__file__).parent / "resources" / "chevron-down.svg").as_posix(),
        )
        .replace(
            "__CHEVRON_UP__",
            (Path(__file__).parent / "resources" / "chevron-up.svg").as_posix(),
        )
    )


def stamp(value):
    return (
        datetime.fromtimestamp(value, TZ).strftime("%d/%m %H:%M")
        if value
        else "Chạy ngay"
    )


def button(text, fn, primary=False):
    b = QPushButton(text)
    b.setProperty("primary", primary)
    b.clicked.connect(fn)
    return b


def item(text, data=None, editable=False):
    i = QTableWidgetItem(str(text))
    if not editable:
        i.setFlags(i.flags() & ~Qt.ItemIsEditable)
    if data is not None:
        i.setData(Qt.UserRole, data)
    i.setToolTip(str(text))
    return i


def table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setAlternatingRowColors(True)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    t.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    t.horizontalHeader().setStretchLastSection(True)
    t.setWordWrap(False)
    t.setShowGrid(False)
    t.verticalHeader().setDefaultSectionSize(58)
    return t


def form_layout(parent=None):
    form = QFormLayout(parent)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.WrapLongRows)
    form.setHorizontalSpacing(18)
    form.setVerticalSpacing(12)
    return form


def text_label(text, name="muted"):
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


def error(parent, text):
    QMessageBox.warning(parent, "Cần kiểm tra", str(text))


class ScheduleWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.enabled = QCheckBox("Đặt lịch một lần")
        self.date = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        # Display Bangkok even if the Windows timezone differs.
        self.date.setDateTime(
            QDateTime.fromString(
                datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S"), "yyyy-MM-ddTHH:mm:ss"
            ).addSecs(3600)
        )
        self.date.setDisplayFormat("dd/MM/yyyy HH:mm")
        self.date.setCalendarPopup(True)
        self.date.setEnabled(False)
        self.enabled.toggled.connect(self.date.setEnabled)
        layout.addWidget(self.enabled)
        layout.addWidget(self.date)
        layout.addWidget(QLabel("Asia/Bangkok (UTC+7)"))

    def value(self):
        if not self.enabled.isChecked():
            return None
        value = (
            datetime.strptime(
                self.date.dateTime().toString("yyyy-MM-dd HH:mm"), "%Y-%m-%d %H:%M"
            )
            .replace(tzinfo=TZ)
            .timestamp()
        )
        if value <= time.time():
            raise ValueError("Giờ đặt lịch phải ở tương lai.")
        return value


class SubmitDialog(QDialog):
    def __init__(self, service, parent):
        super().__init__(parent)
        self.service = service
        self.submission_id = uuid.uuid4().hex
        self.pending = False
        # QWidget already has a create() method. Use an explicit sentinel until
        # footer() installs the submit button, since field signals fire earlier.
        self.create = None
        screen = QApplication.primaryScreen().availableGeometry()
        width = min(
            screen.width() - 60, parent.width() - 40 if parent else screen.width() - 60
        )
        height = min(
            screen.height() - 60,
            parent.height() - 40 if parent else screen.height() - 60,
        )
        self.setMinimumWidth(min(720, width))
        self.resize(min(960, width), min(720, height))
        self.outer_layout = QVBoxLayout(self)
        self.content = QWidget()
        self.layout = QVBoxLayout(self.content)
        self.layout.setContentsMargins(16, 12, 16, 12)
        self.layout.setSpacing(14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.content)
        self.outer_layout.addWidget(scroll, 1)
        self.service.submitted.connect(self._submitted)
        self.service.notice.connect(self._notice)

    def footer(self):
        note = QLabel(
            "Lịch chỉ chạy khi ứng dụng và PC đang mở. Xem điện thoại bằng Xiaowei."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        self.outer_layout.addWidget(note)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button("Đóng", self.reject))
        self.create = button("Tạo tác vụ", self.submit, True)
        row.addWidget(self.create)
        self.outer_layout.addLayout(row)

    def send(self, specs):
        self.pending = True
        self.create.setEnabled(False)
        self.create.setText("Đang kiểm tra và lưu dữ liệu…")
        try:
            self.service.submit(specs, self.submission_id)
        except Exception:
            self.pending = False
            self.create.setEnabled(True)
            raise

    def _submitted(self, ids):
        if self.pending:
            self.pending = False
            self.accept()

    def _notice(self, text):
        if self.pending and not self.service.submitting:
            self.pending = False
            self.create.setEnabled(True)
            self.create.setText("Tạo tác vụ")
            error(self, text)

    def reject(self):
        if not self.pending:
            super().reject()


class BrowseDialog(SubmitDialog):
    """Natural browsing with an explicitly saved local customer recipe."""

    RECIPE_KEY = "browse_recipe_v1"

    def __init__(self, service, devices, parent):
        super().__init__(service, parent)
        self.devices = devices
        self.setWindowTitle("Lướt tự nhiên • TAKTIK")
        self.layout.addWidget(text_label("Lướt tự nhiên", "dialogTitle"))
        self.layout.addWidget(
            text_label("Áp dụng cho: " + ", ".join(d["name"] for d in devices))
        )
        self.app_choice = TikTokAppChoice(devices)
        self.app_choice.changed.connect(self._recipe_changed)
        self.layout.addWidget(self.app_choice)
        behavior = Section(
            "1. Cách xem",
            "Video đầu chỉ xem để làm quen; thỉnh thoảng thả tim hoặc theo dõi; có khoảng nghỉ "
            "giữa phiên. Tỷ lệ là cơ hội chọn hành động, không bảo đảm số lần thực hiện.",
        )
        form = form_layout()
        self.videos = QSpinBox()
        self.videos.setRange(1, 10000)
        self.videos.setValue(20)
        self.videos.setSuffix(" video / máy")
        self.videos.valueChanged.connect(self._recipe_changed)
        form.addRow("Số video", self.videos)
        self.timed_run = QCheckBox("Chạy theo thời gian")
        self.duration_minutes = QSpinBox()
        self.duration_minutes.setRange(1, 1440)
        self.duration_minutes.setValue(30)
        self.duration_minutes.setSuffix(" phút / máy")
        self.duration_minutes.setAccessibleName("Thời gian chạy tính bằng phút")
        self.duration_minutes.setEnabled(False)
        self.timed_run.toggled.connect(self._duration_mode_changed)
        self.duration_minutes.valueChanged.connect(self._recipe_changed)
        form.addRow(self.timed_run)
        form.addRow("Thời gian chạy", self.duration_minutes)
        behavior.body.addLayout(form)
        behavior.body.addWidget(
            text_label(
                "Các máy đã chọn tự chạy song song (tối đa 50 máy). "
                "Mỗi máy tính giờ từ khi phiên lướt bắt đầu, gồm xem, tương tác và nghỉ; "
                "không dừng theo số video. Hết giờ sẽ kết thúc sau thao tác đang thực hiện."
            )
        )
        self.layout.addWidget(behavior)

        comments = Section(
            "2. Bình luận (tùy chọn)",
            "Chỉ dùng đúng câu bạn nhập, mỗi câu một lần trong phiên, theo giới hạn đã cài đặt. "
            "Để trống thì không gửi bình luận.",
        )
        self.comments = QTextEdit()
        self.comments.setPlaceholderText(
            "Mỗi dòng một câu. Hỗ trợ tiếng Việt và 한글. Để trống nếu không muốn bình luận."
        )
        self.comments.setMinimumHeight(90)
        self.comments.setMaximumHeight(140)
        self.comments.textChanged.connect(self._recipe_changed)
        comments.body.addWidget(self.comments)
        self.layout.addWidget(comments)

        self.advanced_section = Section(
            "Cài đặt nâng cao",
            "Tỷ lệ 0% để tắt hành động. Khi bật, giới hạn mỗi phiên phải lớn hơn 0. "
            "Thời gian thực tế được chọn ngẫu nhiên trong khoảng tối thiểu–tối đa.",
            collapsible=True,
            expanded=False,
        )
        advanced_form = form_layout()
        self.advanced_fields = {}
        fields = (
            ("minWatchTime", "Xem tối thiểu", 0.1, 3600, " giây", False),
            ("maxWatchTime", "Xem tối đa", 0.1, 3600, " giây", False),
            ("likeProbability", "Tỷ lệ thả tim", 0, 100, "%", False),
            ("maxLikesPerSession", "Tim tối đa / phiên", 0, 10000, "", True),
            ("followProbability", "Tỷ lệ theo dõi", 0, 100, "%", False),
            ("maxFollowsPerSession", "Theo dõi tối đa / phiên", 0, 10000, "", True),
            ("commentProbability", "Tỷ lệ bình luận", 0, 100, "%", False),
            ("maxCommentsPerSession", "Bình luận tối đa / phiên", 0, 10000, "", True),
            ("warmupVideos", "Video đầu chỉ xem", 0, 1000, " video", True),
            (
                "actionGapVideos",
                "Video bỏ qua giữa hai tương tác",
                0,
                1000,
                " video",
                True,
            ),
            ("restEveryVideos", "Nghỉ sau mỗi", 1, 1000, " video", True),
            ("pauseDurationMin", "Nghỉ tối thiểu", 0.1, 3600, " giây", False),
            ("pauseDurationMax", "Nghỉ tối đa", 0.1, 3600, " giây", False),
        )
        for key, label, low, high, suffix, integer in fields:
            field = QSpinBox() if integer else QDoubleSpinBox()
            if not integer:
                field.setDecimals(1)
                field.setSingleStep(0.1 if low else 1)
            field.setRange(low, high)
            field.setValue(BROWSE_ADVANCED_DEFAULTS[key])
            field.setSuffix(suffix)
            field.setAccessibleName(label)
            field.setObjectName(key)
            field.valueChanged.connect(self._recipe_changed)
            self.advanced_fields[key] = field
            advanced_form.addRow(label, field)
        self.advanced_section.body.addLayout(advanced_form)
        self.layout.addWidget(self.advanced_section)

        timing = Section("3. Thời gian chạy")
        self.schedule = ScheduleWidget()
        timing.body.addWidget(self.schedule)
        self.schedule.enabled.toggled.connect(self.update_preview)
        self.schedule.date.dateTimeChanged.connect(self.update_preview)
        self.layout.addWidget(timing)

        recipe_buttons = QHBoxLayout()
        self.save_recipe_button = button("Lưu kịch bản", self.save_recipe, True)
        recipe_buttons.addWidget(self.save_recipe_button)
        recipe_buttons.addWidget(button("Khôi phục mặc định", self.reset_recipe))
        recipe_buttons.addStretch()
        self.layout.addLayout(recipe_buttons)
        self.recipe_status = text_label(
            "Bấm Lưu kịch bản để dùng lại số video, bình luận và cài đặt nâng cao lần sau. "
            "Giờ hẹn chạy không được lưu."
        )
        self.layout.addWidget(self.recipe_status)

        self.previous_note = text_label("", "muted")
        self.previous_note.hide()
        self.layout.addWidget(self.previous_note)
        self.layout.addStretch()
        self.preview = text_label("", "dialogSummary")
        self.outer_layout.addWidget(self.preview)
        self.footer()
        self.load_recipe()
        self.update_preview()

    def advanced_values(self):
        return {key: field.value() for key, field in self.advanced_fields.items()}

    def _duration_mode_changed(self):
        self.videos.setEnabled(not self.timed_run.isChecked())
        self.duration_minutes.setEnabled(self.timed_run.isChecked())
        self._recipe_changed()

    def _recipe_changed(self):
        if hasattr(self, "recipe_status"):
            self.recipe_status.setText(
                "Chưa lưu thay đổi. Bấm Lưu kịch bản để dùng lại lần sau."
            )
        self.update_preview()

    def values(self):
        return natural_browse_options(
            self.videos.value(),
            self.comments.toPlainText().splitlines(),
            self.advanced_values(),
            self.duration_minutes.value() if self.timed_run.isChecked() else 0,
        )

    def _apply_recipe(self, recipe):
        self.app_choice.load_choice(recipe.get("tiktokApp", self.app_choice.initial_choice))
        options = natural_browse_options(
            recipe.get("maxVideos", 20),
            recipe.get("commentTexts", []),
            recipe.get("advanced", {}),
            recipe.get("runDurationMinutes", 0),
        )
        self.videos.setValue(options["maxVideos"])
        self.duration_minutes.setValue(options.get("runDurationMinutes", 30))
        self.timed_run.setChecked(bool(options.get("runDurationMinutes")))
        self.comments.setPlainText("\n".join(options["commentTexts"]))
        settings = BROWSE_ADVANCED_DEFAULTS | recipe.get("advanced", {})
        for key, field in self.advanced_fields.items():
            field.setValue(settings[key])
        self.update_preview()

    def load_recipe(self):
        try:
            recipe = self.service.store.setting(self.RECIPE_KEY)
            if recipe is None:
                return
            if not isinstance(recipe, dict):
                raise ValueError("Kịch bản đã lưu không hợp lệ.")
            self._apply_recipe(recipe)
        except (ValueError, TypeError, AttributeError) as exc:
            self._apply_recipe({})
            self.recipe_status.setText(
                f"Không đọc được kịch bản đã lưu; đang dùng mặc định. {exc}"
            )
        else:
            self.recipe_status.setText("Đã tải kịch bản đã lưu trên máy này.")

    def save_recipe(self):
        try:
            options = self.values()
            recipe = dict(
                maxVideos=options["maxVideos"],
                commentTexts=options["commentTexts"],
                advanced=self.advanced_values(),
            )
            if self.timed_run.isChecked():
                recipe["runDurationMinutes"] = self.duration_minutes.value()
            if self.app_choice.mode.currentData() or any(
                combo.currentData() for combo in self.app_choice.phones.values()
            ):
                recipe["tiktokApp"] = self.app_choice.saved_choice()
            self.service.store.set_setting(self.RECIPE_KEY, recipe)
        except Exception as exc:
            self.recipe_status.setText(f"Chưa lưu được kịch bản: {exc}")
            return
        self.recipe_status.setText(
            "Đã lưu kịch bản. Những lần mở sau sẽ tự dùng lại cấu hình này."
        )

    def reset_recipe(self):
        self._apply_recipe({})
        self.recipe_status.setText(
            "Đã điền mặc định. Bấm Lưu kịch bản nếu muốn giữ cho lần sau."
        )

    def load_previous(self, payload):
        data = dict(payload or {})
        try:
            videos = int(data.get("maxVideos", 20))
        except (TypeError, ValueError):
            videos = 20
        comments = data.get("commentTexts") or []
        if not isinstance(comments, list):
            comments = []
        options = natural_browse_options(
            min(10000, max(1, videos)),
            [text for text in comments if isinstance(text, str)],
            self.advanced_values(),
            data.get("runDurationMinutes", 0),
        )
        self.videos.setValue(options["maxVideos"])
        self.duration_minutes.setValue(options.get("runDurationMinutes", 30))
        self.timed_run.setChecked(bool(options.get("runDurationMinutes")))
        self.comments.setPlainText("\n".join(options["commentTexts"]))
        self.previous_note.setText(
            "Đã điền số video, thời lượng và bình luận từ tác vụ trước. Lần chạy mới dùng chính sách "
            "Lướt tự nhiên hiện tại trong Cài đặt nâng cao, không chạy lại cấu hình cũ."
        )
        self.previous_note.show()
        self.update_preview()
        return options

    def update_preview(self):
        if not hasattr(self, "preview"):
            return
        try:
            options = self.values()
            self.app_choice.packages()
        except ValueError as exc:
            self.preview.setText(str(exc))
            if self.create is not None:
                self.create.setEnabled(False)
            self.save_recipe_button.setEnabled(False)
            return
        self.save_recipe_button.setEnabled(not self.pending)
        limit = (
            f"{options['runDurationMinutes']} phút/máy"
            if options.get("runDurationMinutes")
            else f"{options['maxVideos']} video/máy"
        )
        lines = [
            "Ứng dụng: " + self.app_choice.mode.currentText(),
            f"{len(self.devices)} máy · {limit} · "
            f"xem {options['minWatchTime']:g}–{options['maxWatchTime']:g} giây/video",
            f"Tim {options['likeProbability']:g}% (tối đa {options['maxLikesPerSession']}/phiên) · "
            f"Theo dõi {options['followProbability']:g}% (tối đa {options['maxFollowsPerSession']}/phiên)",
            (
                f"Bình luận {options['commentProbability']:g}% (tối đa "
                f"{options['maxCommentsPerSession']}, "
                f"{len(options['commentTexts'])} câu, không lặp trong phiên)"
                if options["commentTexts"]
                else "Không bình luận vì danh sách bình luận để trống"
            ),
            f"Chỉ xem {options['warmupVideos']} video đầu · cách "
            f"{options['actionGapVideos']} video · nghỉ "
            f"{options['pauseDurationMin']:g}–{options['pauseDurationMax']:g} giây sau mỗi "
            f"{options['restEveryVideos']} video",
        ]
        if options.get("runDurationMinutes"):
            lines.insert(
                1,
                f"Tự chạy song song {min(len(self.devices), MAX_PARALLEL)} máy · "
                "mỗi máy chạy đủ thời gian đã đặt",
            )
        when = self.schedule.date.dateTime().toString("dd/MM HH:mm")
        lines.append(
            f"Hẹn {when} (UTC+7)" if self.schedule.enabled.isChecked() else "Chạy ngay"
        )
        if self.create is not None:
            self.create.setEnabled(not self.pending)
        self.preview.setText("\n".join(lines))

    def submit(self):
        try:
            run_at = self.schedule.value()
            packages = self.app_choice.packages()
            specs = [
                dict(
                    kind="browse",
                    serial=d["serial"],
                    payload=build_browse(d["serial"], self.values())
                    | ({"packageName": packages[d["serial"]]} if d["serial"] in packages else {}),
                    run_at=run_at,
                )
                for d in self.devices
            ]
            self.send(specs)
        except ValueError as exc:
            error(self, exc)


class PublishDialog(SubmitDialog):
    def __init__(self, service, devices, parent, initial=None):
        super().__init__(service, parent)
        self.devices = devices
        self.files = []
        self.setWindowTitle("Đăng nội dung • TAKTIK")
        self.layout.addWidget(text_label("Đăng video hoặc ảnh", "dialogTitle"))
        self.app_choice = TikTokAppChoice(devices)
        self.app_choice.changed.connect(self.update_publish_preview)
        self.layout.addWidget(self.app_choice)
        self.layout.addWidget(
            text_label(
                "Chọn tệp, nhập nội dung, rồi kiểm tra đúng máy trước khi tạo tác vụ. "
                "Bài đăng dùng tài khoản TikTok đang đăng nhập trên từng điện thoại."
            )
        )
        media = Section("1. Chọn video hoặc ảnh")
        controls = QHBoxLayout()
        controls.addWidget(button("Chọn video / ảnh…", self.add_files, True))
        self.file_count = text_label("Chưa chọn tệp")
        controls.addWidget(self.file_count, 1)
        media.body.addLayout(controls)
        self.mode = QComboBox()
        self.mode.addItems(
            ["Mỗi video cho một máy (lần lượt)", "Mỗi video cho tất cả máy đã chọn"]
        )
        allocation = form_layout()
        allocation.addRow("Cách phân bổ", self.mode)
        media.body.addLayout(allocation)
        self.layout.addWidget(media)
        content = Section(
            "2. Nội dung và thời gian",
            "Nội dung dưới đây được áp dụng cho các dòng. Bạn có thể sửa riêng từng dòng ở bước 3.",
        )
        form = form_layout()
        self.caption = QTextEdit()
        self.caption.setMinimumHeight(86)
        self.caption.setMaximumHeight(110)
        self.caption.setPlaceholderText("Viết nội dung bài đăng…")
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("Ví dụ: #amnhac #cuocsong • tối đa 5 hashtag")
        form.addRow("Nội dung bài đăng", self.caption)
        form.addRow("Hashtag", self.tags)
        self.schedule = ScheduleWidget()
        form.addRow("Thời gian", self.schedule)
        content.body.addLayout(form)
        content.body.addWidget(
            button("Áp dụng nội dung & giờ cho các dòng", self.apply_defaults)
        )
        self.layout.addWidget(content)
        review = Section(
            "3. Kiểm tra trước khi tạo",
            "Mỗi dòng là một bài trên một điện thoại. Nhấp đúp ô để sửa nội dung hoặc giờ riêng. "
            "Bài đăng dùng tài khoản TikTok đang đăng nhập trên máy.",
        )
        self.rows = table(
            [
                "Điện thoại",
                "Tệp",
                "Nội dung",
                "Hashtag",
                "Giờ UTC+7 (trống = ngay)",
            ]
        )
        self.rows.setMinimumHeight(145)
        for c, width in ((0, 145), (1, 155), (2, 240), (3, 150), (4, 180)):
            self.rows.setColumnWidth(c, width)
        review.body.addWidget(self.rows)
        self.layout.addWidget(review)
        self.summary = text_label("Chọn video hoặc ảnh để bắt đầu.", "dialogSummary")
        self.outer_layout.addWidget(self.summary)
        self.mode.currentIndexChanged.connect(self.rebuild)
        self.rows.itemChanged.connect(self.update_publish_preview)
        self.footer()
        self.update_publish_preview()
        if initial:
            self.files = [initial["localPath"]]
            self.caption.setPlainText(initial.get("caption", ""))
            self.tags.setText(" ".join(initial.get("hashtags", [])))
            self.rebuild()

    def update_publish_preview(self, *_):
        if not hasattr(self, "rows"):
            return
        self.file_count.setText(
            f"Đã chọn {len(self.files)} tệp" if self.files else "Chưa chọn tệp"
        )
        count = self.rows.rowCount()
        if count:
            serials = {
                self.rows.item(r, 0).data(Qt.UserRole)
                for r in range(count)
                if self.rows.item(r, 0)
            }
            dates = {
                self.rows.item(r, 4).text().strip()
                for r in range(count)
                if self.rows.item(r, 4)
            }
            when = (
                "Chạy ngay"
                if dates == {""}
                else (
                    f"Hẹn {next(iter(dates))} (UTC+7)"
                    if len(dates) == 1
                    else "Giờ chạy theo từng dòng trong bảng"
                )
            )
            self.summary.setText(
                "Ứng dụng: " + self.app_choice.mode.currentText() + "\n"
                f"{count} tác vụ · {len(self.files)} tệp · {len(serials)} máy nhận bài · {when}\n"
                "Kiểm tra bảng phân bổ trước khi tạo. Bài đăng dùng tài khoản TikTok đang đăng nhập trên từng máy."
            )
        else:
            self.summary.setText("Chọn video hoặc ảnh để bắt đầu.")
        valid_app = True
        if count:
            try:
                self.app_choice.packages(serials)
            except ValueError as exc:
                valid_app = False
                self.summary.setText(str(exc))
        if self.create is not None:
            self.create.setEnabled(bool(count) and valid_app and not self.pending)

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Chọn video / ảnh",
            "",
            "Video / ảnh (*.mp4 *.mov *.m4v *.webm *.png *.jpg *.jpeg)",
        )
        if files:
            self.files.extend(p for p in files if p not in self.files)
            self.rebuild()

    def rebuild(self):
        pairs = []
        for i, file in enumerate(self.files):
            devices = (
                self.devices
                if self.mode.currentIndex() == 1
                else [self.devices[i % len(self.devices)]]
            )
            pairs.extend((d, file) for d in devices)
        self.rows.setRowCount(len(pairs))
        for row, (d, file) in enumerate(pairs):
            self.rows.setItem(row, 0, item(d["name"], d["serial"]))
            self.rows.setItem(row, 1, item(Path(file).name, file))
            self.rows.setItem(row, 2, item(self.caption.toPlainText(), editable=True))
            self.rows.setItem(row, 3, item(self.tags.text(), editable=True))
            self.rows.setItem(row, 4, item("", editable=True))
        self.apply_defaults()

    def apply_defaults(self):
        try:
            value = self.schedule.value()
            scheduled = (
                datetime.fromtimestamp(value, TZ).strftime("%Y-%m-%d %H:%M")
                if value
                else ""
            )
            for row in range(self.rows.rowCount()):
                for column, text in (
                    (2, self.caption.toPlainText()),
                    (3, self.tags.text()),
                    (4, scheduled),
                ):
                    self.rows.setItem(row, column, item(text, editable=True))
            self.update_publish_preview()
        except ValueError as exc:
            error(self, exc)

    def submit(self):
        try:
            if not self.rows.rowCount():
                raise ValueError("Chọn ít nhất một video.")
            packages = self.app_choice.packages({
                self.rows.item(r, 0).data(Qt.UserRole) for r in range(self.rows.rowCount())
            })
            specs = []
            for r in range(self.rows.rowCount()):
                serial = self.rows.item(r, 0).data(Qt.UserRole)
                date = self.rows.item(r, 4).text().strip()
                try:
                    run_at = (
                        datetime.strptime(date, "%Y-%m-%d %H:%M")
                        .replace(tzinfo=TZ)
                        .timestamp()
                        if date
                        else None
                    )
                except ValueError:
                    raise ValueError(
                        f"Dòng {r+1}: giờ phải theo dạng YYYY-MM-DD HH:MM."
                    ) from None
                specs.append(
                    dict(
                        kind="publish",
                        serial=serial,
                        run_at=run_at,
                        payload=dict(
                            deviceId=serial,
                            localPath=self.rows.item(r, 1).data(Qt.UserRole),
                            caption=self.rows.item(r, 2).text(),
                            hashtags=self.rows.item(r, 3).text().split(),
                        ) | ({"packageName": packages[serial]} if serial in packages else {}),
                    )
                )
            self.send(specs)
        except ValueError as exc:
            error(self, exc)


class MainWindow(QMainWindow):
    def __init__(self, service):
        super().__init__()
        self.service = service
        self.setWindowTitle("TAKTIK • Quản lý TikTok")
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1320, screen.width() - 40), min(820, screen.height() - 50))
        self.setMinimumSize(760, 400)
        self.allow_close = False
        self.dialogs = []
        outer = QWidget()
        self.setCentralWidget(outer)
        layout = QHBoxLayout(outer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(188)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(20, 28, 20, 20)
        brand = QLabel("TAKTIK")
        brand.setObjectName("brand")
        side.addWidget(brand)
        label = QLabel("Quản lý TikTok")
        label.setObjectName("eyebrow")
        side.addWidget(label)
        side.addSpacing(20)
        self.nav = QListWidget()
        self.nav.addItems(["Điện thoại", "Hàng đợi & Lịch", "Kết quả", "Cài đặt"])
        side.addWidget(self.nav)
        note = QLabel(
            "Xem điện thoại\nMở Xiaowei để xem màn hình\nvà thao tác thủ công."
        )
        note.setObjectName("sidebarNote")
        side.addWidget(note)
        layout.addWidget(sidebar)
        body = QWidget()
        body.setMinimumSize(720, 480)
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(24, 24, 24, 20)
        self.body.setSpacing(16)
        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(5)
        self.title = QLabel("Điện thoại")
        self.title.setObjectName("pageTitle")
        self.subtitle = text_label(
            "Chọn điện thoại để bắt đầu đăng bài hoặc chạy kịch bản.", "subtitle"
        )
        heading.addWidget(self.title)
        heading.addWidget(self.subtitle)
        header.addLayout(heading, 1)
        self.engine_label = StatusBadge("Đang chuẩn bị…", "neutral")
        self.engine_label.setToolTip(
            "Bộ máy tự động hóa cần sẵn sàng trước khi thực thi hàng đợi."
        )
        header.addWidget(self.engine_label, 0, Qt.AlignTop)
        self.body.addLayout(header)
        self.notice_row = QWidget()
        notice_layout = QHBoxLayout(self.notice_row)
        notice_layout.setContentsMargins(0, 0, 0, 0)
        self.banner = text_label("", "banner")
        notice_layout.addWidget(self.banner, 1)
        notice_layout.addWidget(button("Đóng", lambda: self.notice_row.hide()))
        self.notice_row.hide()
        self.body.addWidget(self.notice_row)
        self.pages = QStackedWidget()
        self.body.addWidget(self.pages, 1)
        body_scroll = QScrollArea()
        body_scroll.setWidgetResizable(True)
        body_scroll.setWidget(body)
        layout.addWidget(body_scroll, 1)
        self.make_devices()
        self.make_queue()
        self.make_history()
        self.make_settings()
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.currentTextChanged.connect(self.title.setText)
        self.nav.currentRowChanged.connect(self.page_changed)
        self.nav.setCurrentRow(0)
        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.setInterval(150)
        self.update_timer.timeout.connect(self.refresh)
        service.changed.connect(self.schedule_refresh)
        service.capacity_changed.connect(self.refresh_capacity)
        service.notice.connect(self.show_notice)
        service.keyboard_finished.connect(self.show_keyboard_results)
        service.closing_ready.connect(self.finish_close)
        self.refresh()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(30000)
        # Inventory polling belongs to DesktopService, including headless runs.
        # Keep this stopped timer as the existing renderer/test lifecycle handle.
        QTimer.singleShot(100, service.refresh_devices)
        if not service.store.setting("onboarded", False):
            QTimer.singleShot(300, self.onboarding)

    def page_changed(self, index):
        descriptions = (
            "Chọn điện thoại để đăng bài hoặc chạy kịch bản.",
            "Theo dõi việc đang chạy và những tác vụ sắp tới.",
            "Xem kết quả, kiểm tra mục chưa rõ và mở bằng chứng.",
            "Thiết lập kết nối, dữ liệu và hỗ trợ.",
        )
        if 0 <= index < len(descriptions):
            self.subtitle.setText(descriptions[index])

    def show_notice(self, text):
        self.banner.setText(text)
        self.notice_row.setVisible(bool(text))

    def make_devices(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)
        stats = QHBoxLayout()
        stats.setSpacing(12)
        self.counts = []
        for name, description in (
            ("Đã kết nối", "Điện thoại đang online"),
            ("Đang chạy", "Tác vụ đang thực hiện"),
            ("Đang giữ", "Chờ thao tác thủ công"),
        ):
            card = QFrame()
            card.setObjectName("card")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(18, 14, 18, 14)
            top = QHBoxLayout()
            top.addWidget(text_label(name, "subtitle"))
            top.addStretch()
            n = QLabel("0")
            n.setObjectName("statNumber")
            top.addWidget(n)
            cv.addLayout(top)
            cv.addWidget(text_label(description))
            self.counts.append(n)
            stats.addWidget(card)
        v.addLayout(stats)
        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Tìm điện thoại, tài khoản hoặc nhóm…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(button("Làm mới kết nối", self.service.refresh_devices))
        self.edit_button = button("Thông tin máy", self.edit_device)
        toolbar.addWidget(self.edit_button)
        self.keyboard_button = button("Cài ADBKeyboard", self.install_keyboard)
        self.keyboard_button.setToolTip("Chọn một hoặc nhiều điện thoại; cài lần lượt, bỏ qua máy mất kết nối hoặc đang bận.")
        toolbar.addWidget(self.keyboard_button)
        self.remove_device_button = button("Xóa khỏi danh sách", self.remove_devices)
        self.remove_device_button.setProperty("danger", True)
        toolbar.addWidget(self.remove_device_button)
        v.addLayout(toolbar)
        self.device_table = table(
            [
                "Chọn",
                "Điện thoại",
                "Nhóm",
                "Tài khoản dự kiến",
                "Kết nối",
                "Hoạt động",
                "Chế độ",
            ]
        )
        for column, width in ((0, 46), (1, 195), (3, 155), (4, 160), (5, 235)):
            self.device_table.setColumnWidth(column, width)
        self.device_table.setColumnHidden(2, True)
        self.device_table.setColumnHidden(6, True)
        self.device_table.horizontalHeader().setStretchLastSection(False)
        self.device_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.Stretch
        )
        self.device_table.cellDoubleClicked.connect(lambda *_: self.edit_device())
        self.device_table.cellClicked.connect(self.check_clicked_device)
        self.device_table.itemChanged.connect(self.update_selection)
        self.device_table.itemSelectionChanged.connect(self.update_selection)
        v.addWidget(self.device_table, 1)
        self.device_empty = EmptyState(
            "Chưa có điện thoại",
            "1. Kết nối USB và bật USB debugging.\n2. Chấp nhận quyền kết nối trên điện thoại.\n3. Bấm Làm mới kết nối để tìm máy.",
        )
        v.addWidget(self.device_empty, 1)
        action_bar = QFrame()
        action_bar.setObjectName("selectionBar")
        actions = QHBoxLayout(action_bar)
        actions.setContentsMargins(14, 12, 14, 12)
        self.select_all = QCheckBox("Chọn tất cả")
        self.select_all.clicked.connect(self.select_all_visible)
        actions.addWidget(self.select_all)
        self.selection_label = text_label("Chưa chọn máy")
        actions.addWidget(self.selection_label)
        actions.addStretch()
        self.hold_button = button("Dừng / Giữ máy", self.hold)
        self.hold_button.setProperty("danger", True)
        self.release_button = button("Tiếp tục", self.release)
        self.release_button.setToolTip(
            "Cho phép hàng đợi tiếp tục sau khi bạn đã kiểm tra điện thoại."
        )
        self.browse_button = button("Lướt tự nhiên", self.browse)
        self.publish_button = button("Đăng nội dung", self.publish, True)
        for b in (
            self.hold_button,
            self.release_button,
            self.browse_button,
            self.publish_button,
        ):
            actions.addWidget(b)
        v.addWidget(action_bar)
        self.live_log = LiveLogPanel(page)
        v.addWidget(self.live_log)
        v.addWidget(
            text_label(
                "Tài khoản tự cập nhật khi engine đọc hồ sơ đăng nhập. Dừng và chờ máy sẵn sàng trước khi thao tác trong Xiaowei."
            )
        )
        self.pages.addWidget(page)

    def select_all_visible(self, checked):
        self.device_table.blockSignals(True)
        try:
            for r in range(self.device_table.rowCount()):
                self.device_table.item(r, 0).setCheckState(
                    Qt.Checked if checked else Qt.Unchecked
                )
            if not checked:
                self.device_table.clearSelection()
                self.device_table.setCurrentCell(-1, -1)
        finally:
            self.device_table.blockSignals(False)
        self.update_selection()

    def check_clicked_device(self, row, column):
        if column != 0 and (cell := self.device_table.item(row, 0)):
            cell.setCheckState(Qt.Checked)

    def update_selection(self, *_):
        if not hasattr(self, "publish_button") or self.device_table.signalsBlocked():
            return
        devices = self.selected_devices()
        count = len(devices)
        self.selection_label.setText(
            f"Đã chọn {count} máy" if count else "Chưa chọn máy"
        )
        can_create = bool(devices) and all(
            d["connection"] == "online" and d["package"] for d in devices
        )
        self.publish_button.setEnabled(can_create)
        self.browse_button.setEnabled(can_create)
        self.hold_button.setEnabled(bool(devices))
        self.release_button.setEnabled(any(d["hold"] for d in devices))
        self.edit_button.setEnabled(count == 1)
        removal_reason = self.service.device_removal_reason([d["serial"] for d in devices])
        self.remove_device_button.setEnabled(not bool(removal_reason))
        self.remove_device_button.setToolTip(
            removal_reason or "Xóa máy mất kết nối khỏi danh sách; giữ nguyên lịch sử tác vụ."
        )
        installing = bool(self.service.keyboard_installing)
        label = f"Cài ADBKeyboard ({count} máy)" if count > 1 else "Cài ADBKeyboard"
        self.keyboard_button.setText("Đang cài bàn phím…" if installing else label)
        self.keyboard_button.setEnabled(
            bool(devices) and not installing and not self.service.closing
        )
        self.select_all.setEnabled(self.device_table.rowCount() > 0)
        self.select_all.setChecked(
            bool(self.device_table.rowCount())
            and len(self.selected_serials()) == self.device_table.rowCount()
        )
        hint = "Chọn máy đã kết nối và có TikTok để tạo tác vụ."
        self.publish_button.setToolTip(
            "Đăng video hoặc ảnh lên máy đã chọn." if can_create else hint
        )
        self.browse_button.setToolTip(
            "Lướt, tim, bình luận và theo dõi theo cấu hình." if can_create else hint
        )

    def make_queue(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.queue_filter = QComboBox()
        self.queue_filter.addItems(
            [
                "Tất cả trạng thái",
                "Đang chờ",
                "Đã đặt lịch",
                "Lịch quá hạn",
                "Đang chạy",
            ]
        )
        self.queue_filter.currentIndexChanged.connect(self.refresh)
        self.queue_device = QComboBox()
        self.queue_device.addItem("Tất cả máy", "")
        self.queue_device.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.queue_filter)
        row.addWidget(self.queue_device)
        row.addStretch()
        row.addWidget(QLabel("Asia/Bangkok • UTC+7"))
        v.addLayout(row)
        self.queue_table = table(
            ["Tác vụ", "Máy", "Giờ chạy (UTC+7)", "Trạng thái", "Lý do chờ / Tiến độ"]
        )
        self.queue_table.setColumnWidth(0, 130)
        self.queue_table.setColumnWidth(1, 160)
        self.queue_table.setColumnWidth(2, 160)
        self.queue_table.setColumnWidth(3, 170)
        v.addWidget(self.queue_table, 1)
        self.queue_empty = EmptyState(
            "Chưa có tác vụ",
            "Chọn điện thoại, sau đó Đăng nội dung hoặc Lướt tự nhiên. Các tác vụ và lịch hẹn sẽ xuất hiện tại đây.",
        )
        v.addWidget(self.queue_empty, 1)
        actions = QHBoxLayout()
        self.queue_buttons = []
        for label, fn in [
            ("Chi tiết / Sửa", lambda: self.job_details(False)),
            ("Chạy lịch quá hạn", self.run_overdue),
            ("Hủy tác vụ", self.cancel_job),
            ("Dừng máy", self.stop_job),
        ]:
            b = button(label, fn)
            self.queue_buttons.append(b)
            actions.addWidget(b)
        self.queue_table.itemSelectionChanged.connect(self.update_job_actions)
        v.addLayout(actions)
        note = QLabel(
            "Mỗi máy chỉ chạy một tác vụ. Máy bận, bị giữ hoặc mất kết nối sẽ tiếp tục chờ. Khi PC ngủ hoặc ứng dụng đóng, lịch không chạy; lịch quá hạn cần bạn chọn xử lý."
        )
        note.setWordWrap(True)
        v.addWidget(note)
        self.pages.addWidget(page)

    def make_history(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        self.history_table = table(
            ["Loại", "Máy", "Thời gian (UTC+7)", "Kết quả", "Thông tin"]
        )
        for c, w in ((0, 120), (1, 160), (2, 160), (3, 210)):
            self.history_table.setColumnWidth(c, w)
        v.addWidget(self.history_table, 1)
        self.history_empty = EmptyState(
            "Chưa có kết quả",
            "Khi một tác vụ kết thúc, bạn có thể xem trạng thái và bằng chứng tại đây.",
        )
        v.addWidget(self.history_empty, 1)
        actions = QHBoxLayout()
        self.history_buttons = [
            button("Chi tiết & bằng chứng", lambda: self.job_details(True)),
            button("Mở nhật ký", self.open_logs),
            button("Kiểm tra & tạo mới", self.retry_review),
        ]
        for b in self.history_buttons:
            actions.addWidget(b)
        self.history_table.itemSelectionChanged.connect(self.update_job_actions)
        v.addLayout(actions)
        note = QLabel(
            "“Engine xác nhận” là kết quả TAKTIK báo lại. Đối chiếu bài đăng/comment/follow trên TikTok để kiểm chứng thực tế. Kết quả chưa rõ luôn giữ máy và không tự chạy lại."
        )
        note.setWordWrap(True)
        v.addWidget(note)
        self.pages.addWidget(page)

    def make_settings(self):
        page = QWidget()
        f = QFormLayout(page)
        f.setContentsMargins(0, 0, 0, 0)
        self.adb_path = QLineEdit(self.service.store.setting("adb", ""))
        self.adb_path.setPlaceholderText("Để trống: dùng adb trong PATH")
        f.addRow("Đường dẫn ADB", self.adb_path)
        self.adb_port = QSpinBox()
        self.adb_port.setRange(1, 65535)
        self.adb_port.setValue(self.service.store.setting("adb_port", 5037))
        self.adb_port.setToolTip(
            "Cổng ưu tiên; tool tự tìm thêm 5037, 5038 và các ADB server đang chạy."
        )
        f.addRow("Cổng ADB ưu tiên", self.adb_port)
        self.parallel = QSpinBox()
        self.parallel.setRange(1, MAX_PARALLEL)
        self.parallel.setValue(
            parallel_limit(self.service.store.setting("max_parallel", 1))
        )
        f.addRow("Số máy chạy đồng thời", self.parallel)
        self.launch_delay = QSpinBox()
        self.launch_delay.setRange(1, 60)
        self.launch_delay.setValue(
            max(
                1,
                int(launch_interval(self.service.store.setting("launch_interval", 2))),
            )
        )
        self.launch_delay.setSuffix(" giây")
        f.addRow("Khoảng cách mở máy tiếp theo", self.launch_delay)
        f.addRow(
            text_label(
                "Các thiết lập trên áp dụng cho đăng nội dung và lướt theo số video. "
                "Lướt theo thời gian tự chạy song song tối đa 50 máy.",
                "hint",
            )
        )
        self.capacity_label = text_label("", "hint")
        f.addRow("Điều phối", self.capacity_label)
        self.retention = QSpinBox()
        self.retention.setRange(1, 365)
        self.retention.setValue(self.service.store.setting("retention_days", 30))
        self.retention.setSuffix(" ngày")
        f.addRow("Thời gian giữ log / ảnh", self.retention)
        loc = QLabel(str(self.service.root))
        loc.setTextInteractionFlags(Qt.TextSelectableByMouse)
        loc.setWordWrap(True)
        f.addRow("Dữ liệu ứng dụng", loc)
        f.addRow(button("Lưu cài đặt", self.save_settings, True))
        self.license_machine = QLineEdit(
            getattr(self.service.license_manager, "machine_id", "")
        )
        self.license_machine.setReadOnly(True)
        f.addRow("Mã máy bản quyền", self.license_machine)
        self.license_label = text_label("")
        f.addRow("Trạng thái bản quyền", self.license_label)
        f.addRow(button("Kích hoạt / Gia hạn license", self.manage_license))
        self.refresh_license()
        f.addRow(
            button(
                "Mở thư mục dữ liệu",
                lambda: QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(self.service.root))
                ),
            )
        )
        f.addRow(button("Sao lưu database ứng dụng", self.backup))
        f.addRow(
            button(
                "Dọn log / ảnh quá hạn",
                lambda: self.service.prune_logs(self.retention.value()),
            )
        )
        f.addRow(button("Xuất thông tin hỗ trợ đã lược dữ liệu riêng", self.export))
        hint = QLabel(
            "Dữ liệu được giữ ngoài thư mục cài đặt. Dùng TAKTIK_CUSTOMER_DATA khi cần chuyển nơi lưu; chỉ đổi khi đã đóng ứng dụng.\n"
            "Ứng dụng dùng ADB đang có, không đổi driver hay dừng ADB server. Chưa tích hợp API Xiaowei.\n"
            "Bản thử 0.1.0 • TAKTIK GPL-3.0 và Qt LGPL-3.0. Xem LICENSE / thông báo nguồn trong gói bàn giao.\n"
            "Chỉ công bố số máy và phiên bản TikTok sau khi kiểm chứng thực tế. Các ngôn ngữ/phiên bản chưa thử có thể cần điều chỉnh selector."
        )
        hint.setWordWrap(True)
        f.addRow(hint)
        self.pages.addWidget(page)

    def selected_serials(self):
        return [
            self.device_table.item(r, 0).data(Qt.UserRole)
            for r in range(self.device_table.rowCount())
            if self.device_table.item(r, 0).checkState() == Qt.Checked
        ]

    def refresh_license(self):
        if not hasattr(self, "license_label"):
            return
        from customer_desktop.licensing import format_expiry

        status = self.service.license_status
        text = status.message
        if status.valid and getattr(status, "expires_at", None):
            text += " Hết hạn: " + format_expiry(status.expires_at)
        self.license_label.setText(text)

    def manage_license(self):
        from customer_desktop.license_dialog import LicenseDialog

        dialog = LicenseDialog(self.service.license_manager, self)

        def updated(*_):
            self.service.license_status = self.service.license_manager.check()
            self.refresh_license()
            self.service.capacity_changed.emit()

        dialog.finished.connect(updated)
        self.show_dialog(dialog)

    def selected_devices(self):
        serials = self.selected_serials()
        return [d for d in self.service.store.devices() if d["serial"] in serials]

    def require_devices(self):
        devices = self.selected_devices()
        if not devices:
            raise ValueError("Chọn điện thoại trong bảng trước.")
        if any(d["connection"] != "online" or not d["package"] for d in devices):
            raise ValueError(
                "Chỉ tạo tác vụ cho máy đã kết nối và có TikTok. Kiểm tra quyền ADB rồi làm mới."
            )
        return devices

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.finished.connect(
            lambda *_: self.dialogs.remove(dialog) if dialog in self.dialogs else None
        )
        dialog.open()

    def publish(self):
        try:
            self.show_dialog(PublishDialog(self.service, self.require_devices(), self))
        except ValueError as exc:
            error(self, exc)

    def browse(self):
        try:
            self.show_dialog(BrowseDialog(self.service, self.require_devices(), self))
        except ValueError as exc:
            error(self, exc)

    def install_keyboard(self):
        try:
            devices = self.selected_devices()
            self.service.install_device_keyboards([d["serial"] for d in devices])
        except ValueError as exc:
            error(self, exc)

    def show_keyboard_results(self, results):
        if self.service.closing:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Kết quả cài ADBKeyboard")
        dialog.resize(820, 420)
        layout = QVBoxLayout(dialog)
        layout.addWidget(text_label(f"Đã xử lý {len(results)} điện thoại. Xem kết quả từng máy bên dưới."))
        rows = table(["Điện thoại", "Kết quả", "Chi tiết"])
        rows.setRowCount(len(results))
        labels = {"installed": "Đã cài", "existing": "Đã có sẵn", "failed": "Lỗi", "skipped": "Bỏ qua"}
        for row, result in enumerate(results):
            for column, value in enumerate((result["serial"], labels[result["status"]], result["message"])):
                rows.setItem(row, column, item(value))
        rows.setColumnWidth(0, 165)
        rows.setColumnWidth(1, 120)
        layout.addWidget(rows)
        layout.addWidget(button("Đóng", dialog.accept))
        self.show_dialog(dialog)

    def edit_device(self):
        ds = self.selected_devices()
        if len(ds) != 1:
            return error(self, "Chọn đúng một máy để sửa tên / nhóm / tài khoản.")
        d = ds[0]
        dialog = QDialog(self)
        dialog.setWindowTitle("Thông tin điện thoại")
        form = QFormLayout(dialog)
        form.addRow("Serial", QLabel(d["serial"]))
        fields = [QLineEdit(d[k]) for k in ("name", "group_name", "account")]
        for label, field in zip(
            ("Tên máy", "Nhóm", "Tài khoản dự kiến (chưa xác minh)"), fields
        ):
            form.addRow(label, field)
        form.addRow(
            "Thiết bị",
            QLabel(f"{d['model']} • Android {d['android']} • TikTok {d['version']}"),
        )
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Lưu")
        buttons.button(QDialogButtonBox.Cancel).setText("Hủy")
        form.addRow(buttons)
        buttons.rejected.connect(dialog.reject)

        def save():
            self.service.store.save_device(d["serial"], *(f.text() for f in fields))
            dialog.accept()
            self.refresh()

        buttons.accepted.connect(save)
        self.show_dialog(dialog)

    def remove_devices(self):
        serials = self.selected_serials()
        reason = self.service.device_removal_reason(serials)
        if reason:
            return error(self, reason)
        chosen = self.selected_devices()
        names = "\n".join(f"• {d['name']} ({d['serial']})" for d in chosen[:8])
        if len(chosen) > 8:
            names += f"\n… và {len(chosen) - 8} máy khác."
        answer = QMessageBox.question(
            self, "Xóa điện thoại khỏi danh sách",
            f"Xóa {len(chosen)} điện thoại mất kết nối khỏi danh sách?\n\n{names}\n\n"
            "Lịch sử tác vụ và nhật ký vẫn được giữ. Máy sẽ hiện lại khi kết nối ADB trở lại.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            count = self.service.remove_devices(serials)
            self.refresh()
            self.banner.setText(f"Đã xóa {count} máy khỏi danh sách. Lịch sử tác vụ được giữ nguyên.")
        except ValueError as exc:
            error(self, exc)

    def hold(self):
        for d in self.selected_devices():
            self.service.stop_serial(d["serial"])

    def release(self):
        try:
            for d in self.selected_devices():
                self.service.release_serial(d["serial"])
        except ValueError as exc:
            error(self, exc)

    def schedule_refresh(self):
        if not self.update_timer.isActive():
            self.update_timer.start()

    def refresh_capacity(self):
        self.refresh_license()
        reason = self.service.admission_reason
        self.capacity_label.setText(
            reason or "Tài nguyên đủ để nhận việc mới theo hạn mức đã đặt."
        )
        self.engine_label.set_status(
            (
                "Đang chuẩn bị…"
                if not self.service.ready
                else "Chờ tài nguyên" if reason else "Sẵn sàng"
            ),
            "neutral" if not self.service.ready else "warning" if reason else "success",
        )
        self.engine_label.setToolTip(
            reason or "Engine sẵn sàng; hàng đợi khởi động từng máy theo nhịp đã đặt."
        )

    def refresh(self, *_):
        if not hasattr(self, "device_table"):
            return
        self.update_timer.stop()
        selected = set(self.selected_serials())
        current = self.device_table.currentRow()
        current_serial = (
            self.device_table.item(current, 0).data(Qt.UserRole)
            if current >= 0
            else None
        )
        devices = self.service.store.devices()
        jobs = self.service.store.jobs()
        by_device = {}
        for job in reversed(jobs):
            by_device[job["serial"]] = job
        active = {j["serial"]: j for j in jobs if j["state"] in ACTIVE_STATES}
        devices_by_serial = {d["serial"]: d for d in devices}
        self.counts[0].setText(str(sum(d["connection"] == "online" for d in devices)))
        self.counts[1].setText(str(len(active)))
        self.counts[2].setText(str(sum(bool(d["hold"]) for d in devices)))
        self.refresh_capacity()
        query = self.search.text().casefold()
        visible = [
            d
            for d in devices
            if query
            in " ".join(
                str(d[k]) for k in ("name", "serial", "group_name", "account")
            ).casefold()
        ]
        with QSignalBlocker(self.device_table):
            self.device_table.setRowCount(len(visible))
            for r, d in enumerate(visible):
                serial = d["serial"]
                job = active.get(serial) or by_device.get(serial)
                check = self.device_table.item(r, 0)
                if check is None or check.data(Qt.UserRole) != serial:
                    check = item("", serial)
                    check.setFlags(check.flags() | Qt.ItemIsUserCheckable)
                    self.device_table.setItem(r, 0, check)
                check.setCheckState(Qt.Checked if serial in selected else Qt.Unchecked)
                progress = (
                    STATE_LABELS.get(job["state"], job["state"]) if job else "Sẵn sàng"
                )
                if not job and d["connection"] != "online":
                    progress = "Chờ kết nối"
                elif not job and not d["package"]:
                    progress = "Chưa thấy TikTok"
                if job and job["id"] in self.service.runners:
                    stats = self.service.runners[job["id"]].tracker.stats
                    progress += f"\nXem {stats.get('videos_watched',0)} / Tim {stats.get('videos_liked',0)} / Comment {stats.get('videos_commented','—')} / Follow {stats.get('users_followed',0)}"
                if d["hold"]:
                    progress = (
                        "Thủ công sẵn sàng"
                        if serial not in active
                        else "Đang dừng để giữ máy"
                    )
                values = [
                    d["name"] + "\n" + serial,
                    d["group_name"],
                    ("@" + d["account"]) if d["account"] else "Chưa gán",
                    STATE_LABELS.get(d["connection"], d["connection"])
                    + (f" · ADB {self.service.device_ports[serial]}" if serial in self.service.device_ports else "")
                    + "\n"
                    + (
                        (
                            ("TikTok Lite " if d["package"] == "com.ss.android.ugc.tiktok.lite" else "TikTok thường ")
                            + d["version"]
                        )
                        if d["version"]
                        else "Chưa thấy ứng dụng đã chọn"
                    ),
                    progress,
                    (
                        ("Chờ worker dừng" if serial in active else "Thủ công sẵn sàng")
                        if d["hold"]
                        else "Tự động"
                    ),
                ]
                for c, value in enumerate(values, 1):
                    cell = self.device_table.item(r, c)
                    if cell is None:
                        cell = item(value)
                        self.device_table.setItem(r, c, cell)
                    elif cell.text() != value:
                        cell.setText(value)
                    if c == 1:
                        cell.setToolTip(
                            f"{d['name']}\nSerial: {serial}\nNhóm: {d['group_name'] or 'Chưa gán'}"
                        )
                    if c == 3:
                        cell.setToolTip(
                            "Tự cập nhật khi engine đọc hồ sơ tài khoản đang đăng nhập trên máy này. "
                            "Nếu đổi tài khoản trên điện thoại, thông tin sẽ đổi ở lần đọc tiếp theo."
                        )
                    if c == 4:
                        cell.setForeground(
                            QColor(
                                "#157052" if d["connection"] == "online" else "#a65023"
                            )
                        )
                    if c == 5:
                        cell.setForeground(
                            QColor("#a65023" if d["hold"] else "#25314b")
                        )
                if serial == current_serial:
                    self.device_table.selectRow(r)
        self.update_selection()
        self.device_table.setVisible(bool(visible))
        self.device_empty.setVisible(not visible)
        if devices:
            self.device_empty.set_content(
                "Không tìm thấy điện thoại phù hợp",
                "Thử tên máy, nhóm hoặc tài khoản khác; bấm dấu × để xóa tìm kiếm.",
            )
        else:
            self.device_empty.set_content(
                "Chưa có điện thoại",
                "Kết nối USB, bật USB debugging và chấp nhận quyền trên điện thoại.\nSau đó bấm Làm mới kết nối để tìm máy.",
            )
        existing = [
            self.queue_device.itemData(i) for i in range(1, self.queue_device.count())
        ]
        if existing != [d["serial"] for d in devices]:
            chosen = self.queue_device.currentData()
            self.queue_device.blockSignals(True)
            self.queue_device.clear()
            self.queue_device.addItem("Tất cả máy", "")
            for d in devices:
                self.queue_device.addItem(d["name"], d["serial"])
            self.queue_device.setCurrentIndex(
                max(0, self.queue_device.findData(chosen))
            )
            self.queue_device.blockSignals(False)
        names = {d["serial"]: d["name"] for d in devices}
        waiting = [
            j
            for j in jobs
            if j["state"] not in ("succeeded", "failed", "needs_review", "cancelled")
        ]
        desired = [None, ("queued",), ("scheduled",), ("overdue",), ACTIVE_STATES][
            self.queue_filter.currentIndex()
        ]
        waiting = [
            j
            for j in waiting
            if (not desired or j["state"] in desired)
            and (
                not self.queue_device.currentData()
                or j["serial"] == self.queue_device.currentData()
            )
        ]
        self.fill_jobs(self.queue_table, waiting, names, devices=devices_by_serial)
        self.fill_jobs(
            self.history_table,
            [
                j
                for j in jobs
                if j["state"] in ("succeeded", "failed", "needs_review", "cancelled")
            ],
            names,
            True,
            devices=devices_by_serial,
        )
        self.update_job_actions()

    def update_job_actions(self):
        if not hasattr(self, "history_buttons"):
            return
        job = self.selected_job(self.queue_table)
        state = job["state"] if job else ""
        for b, enabled in zip(
            self.queue_buttons,
            (
                bool(job),
                state == "overdue",
                state in ("queued", "scheduled", "overdue"),
                state in ACTIVE_STATES,
            ),
        ):
            b.setEnabled(enabled)
        job = self.selected_job(self.history_table)
        for b in self.history_buttons:
            b.setEnabled(bool(job))
        if job:
            self.history_buttons[2].setEnabled(self.service.manual_ready(job["serial"]))

    def fill_jobs(self, t, jobs, names, history=False, devices=None):
        with QSignalBlocker(t):
            t.setUpdatesEnabled(False)
            try:
                self._fill_jobs(t, jobs, names, history, devices)
            finally:
                t.setUpdatesEnabled(True)

    def _fill_jobs(self, t, jobs, names, history=False, devices=None):
        old = self.selected_job(t)
        selected = old["id"] if old else None
        if devices is None:
            devices = {d["serial"]: d for d in self.service.store.devices()}
        signature = (jobs, names, devices)
        if getattr(t, "_render_signature", None) == signature:
            return
        t._render_signature = signature
        t.setRowCount(len(jobs))
        t.setVisible(bool(jobs))
        empty = self.history_empty if history else self.queue_empty
        empty.setVisible(not jobs)
        if not history:
            filtered = self.queue_filter.currentIndex() != 0 or bool(
                self.queue_device.currentData()
            )
            empty.set_content(
                "Không có tác vụ phù hợp" if filtered else "Chưa có tác vụ",
                (
                    "Thử thay đổi bộ lọc để xem các tác vụ khác."
                    if filtered
                    else "Chọn điện thoại, sau đó Đăng nội dung hoặc Lướt tự nhiên. Tác vụ và lịch hẹn sẽ xuất hiện tại đây."
                ),
            )
        for r, j in enumerate(jobs):
            message = j["message"]
            d = devices.get(j["serial"])
            if j["state"] == "queued" and d:
                if d["hold"]:
                    message = "Máy đang được giữ; cho phép chạy tiếp sau khi đối chiếu."
                elif d["connection"] != "online":
                    message = "Chờ điện thoại kết nối."
                elif any(
                    x.job["serial"] == j["serial"]
                    for x in self.service.runners.values()
                ):
                    message = "Chờ tác vụ trước trên cùng máy."
            values = [
                "Đăng video" if j["kind"] == "publish" else "Kịch bản For You",
                names.get(j["serial"], j["serial"]),
                stamp(j["created"] if history else j["run_at"]),
                STATE_LABELS.get(j["state"], j["state"]),
                message,
            ]
            for c, text in enumerate(values):
                existing = t.item(r, c)
                identity = j["id"] if c == 0 else None
                if (
                    existing
                    and existing.text() == text
                    and existing.data(Qt.UserRole) == identity
                ):
                    continue
                cell = item(text, j["id"] if c == 0 else None)
                if c == 3:
                    color = (
                        "#a65023"
                        if j["state"] in ("needs_review", "overdue", "stopping")
                        else (
                            "#157052"
                            if j["state"] == "succeeded"
                            else "#365ff5" if j["state"] in ACTIVE_STATES else "#64748b"
                        )
                    )
                    cell.setForeground(QColor(color))
                t.setItem(r, c, cell)
            if j["id"] == selected:
                t.selectRow(r)

    def selected_job(self, t):
        r = t.currentRow()
        cell = t.item(r, 0) if r >= 0 else None
        return self.service.store.job(cell.data(Qt.UserRole)) if cell else None

    def cancel_job(self):
        if j := self.selected_job(self.queue_table):
            self.service.cancel(j["id"])

    def run_overdue(self):
        j = self.selected_job(self.queue_table)
        if j and j["state"] == "overdue":
            self.service.run_waiting(j["id"])
        else:
            error(self, "Chọn một lịch quá hạn trước.")

    def stop_job(self):
        if j := self.selected_job(self.queue_table):
            self.service.stop_serial(j["serial"])

    def job_details(self, history):
        j = self.selected_job(self.history_table if history else self.queue_table)
        if not j:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Chi tiết tác vụ " + j["id"][:8])
        dialog.resize(780, 650)
        v = QVBoxLayout(dialog)
        info = QLabel(
            f"{STATE_LABELS.get(j['state'])}\n{j['message']}\nSerial: {j['serial']} • UTC+7"
        )
        info.setWordWrap(True)
        v.addWidget(info)
        text = QTextEdit()
        text.setReadOnly(True)
        attempts = self.service.store.attempts(j["id"])
        text.setPlainText(
            "Snapshot tác vụ:\n"
            + json.dumps(json.loads(j["snapshot"]), ensure_ascii=False, indent=2)
            + "\n\nLần chạy và bằng chứng:\n"
            + json.dumps(attempts, ensure_ascii=False, indent=2)
        )
        v.addWidget(text)
        if j["state"] in ("queued", "scheduled", "overdue"):
            form = QFormLayout()
            caption = QTextEdit()
            caption.setMaximumHeight(90)
            p = json.loads(j["snapshot"])
            caption.setPlainText(p.get("caption", ""))
            tags = QLineEdit(" ".join(p.get("hashtags", [])))
            schedule = ScheduleWidget()
            if j["run_at"] and j["run_at"] > time.time():
                schedule.enabled.setChecked(True)
                schedule.date.setDateTime(
                    QDateTime.fromString(
                        datetime.fromtimestamp(j["run_at"], TZ).strftime(
                            "%Y-%m-%d %H:%M"
                        ),
                        "yyyy-MM-dd HH:mm",
                    )
                )
            if j["kind"] == "publish":
                form.addRow("Caption mới", caption)
                form.addRow("Hashtag", tags)
            form.addRow("Thời gian mới", schedule)
            v.addLayout(form)

            def save():
                try:
                    when = schedule.value()
                    if j["kind"] == "publish":
                        p["caption"] = caption.toPlainText()
                        p["hashtags"] = tags.text().split()
                    # Only pending jobs are editable; scheduler may have claimed it meanwhile.
                    cur = self.service.store.db.execute(
                        "UPDATE jobs SET snapshot=?,run_at=?,state=?,updated=? WHERE id=? AND state IN ('queued','scheduled','overdue')",
                        (
                            json.dumps(p, ensure_ascii=False),
                            when,
                            "scheduled" if when else "queued",
                            time.time(),
                            j["id"],
                        ),
                    )
                    self.service.store.db.commit()
                    if cur.rowcount != 1:
                        raise ValueError("Tác vụ đã bắt đầu; không thể sửa nữa.")
                    dialog.accept()
                    self.refresh()
                except ValueError as exc:
                    error(dialog, exc)

            v.addWidget(button("Lưu thay đổi mục chờ", save, True))
        v.addWidget(button("Đóng", dialog.accept))
        self.show_dialog(dialog)

    def open_logs(self):
        if j := self.selected_job(self.history_table):
            path = self.service.root / "logs" / j["id"]
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def retry_review(self):
        j = self.selected_job(self.history_table)
        if not j:
            return
        if not self.service.manual_ready(j["serial"]):
            return error(self, "Chờ worker dừng xong trước.")
        if (
            QMessageBox.question(
                self,
                "Tạo tác vụ mới",
                "Bạn đã đối chiếu kết quả trên điện thoại và muốn tạo một tác vụ mới có thể lặp lại hành động? Đây không phải tiếp tục lần chạy trước.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        devices = [
            d for d in self.service.store.devices() if d["serial"] == j["serial"]
        ]
        p = json.loads(j["snapshot"])
        if j["kind"] == "publish":
            self.show_dialog(PublishDialog(self.service, devices, self, initial=p))
        else:
            d = BrowseDialog(self.service, devices, self)
            d.load_previous(p)
            self.show_dialog(d)

    def save_settings(self):
        if self.service.runners or self.service.validating:
            return error(self, "Dừng các tác vụ trước khi đổi cài đặt.")
        path = self.adb_path.text().strip()
        if path and not Path(path).is_file():
            return error(self, "Đường dẫn ADB không tồn tại.")
        for key, value in (
            ("adb", path),
            ("adb_port", self.adb_port.value()),
            ("max_parallel", self.parallel.value()),
            ("launch_interval", self.launch_delay.value()),
            ("retention_days", self.retention.value()),
        ):
            self.service.store.set_setting(key, value)
        self.banner.setText(
            "Đã lưu cài đặt. Nếu đổi cổng ADB, hãy đóng và mở lại tool để áp dụng."
        )

    def backup(self):
        try:
            self.banner.setText("Đã sao lưu: " + str(self.service.store.backup()))
        except Exception as exc:
            error(self, exc)

    def export(self):
        try:
            path = self.service.support_export()
            self.banner.setText("Đã xuất thông tin hỗ trợ: " + str(path))
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        except Exception as exc:
            error(self, exc)

    def onboarding(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Bắt đầu với TAKTIK")
        dialog.resize(620, 420)
        v = QVBoxLayout(dialog)
        title = QLabel("Kết nối điện thoại đầu tiên")
        title.setObjectName("dialogTitle")
        v.addWidget(title)
        text = QLabel(
            "1. Cắm USB, bật USB debugging và chấp nhận quyền ADB trên điện thoại.\n\n2. Bấm Làm mới ADB. Bảng hiển thị model, Android, TikTok; đổi tên, nhóm và nhãn tài khoản để đối chiếu.\n\n3. Kiểm tra TikTok đã đăng nhập bằng Xiaowei. Chọn “Chỉ lướt” với 1 video để thử trước.\n\nKhi cần thao tác trong Xiaowei, bấm Dừng / Giữ máy rồi chờ “Thủ công sẵn sàng”. Lịch chỉ chạy khi ứng dụng và PC hoạt động."
        )
        text.setWordWrap(True)
        v.addWidget(text, 1)
        v.addWidget(button("Kiểm tra kết nối (chỉ đọc)", self.service.refresh_devices))

        def finish():
            self.service.store.set_setting("onboarded", True)
            dialog.accept()

        v.addWidget(button("Vào màn hình chính", finish, True))
        self.show_dialog(dialog)

    def closeEvent(self, event):
        if self.allow_close:
            self.update_timer.stop()
            self.refresh_timer.stop()
            event.accept()
            return
        if self.service.runners or self.service.validating:
            if (
                QMessageBox.question(
                    self,
                    "Dừng và thoát",
                    f"Có {len(self.service.runners)+len(self.service.validating)} tác vụ đang hoạt động. Dừng tất cả và thoát? Kết quả có thể cần kiểm tra.",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                != QMessageBox.Yes
            ):
                event.ignore()
                return
        event.ignore()
        self.setEnabled(False)
        self.banner.setText("Đang chờ worker dừng và lưu dữ liệu…")
        self.service.shutdown()

    def finish_close(self):
        self.allow_close = True
        self.close()
