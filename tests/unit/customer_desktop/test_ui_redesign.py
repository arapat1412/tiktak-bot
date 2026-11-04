"""Customer flows use explicit selection and retain the existing task contract."""

from datetime import datetime
import json
from unittest.mock import Mock

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from customer_desktop.domain import build_browse, natural_browse_options
from customer_desktop.paths import prepare_paths
from customer_desktop.services import DesktopService
from customer_desktop.ui import TZ, BrowseDialog, MainWindow, PublishDialog


def setup(tmp_path, devices=True):
    service = DesktopService(prepare_paths(tmp_path), prepare=False)
    service.timer.stop()
    service.refresh_devices = lambda: None
    service.store.set_setting("onboarded", True)
    if devices:
        service.store.discover(
            [
                dict(serial="a", model="Máy A", connection="online", package="fixture"),
                dict(
                    serial="b", model="Máy B", connection="offline", package="fixture"
                ),
            ]
        )
    return service


def window(service):
    w = MainWindow(service)
    w.refresh_timer.stop()
    return w


def finish(w, service):
    w.allow_close = True
    w.close()
    service.store.close()


def test_selection_matches_checks_and_refresh_preserves_it(app, tmp_path):
    s = setup(tmp_path)
    w = window(s)
    assert not w.publish_button.isEnabled()
    assert not w.hold_button.isEnabled()
    w.show()
    app.processEvents()
    QTest.mouseClick(
        w.device_table.viewport(),
        Qt.LeftButton,
        pos=w.device_table.visualItemRect(w.device_table.item(0, 1)).center(),
    )
    assert w.selected_serials() == ["a"]
    assert w.publish_button.isEnabled() and w.browse_button.isEnabled()
    assert w.selection_label.text() == "Đã chọn 1 máy"
    w.refresh()
    assert w.selected_serials() == ["a"]
    w.device_table.selectRow(0)
    w.device_table.item(0, 0).setCheckState(Qt.Unchecked)
    assert not w.selected_devices()  # Highlighted row is not an invisible selection.
    assert not w.publish_button.isEnabled()
    finish(w, s)


def test_multidevice_settings_and_resource_feedback(app, tmp_path):
    s = setup(tmp_path)
    w = window(s)
    assert w.parallel.maximum() == 50 and w.parallel.value() == 1
    assert w.launch_delay.value() == 2
    w.parallel.setValue(50)
    w.launch_delay.setValue(3)
    w.save_settings()
    assert s.store.setting("max_parallel") == 50
    assert s.store.setting("launch_interval") == 3
    s.capacity = {"reason": "RAM trống thấp"}
    s.capacity_at = s.clock()
    s.capacity_changed.emit()
    assert "RAM trống thấp" in w.capacity_label.text()
    assert w.engine_label.text() == "Chờ tài nguyên"
    finish(w, s)


def test_select_all_timed_browse_submits_all_phones_for_thirty_minutes(app, tmp_path):
    s = setup(tmp_path, devices=False)
    s.store.discover(
        [
            dict(serial=f"fake-{i:02}", connection="online", package="fixture")
            for i in range(50)
        ]
    )
    w = window(s)
    w.select_all_visible(True)
    assert len(w.selected_devices()) == 50
    dialog = BrowseDialog(s, w.require_devices(), w)
    try:
        dialog.timed_run.setChecked(True)
        dialog.duration_minutes.setValue(30)
        assert "Tự chạy song song 50 máy" in dialog.preview.text()
        sent = []
        dialog.send = sent.extend
        dialog.submit()
        assert len(sent) == len({spec["serial"] for spec in sent}) == 50
        assert all(spec["payload"]["runDurationMinutes"] == 30 for spec in sent)
        assert s.store.setting("max_parallel", 1) == 1
    finally:
        dialog.reject()
        finish(w, s)


