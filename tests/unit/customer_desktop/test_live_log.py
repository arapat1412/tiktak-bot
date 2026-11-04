from collections import deque, OrderedDict
import threading

import pytest

from customer_desktop import console
from customer_desktop.live_log import LiveLogPanel


@pytest.fixture(autouse=True)
def isolated_history(monkeypatch):
    monkeypatch.setattr(console, "_history", deque(maxlen=2000))
    monkeypatch.setattr(console, "_recent", OrderedDict())
    monkeypatch.setattr(console, "_sequence", 0)
    monkeypatch.setattr(console, "_sink", None)


def test_vietnamese_events_are_concise_and_skip_technical_noise():
    console.event(
        {"type": "status", "status": "connecting", "message": "Connecting..."},
        "a",
        "job",
    )
    console.event({"type": "step_metric", "category": "keystroke"}, "a", "job")
    console.event(
        {"type": "log", "level": "DEBUG", "message": "verbose XPath"}, "a", "job"
    )
    console.event({"type": "log", "message": "Config: max_videos=20"}, "a", "job")
    console.event(
        {
            "type": "video_info",
            "video": {"author": "한글", "description": "do not dump caption"},
        },
        "a",
        "job",
    )
    console.event(
        {
            "type": "stats",
            "stats": {"videos_watched": 7, "videos_liked": 2, "errors": 0},
        },
        "a",
        "job",
    )
    console.emit(
        "2026-10-29 22:00:00.000 | WARNING | module:method:42 - Failed to scroll to next video",
        "a",
        "job",
        "ENGINE",
    )
    records = console.records_after()
    assert len(records) == 4
    text = "\n".join(map(console.format_record, records))
    assert "Đang kết nối điện thoại" in text
    assert "Đang xem video của @한글" in text
    assert "đã xem: 7 · tim: 2 · lỗi: 0" in text
    assert "CẢNH BÁO  Không lướt được sang video tiếp theo" in text
    assert "module:method" not in text and "caption" not in text


def test_errors_not_downgraded_or_hidden_and_original_event_unchanged():
    event = {"type": "error", "message": "Unmapped native failure 한국어"}
    before = dict(event)
    console.event(event, "a", "job")
    console.emit(
        "2026-10-29 22:00:00 | INFO | module:1 - error detail", "a", "job", "ERROR"
    )
    records = console.records_after()
    assert event == before
    assert all(record["level"] == "ERROR" for record in records)
    assert "Unmapped native failure 한국어" == records[0]["message"]


def test_plain_stderr_exception_and_stop_reason_remain_visible():
    console.emit("RuntimeError: device disconnected", "a", "job", "ENGINE")
    console.event(
        {"type": "status", "status": "completed", "completion_reason": "feed_stuck"},
        "a",
        "job",
    )
    console.event(
        {
            "type": "status",
            "status": "running",
            "level": "WARNING",
            "message": "Lỗi cần kiểm tra",
        },
        "a",
        "job",
    )
    records = console.records_after()
    assert records[0]["level"] == "ERROR"
    assert "device disconnected" in records[0]["message"]
    assert "Không chuyển được video" in records[1]["message"]
    assert records[2]["level"] == "WARNING"
    assert "Lỗi cần kiểm tra" in records[2]["message"]


def test_history_is_bounded_thread_safe_and_returns_copies():
    def produce(serial):
        for index in range(700):
            console.emit(f"Thông báo {index}", serial)

    threads = [
        threading.Thread(target=produce, args=(str(index),)) for index in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    records = console.records_after()
    assert len(records) == 2000
    assert records[-1]["sequence"] == 2800
    assert len(console._recent) <= 512
    records[-1]["message"] = "mutation"
    assert console.records_after(2799)[0]["message"] != "mutation"


def test_panel_no_console_filters_pause_clear_and_resume(app):
    panel = LiveLogPanel()
    panel.timer.stop()
    console.emit("Tiếng Việt 한글", "a", "job1")
    console.emit("Lỗi kết nối", "b", "job2", "ERROR")
    panel.refresh()
    assert "Tiếng Việt 한글" in panel.output.toPlainText()
    panel.device_filter.setCurrentIndex(panel.device_filter.findData("a"))
    assert "Lỗi kết nối" not in panel.output.toPlainText()
    panel.errors_only.setChecked(True)
    assert panel.output.toPlainText() == ""
    panel.device_filter.setCurrentIndex(0)
    assert "Lỗi kết nối" in panel.output.toPlainText()
    panel.paused.setChecked(True)
    console.emit("Lỗi mới", "b", "job2", "ERROR")
    panel.refresh()
    assert "Lỗi mới" not in panel.output.toPlainText()
    panel.paused.setChecked(False)
    assert "Lỗi mới" in panel.output.toPlainText()
    count = len(console.records_after())
    panel.clear_button.click()
    assert panel.output.toPlainText() == ""
    assert len(console.records_after()) == count
    panel.redraw()
    assert panel.output.toPlainText() == ""
    console.emit("Lỗi sau xóa", "b", "job2", "ERROR")
    panel.refresh()
    assert "Lỗi sau xóa" in panel.output.toPlainText()
    assert "Lỗi mới" not in panel.output.toPlainText()
    panel.close()


def test_burst_view_bounded_and_manual_scroll_preserved(app):
    panel = LiveLogPanel()
    panel.timer.stop()
    panel.show()
    for index in range(3000):
        console.emit(f"Sự kiện {index}", "a")
    panel.refresh()
    app.processEvents()
    assert panel.output.document().blockCount() <= 1000
    assert "Sự kiện 2999" in panel.output.toPlainText()
    panel.auto_scroll.setChecked(False)
    panel.output.verticalScrollBar().setValue(0)
    console.emit("Sự kiện cuối", "a")
    panel.refresh()
    assert panel.output.verticalScrollBar().value() == 0
    panel.close()
