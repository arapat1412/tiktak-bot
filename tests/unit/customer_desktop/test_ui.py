from copy import deepcopy
from datetime import datetime
from unittest.mock import Mock

from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import QMessageBox

from customer_desktop.domain import build_browse, natural_browse_options
from customer_desktop.paths import prepare_paths
from customer_desktop.services import DesktopService
from customer_desktop.ui import (
    BrowseDialog,
    MainWindow,
    PublishDialog,
    ScheduleWidget,
    TZ,
)


def setup_service(tmp_path):
    service = DesktopService(prepare_paths(tmp_path), prepare=False)
    service.timer.stop()
    service.store.discover(
        [
            dict(serial=s, model="Máy " + s, connection="online", package="fixture")
            for s in ("a", "b")
        ]
    )
    return service


def test_browse_is_one_natural_mode_with_optional_comments(app, tmp_path):
    s = setup_service(tmp_path)
    d = BrowseDialog(s, s.store.devices(), None)
    assert not hasattr(d, "preset")
    assert not hasattr(d, "presets")
    assert not d.advanced_section.isExpanded()
    assert (d.videos.minimum(), d.videos.maximum()) == (1, 10000)
    assert d.videos.value() == 20
    d.show()
    app.processEvents()
    assert d.comments.isVisible()
    options = d.values()
    assert options == natural_browse_options()
    assert "deviceId" not in options
    assert options["browseProfile"] == "natural"
    assert (options["commentProbability"], options["maxCommentsPerSession"]) == (0, 0)
    assert (options["likeProbability"], options["maxLikesPerSession"]) == (25, 5)
    assert (options["followProbability"], options["maxFollowsPerSession"]) == (5, 1)
    preview = d.preview.text()
    assert "20 video/máy" in preview
    assert "Tim 25% (tối đa 5/phiên)" in preview
    assert "Theo dõi 5% (tối đa 1/phiên)" in preview
    assert "Không bình luận" in preview
    assert "Chạy ngay" in preview
    d.reject()
    s.store.close()


def test_browse_comments_are_optional_unicode_and_deduped(app, tmp_path):
    s = setup_service(tmp_path)
    d = BrowseDialog(s, s.store.devices(), None)
    d.comments.setPlainText("Xin chào\n\n한글\nXin chào\n  안녕하세요  ")
    options = d.values()
    assert options["commentTexts"] == ["Xin chào", "한글", "안녕하세요"]
    assert options["commentProbability"] == 8
    assert options["maxCommentsPerSession"] == 2
    assert "Bình luận 8% (tối đa 2, 3 câu, không lặp trong phiên)" in d.preview.text()
    d.comments.setPlainText("Chỉ một câu")
    options = d.values()
    assert options["commentTexts"] == ["Chỉ một câu"]
    assert options["maxCommentsPerSession"] == 1
    d.comments.clear()
    options = d.values()
    assert (options["commentProbability"], options["maxCommentsPerSession"]) == (0, 0)
    assert "Không bình luận" in d.preview.text()
    d.reject()
    s.store.close()


def test_saved_presets_do_not_change_the_single_mode(app, tmp_path):
    s = setup_service(tmp_path)
    s.store.save_preset(
        "Mẫu cũ",
        {
            "browseProfile": "standard",
            "maxVideos": 3,
            "likeProbability": 90,
            "maxLikesPerSession": 9,
            "commentProbability": 50,
            "maxCommentsPerSession": 7,
            "commentTexts": ["Nội dung cũ"],
        },
    )
    d = BrowseDialog(s, s.store.devices(), None)
    assert d.videos.value() == 20
    assert d.comments.toPlainText() == ""
    assert d.values() == natural_browse_options()
    d.reject()
    s.store.close()