def test_worker_change_burst_coalesces_to_one_refresh(app, tmp_path):
    s = setup(tmp_path)
    w = window(s)
    fired = []
    w.update_timer.timeout.connect(lambda: fired.append(True))
    for _ in range(100):
        s.changed.emit()
    QTest.qWait(220)
    assert fired == [True]
    finish(w, s)


def test_bulk_selection_offline_hold_and_filter(app, tmp_path):
    s = setup(tmp_path)
    w = window(s)
    w.select_all_visible(True)
    assert w.selected_serials() == ["a", "b"]
    assert not w.publish_button.isEnabled()
    assert w.hold_button.isEnabled()
    w.select_all_visible(False)
    assert not w.selected_devices()
    s.store.hold("a", True)
    w.refresh()
    w.check_clicked_device(0, 1)
    assert w.release_button.isEnabled()
    s.stop_serial = Mock()
    w.hold_button.click()
    s.stop_serial.assert_called_once_with("a")
    w.search.setText("không có máy này")
    assert not w.device_empty.isHidden()
    assert w.device_table.isHidden()
    assert not w.publish_button.isEnabled()
    assert not w.select_all.isEnabled()
    w.search.clear()
    assert w.device_empty.isHidden()
    assert not w.selected_serials()
    finish(w, s)


def test_empty_states_and_job_actions_follow_current_state(app, tmp_path):
    s = setup(tmp_path, devices=False)
    w = window(s)
    assert not w.device_empty.isHidden()
    assert not w.queue_empty.isHidden()
    assert not w.history_empty.isHidden()
    assert all(not b.isEnabled() for b in w.queue_buttons + w.history_buttons)
    s.store.discover([dict(serial="a", connection="online", package="fixture")])
    jid = s.store.enqueue(
        [dict(serial="a", kind="browse", payload=build_browse("a", {}))], "ui-fixture"
    )[0]
    w.refresh()
    w.queue_table.selectRow(0)
    assert [b.isEnabled() for b in w.queue_buttons] == [True, False, True, False]
    s.store.db.execute("UPDATE jobs SET state='running' WHERE id=?", (jid,))
    s.store.db.commit()
    w.refresh()
    assert [b.isEnabled() for b in w.queue_buttons] == [True, False, False, True]
    s.store.db.execute("UPDATE jobs SET state='needs_review' WHERE id=?", (jid,))
    s.store.db.commit()
    w.refresh()
    assert not w.queue_empty.isHidden()
    assert w.history_empty.isHidden()
    assert w.history_table.item(0, 3).text() == "Cần kiểm tra"
    w.history_table.selectRow(0)
    assert all(b.isEnabled() for b in w.history_buttons)
    assert json.loads(s.store.job(jid)["snapshot"])["likeProbability"] == 0
    finish(w, s)


def test_browse_action_offers_one_natural_mode_with_optional_comments(app, tmp_path):
    s = setup(tmp_path)
    w = window(s)
    assert w.browse_button.text() == "Lướt tự nhiên"
    d = BrowseDialog(s, s.store.devices()[:1], w)
    d.show()
    app.processEvents()
    assert d.comments.isVisible()
    assert d.values() == natural_browse_options()
    assert d.create.isEnabled()
    d.comments.setPlainText("Nội dung thử\n한글")
    assert d.values()["commentTexts"] == ["Nội dung thử", "한글"]
    assert "Tim 25%" in d.preview.text()
    assert "Bình luận 8%" in d.preview.text()
    d.comments.clear()
    assert d.values()["commentProbability"] == 0
    assert "Không bình luận" in d.preview.text()
    assert d.create.isEnabled()
    d.reject()
    finish(w, s)


