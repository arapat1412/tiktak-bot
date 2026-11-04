import io
from pathlib import Path
import sys
import threading
import time
import uuid

import pytest
from PySide6.QtTest import QTest

from customer_desktop import console
from customer_desktop.paths import prepare_paths
from customer_desktop.runner import Runner


@pytest.fixture(autouse=True)
def reset_console():
    console.shutdown()
    yield
    console.shutdown()


def test_event_context_unicode_and_errors(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(console, "_sink", console.ConsoleSink(stream))
    console.event({"type": "log", "message": "Xin chào 한글"}, "PHONE-1", "abcdefgh123")
    console.event(
        {"type": "error", "error": "Không gửi được"}, "PHONE-1", "abcdefgh123"
    )
    console.event({"type": "status", "status": "completed"}, "PHONE-1", "abcdefgh123")
    console.event(
        {"type": "upload_result", "success": False, "message": "Chưa đăng được"},
        "PHONE-1",
        "abcdefgh123",
    )
    console.shutdown()
    output = stream.getvalue()
    assert "[PHONE-1 · abcdefgh]  THÔNG TIN  Xin chào 한글" in output
    assert "LỖI  Không gửi được" in output
    assert "Engine báo đã hoàn tất" in output
    assert "LỖI  Đăng bài chưa thành công: Chưa đăng được" in output


def test_split_utf8_stderr_and_final_partial_line():
    lines = []
    decoder = console.StderrLines(lines.append)
    raw = "Tiếng Việt 한글\nDòng cuối 한국어".encode()
    for byte in raw:
        decoder.feed(bytes([byte]))
    assert lines == ["Tiếng Việt 한글"]
    decoder.feed(b"", final=True)
    assert lines == ["Tiếng Việt 한글", "Dòng cuối 한국어"]


def test_unterminated_lines_and_controls_are_bounded():
    lines = []
    decoder = console.StderrLines(lines.append)
    decoder.feed(b"x" * 30000)
    assert len(decoder.pending) <= 4096
    decoder.feed(b"", final=True)
    assert all(len(line) <= 4096 for line in lines)
    assert sum(map(len, lines)) == 30000
    assert console.clean("\x1b[31mError\x1b[0m\x00") == "Error"


def test_slow_console_never_blocks_producer_or_shutdown():
    entered, release = threading.Event(), threading.Event()

    class SlowStream:
        def write(self, text):
            entered.set()
            release.wait(3)

        def flush(self):
            pass

    sink = console.ConsoleSink(SlowStream(), capacity=2)
    try:
        sink.put("block writer")
        assert entered.wait(1)
        started = time.monotonic()
        for _ in range(5000):
            sink.put("burst")
        sink.close(timeout=0.01)
        assert time.monotonic() - started < 1
        assert sink.queue.qsize() <= 2 and sink.dropped > 0
    finally:
        release.set()
        sink.close()


def test_closed_console_does_not_raise():
    class BrokenStream:
        def write(self, text):
            raise OSError("closed console")

    sink = console.ConsoleSink(BrokenStream())
    sink.put("first")
    assert sink.closed.wait(1)
    sink.put("second")
    sink.close()


def test_real_worker_mirrors_console_and_preserves_result(app, tmp_path, monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(console, "_sink", console.ConsoleSink(stream))
    root = prepare_paths(tmp_path)
    job = dict(id=uuid.uuid4().hex, serial="fixture", kind="publish", snapshot="{}")
    aid = uuid.uuid4().hex
    worker = Path(__file__).with_name("fake_worker.py")
    wrapper = tmp_path / "console_worker.py"
    stderr_text = "Lỗi thử 한국어\nDòng cuối không xuống dòng"
    wrapper.write_text(
        "import runpy,sys,os\n"
        "sys.argv = [sys.argv[0], 'success']\n"
        f"runpy.run_path({str(worker)!r}, run_name='__main__')\n"
        f"raw = {stderr_text!r}.encode('utf-8')\n"
        "for byte in raw: os.write(2, bytes([byte]))\n",
        encoding="utf-8",
    )
    runner = Runner(
        root,
        job,
        aid,
        root / "logs" / job["id"] / aid,
        "adb",
        command=(sys.executable, ["-u", str(wrapper)]),
    )
    results = []
    runner.done.connect(lambda *args: results.append(args))
    runner.start()
    end = time.monotonic() + 8
    while not results and time.monotonic() < end:
        app.processEvents()
        QTest.qWait(10)
    assert results and results[0][0] == "succeeded"
    console.shutdown()
    output = stream.getvalue()
    assert "Bắt đầu đăng nội dung" in output and "Xin chào 한글" in output
    assert "Hoàn tất" in output
    assert "Lỗi thử 한국어" in output and "Dòng cuối không xuống dòng" in output
    assert b"Xin ch" in (runner.directory / "stdout.jsonl").read_bytes()
    assert (runner.directory / "stderr.log").read_bytes() == stderr_text.encode("utf-8")