def test_load_previous_normalizes_legacy_payload_without_mutation(app, tmp_path):
    s = setup_service(tmp_path)
    d = BrowseDialog(s, s.store.devices(), None)
    legacy = {
        "deviceId": "a",
        "workflowType": "for_you",
        "browseProfile": "standard",
        "maxVideos": 7,
        "minWatchTime": 1,
        "maxWatchTime": 3,
        "likeProbability": 90,
        "maxLikesPerSession": 50,
        "followProbability": 0,
        "maxFollowsPerSession": 0,
        "commentProbability": 40,
        "maxCommentsPerSession": 9,
        "commentTexts": ["Chào", "", "Chào", "한글"],
    }
    original = deepcopy(legacy)
    returned = d.load_previous(legacy)
    assert legacy == original
    assert d.videos.value() == 7
    assert d.comments.toPlainText() == "Chào\n한글"
    expected = natural_browse_options(7, ["Chào", "", "Chào", "한글"])
    assert returned == expected
    assert d.values() == expected
    assert expected["browseProfile"] == "natural"
    assert (expected["likeProbability"], expected["maxLikesPerSession"]) == (25, 5)
    assert (expected["commentProbability"], expected["maxCommentsPerSession"]) == (8, 2)
    note = d.previous_note.text()
    assert "chính sách Lướt tự nhiên hiện tại" in note
    assert "không chạy lại cấu hình cũ" in note
    d.reject()
    s.store.close()


def test_browse_submit_uses_factory_for_each_serial_and_schedule(app, tmp_path):
    s = setup_service(tmp_path)
    d = BrowseDialog(s, s.store.devices(), None)
    d.videos.setValue(12)
    d.comments.setPlainText("Chào\n한글")
    d.schedule.enabled.setChecked(True)
    d.schedule.date.setDateTime(
        QDateTime.fromString("2030-01-02 09:30", "yyyy-MM-dd HH:mm")
    )
    assert "Hẹn 02/01 09:30 (UTC+7)" in d.preview.text()
    run_at = datetime(2030, 1, 2, 9, 30, tzinfo=TZ).timestamp()
    expected = natural_browse_options(12, ["Chào", "한글"])
    d.send = Mock()
    d.submit()
    specs = d.send.call_args.args[0]
    assert [spec["serial"] for spec in specs] == ["a", "b"]
    assert all(spec["kind"] == "browse" for spec in specs)
    assert all(spec["run_at"] == run_at for spec in specs)
    assert [spec["payload"] for spec in specs] == [
        build_browse("a", expected),
        build_browse("b", expected),
    ]
    d.reject()
    s.store.close()


def test_retry_review_browse_prefills_only_previous_choices(app, tmp_path, monkeypatch):
    s = setup_service(tmp_path)
    s.refresh_devices = lambda: None
    legacy = build_browse(
        "a",
        dict(
            browseProfile="standard",
            maxVideos=9,
            likeProbability=90,
            maxLikesPerSession=20,
            commentTexts=["Chào", "한글"],
        ),
    )
    jid = s.store.enqueue([dict(serial="a", kind="browse", payload=legacy)], "retry")[0]
    s.store.db.execute("UPDATE jobs SET state='needs_review' WHERE id=?", (jid,))
    s.store.db.commit()
    s.manual_ready = lambda serial: True

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes
    )
    w = MainWindow(s)
    w.refresh_timer.stop()
    w.refresh()
    w.history_table.selectRow(0)
    w.retry_review()
    d = w.dialogs[-1]
    assert isinstance(d, BrowseDialog)
    assert d.videos.value() == 9
    assert d.comments.toPlainText() == "Chào\n한글"
    assert d.values() == natural_browse_options(9, ["Chào", "한글"])
    assert "chính sách Lướt tự nhiên hiện tại" in d.previous_note.text()
    d.reject()
    w.allow_close = True
    w.close()
    s.store.close()


def test_publish_allocation_is_visible_and_explicit(app, tmp_path):
    s = setup_service(tmp_path)
    d = PublishDialog(s, s.store.devices(), None)
    d.files = ["C:/fixtures/one.mp4", "C:/fixtures/two.mp4"]
    d.rebuild()
    assert d.rows.rowCount() == 2
    assert [d.rows.item(r, 0).data(256) for r in range(2)] == ["a", "b"]
    d.mode.setCurrentIndex(1)
    assert d.rows.rowCount() == 4
    assert [d.rows.item(r, 0).data(256) for r in range(4)] == ["a", "b", "a", "b"]
    d.caption.setPlainText("Chào\n한글")
    d.apply_defaults()
    assert all(d.rows.item(r, 2).text() == "Chào\n한글" for r in range(4))
    d.reject()
    s.store.close()


def test_schedule_uses_bangkok_not_host_timezone(app):
    w = ScheduleWidget()
    w.enabled.setChecked(True)
    w.date.setDateTime(QDateTime.fromString("2030-01-02 09:30", "yyyy-MM-dd HH:mm"))
    assert w.value() == datetime(2030, 1, 2, 9, 30, tzinfo=TZ).timestamp()