def test_publish_needs_media_rows_and_maps_caption_tags_schedule(app, tmp_path):
    s = setup(tmp_path)
    d = PublishDialog(s, s.store.devices(), None)
    assert not d.create.isEnabled()
    d.files = ["C:/fixture/a.mp4", "C:/fixture/b.mp4"]
    d.rebuild()
    assert d.create.isEnabled()
    d.pending = True
    d.update_publish_preview()
    assert not d.create.isEnabled()
    d.pending = False
    d.mode.setCurrentIndex(1)
    assert d.rows.rowCount() == 4
    assert d.rows.columnCount() == 5
    d.rows.item(1, 2).setText("Nội dung riêng 한글")
    d.rows.item(2, 3).setText("#hai #ba")
    d.rows.item(0, 4).setText("2030-01-02 09:30")
    d.send = Mock()
    d.submit()
    specs = d.send.call_args.args[0]
    assert [spec["serial"] for spec in specs] == ["a", "b", "a", "b"]
    assert specs[1]["payload"]["caption"] == "Nội dung riêng 한글"
    assert specs[2]["payload"]["hashtags"] == ["#hai", "#ba"]
    assert specs[0]["run_at"] == datetime(2030, 1, 2, 9, 30, tzinfo=TZ).timestamp()
    assert specs[1]["run_at"] is None
    assert all(spec["payload"]["deviceId"] == spec["serial"] for spec in specs)
    assert all("botUsername" not in spec["payload"] for spec in specs)
    d.reject()
    s.store.close()


def test_publish_ignores_saved_device_account_and_retry_username(app, tmp_path):
    s = setup(tmp_path)
    s.store.save_device("a", "Máy A", "", "tai_khoan_da_luu")
    s.store.save_device("b", "Máy B", "", "")
    d = PublishDialog(
        s,
        s.store.devices(),
        None,
        initial=dict(
            localPath="C:/fixture/cu.mp4",
            caption="Bài cũ",
            hashtags=["#cu"],
            botUsername="tai_khoan_cu",
        ),
    )
    assert d.rows.columnCount() == 5
    assert d.rows.horizontalHeaderItem(2).text() == "Nội dung"
    assert not hasattr(d, "account_check")
    assert "tài khoản TikTok đang đăng nhập" in d.summary.text()
    cells = [
        d.rows.item(r, c).text()
        for r in range(d.rows.rowCount())
        for c in range(d.rows.columnCount())
    ]
    assert all("tai_khoan" not in cell for cell in cells)
    d.send = Mock()
    d.submit()
    specs = d.send.call_args.args[0]
    assert len(specs) == 1
    assert specs[0]["serial"] == "a"
    assert specs[0]["payload"]["caption"] == "Bài cũ"
    assert specs[0]["payload"]["hashtags"] == ["#cu"]
    assert "botUsername" not in specs[0]["payload"]
    d.reject()
    s.store.close()


def test_retry_review_keeps_confirmation_and_opens_current_natural_mode(
    app, tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    s = setup(tmp_path)
    old = build_browse(
        "a",
        dict(
            maxVideos=7,
            likeProbability=90,
            maxLikesPerSession=20,
            commentProbability=50,
            maxCommentsPerSession=5,
            commentTexts=["Câu cũ 한글"],
        ),
    )
    jid = s.store.enqueue(
        [dict(serial="a", kind="browse", payload=old)], "legacy-review"
    )[0]
    s.store.db.execute("UPDATE jobs SET state='needs_review' WHERE id=?", (jid,))
    s.store.db.commit()
    snapshot = s.store.job(jid)["snapshot"]
    w = window(s)
    w.history_table.selectRow(0)
    w.show_dialog = Mock()
    question = Mock(return_value=QMessageBox.No)
    monkeypatch.setattr(QMessageBox, "question", question)
    w.retry_review()
    w.show_dialog.assert_not_called()
    question.return_value = QMessageBox.Yes
    w.retry_review()
    assert question.call_count == 2
    d = w.show_dialog.call_args.args[0]
    assert d.values() == natural_browse_options(7, ["Câu cũ 한글"])
    assert not d.previous_note.isHidden()
    assert s.store.job(jid)["snapshot"] == snapshot
    assert len(s.store.jobs()) == 1  # Opening the form never submits a new attempt.
    d.reject()
    finish(w, s)
