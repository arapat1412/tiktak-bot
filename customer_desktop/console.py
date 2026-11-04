"""Bounded live console mirror; original attempt files remain the diagnostics source."""

import atexit
import codecs
from collections import deque, OrderedDict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import os
import queue
import re
import sys
import threading
import time

_ANSI = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_TZ = timezone(timedelta(hours=7))
_sink = None
_history = deque(maxlen=2000)
_history_lock = threading.RLock()
_sequence = 0
_recent = OrderedDict()

LEVELS = {
    "INFO": "THÔNG TIN",
    "SUCCESS": "HOÀN TẤT",
    "WARNING": "CẢNH BÁO",
    "ERROR": "LỖI",
    "CRITICAL": "LỖI",
    "ENGINE": "THÔNG TIN",
}
STATUSES = {
    "connecting": "Đang kết nối điện thoại",
    "verifying_account": "Đang kiểm tra tài khoản",
    "navigating": "Đang mở màn hình đăng",
    "selecting": "Đang chọn video / ảnh",
    "filling": "Đang nhập nội dung",
    "publishing": "Đang đăng, chờ TikTok xác nhận",
    "running": "Đang chạy",
    "completed": "Engine báo đã hoàn tất, đang kiểm tra kết quả",
    "success": "Engine báo thành công, đang kiểm tra kết quả",
    "stopping": "Đang dừng",
    "error": "Có lỗi",
    "succeeded": "Hoàn tất",
    "failed": "Thất bại",
    "needs_review": "Cần kiểm tra",
    "cancelled": "Đã hủy",
}


def records_after(sequence=0):
    """Copied, bounded history for polling UI; producers never call Qt."""
    with _history_lock:
        return [dict(record) for record in _history if record["sequence"] > sequence]


def format_record(record):
    device = "Ứng dụng" if record["serial"] == "APP" else record["serial"]
    job = f" · {record['job'][:8]}" if record["job"] != "--------" else ""
    level = LEVELS.get(record["level"], "THÔNG TIN")
    return f"{record['time']}  [{device}{job}]  {level}  {record['message']}"


@lru_cache(maxsize=512)
def readable(message):
    """Translate known engine diagnostics without changing their recorded originals."""
    message = clean(message)
    match = re.match(
        r"^\d{4}-\d\d-\d\d.*?\|\s*(TRACE|DEBUG|INFO|WARNING|ERROR|CRITICAL|SUCCESS)\s*\|.*? - (.*)$",
        message,
    )
    level = match[1] if match else None
    if match:
        message = match[2]
    elif re.match(r"^(?:[\w.]+(?:Error|Exception)|ERROR|CRITICAL):", message):
        level = "ERROR"
    elif re.match(r"^(?:[\w.]*Warning|WARNING):", message):
        level = "WARNING"
    message = re.sub(r"^[\s\U0001f000-\U0001ffff\u2300-\u27ff\ufe0f]+", "", message)
    translations = {
        "Starting For You workflow": "Bắt đầu lướt tự nhiên",
        "Skipping advertisement": "Bỏ qua quảng cáo",
        "Skipping a LIVE preview": "Bỏ qua video phát trực tiếp",
        "Session limits reached": "Đã đạt giới hạn phiên",
        "Failed to navigate to For You feed": "Không mở được trang Dành cho bạn",
        "Failed to scroll to next video": "Không lướt được sang video tiếp theo",
        "Too many errors, stopping": "Có quá nhiều lỗi, đang dừng",
        "System popup was blocking, closed it": "Đã đóng thông báo che màn hình",
        "Navigating to Home": "Đang mở trang chủ",
        "Navigating to Profile": "Đang mở hồ sơ",
        "Bắt đầu browse": "Bắt đầu lướt tự nhiên",
        "Bắt đầu publish": "Bắt đầu đăng nội dung",
    }
    message = translations.get(message, message)
    for pattern, replacement in (
        (r"^Taking a break for ([\d.]+)s$", r"Nghỉ \1 giây"),
        (r"^Liked video by (.+)$", r"Đã thả tim video của \1"),
        (r"^Followed (.+)$", r"Đã theo dõi \1"),
        (r"^Pushing file to device:.*$", "Đang chuyển video / ảnh vào điện thoại"),
        (r"^Workflow error: (.*)$", r"Lỗi khi chạy: \1"),
        (
            r"^Interaction verification failed: (.*)$",
            r"Không xác minh được tương tác: \1",
        ),
        (r"^Pause callback error: (.*)$", r"Lỗi khi nghỉ giữa phiên: \1"),
    ):
        message = re.sub(pattern, replacement, message)
    for status, label in STATUSES.items():
        if message.startswith(status + ":"):
            message = label + message[len(status) :]
            break
    return message, level


def clean(value):
    return _CONTROL.sub("", _ANSI.sub("", str(value)[:8192])).strip()[:4096]


class ConsoleSink:
    def __init__(self, stream, capacity=1024):
        self.stream = stream
        self.queue = queue.Queue(maxsize=capacity)
        self.closed = threading.Event()
        self.dropped = 0
        self.thread = threading.Thread(
            target=self._write, name="live-console", daemon=True
        )
        self.thread.start()

    def put(self, line):
        if self.closed.is_set():
            return
        try:
            self.queue.put_nowait(line[:8192])
        except queue.Full:
            self.dropped += 1

    def _write(self):
        while not self.closed.is_set() or not self.queue.empty():
            try:
                line = self.queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                self.stream.write(line + "\n")
                self.stream.flush()
            except Exception:
                # A console closed by Windows cannot break a worker or the Qt loop.
                self.closed.set()
                return

    def close(self, timeout=1):
        self.closed.set()
        self.thread.join(timeout=timeout)


def initialize(stream=None):
    global _sink
    if _sink is not None:
        return
    for output in (sys.stdout, sys.stderr):
        try:
            output.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass
    stream = stream if stream is not None else (sys.stdout or sys.stderr)
    if stream is None:
        return
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW("TAKTIK - Log trực tiếp")
        except Exception:
            pass
    _sink = ConsoleSink(stream)
    atexit.register(shutdown)


def shutdown():
    global _sink
    sink, _sink = _sink, None
    if sink is not None:
        sink.close()


def emit(message, serial="APP", job="--------", level="INFO"):
    global _sequence
    message, detected_level = readable(clean(message))
    level = clean(level)
    level = (
        level if level.upper() in ("ERROR", "CRITICAL") else detected_level or level
    ).upper()
    level = {"WARN": "WARNING", "FATAL": "CRITICAL", "ENGINE": "INFO"}.get(level, level)
    if level in ("TRACE", "DEBUG") or not message:
        return
    # Large technical dumps remain in the original files, never in the live view.
    if level not in ("ERROR", "CRITICAL", "WARNING") and (
        message.startswith(("{", "[", "Config:", "Traceback (", 'File "'))
        or " completed: {" in message
        or "xpath=" in message.lower()
    ):
        return
    message = " ".join(message.split())[:600]
    key = (clean(serial)[:64], clean(job)[:8], level, message)
    with _history_lock:
        now = time.monotonic()
        if now - _recent.get(key, -10) < 1:
            return
        _recent[key] = now
        _recent.move_to_end(key)
        if len(_recent) > 512:
            _recent.popitem(last=False)
        _sequence += 1
        record = dict(
            sequence=_sequence,
            time=f"{datetime.now(_TZ):%H:%M:%S}",
            serial=key[0],
            job=key[1],
            level=level,
            message=message,
        )
        _history.append(record)
    sink = _sink
    if sink is not None:
        sink.put(format_record(record))


def event(item, serial, job):
    kind = clean(item.get("type", "event"))
    level = item.get("level") or (
        "ERROR" if kind in ("error", "protocol_error") else "INFO"
    )
    message = item.get("message") or item.get("error")
    if kind in ("step_metric", "config", "account", "profile_captured"):
        return
    if kind == "upload_result":
        success = item.get("success") is True
        level = "SUCCESS" if success else "ERROR"
        message = message or (item.get("error_type") if not success else None)
        message = (
            "Engine báo đăng bài thành công" if success else "Đăng bài chưa thành công"
        ) + (f": {message}" if message else "")
    elif kind == "status":
        status = clean(item.get("status", ""))
        label = STATUSES.get(status, "Cập nhật trạng thái")
        # Structured status is clearer than duplicate engine summaries/config dumps.
        message = (
            label
            if status in STATUSES and status != "error"
            else f"{label}: {message or status}"
        )
        if status == "error":
            level = "ERROR"
        if clean(item.get("level", "")).upper() in (
            "WARN",
            "WARNING",
            "ERROR",
            "CRITICAL",
        ):
            detail = item.get("message") or item.get("error")
            if detail:
                message = f"{label}: {detail}"
        reason = clean(item.get("completion_reason") or "")
        if reason:
            reasons = {
                "feed_stuck": "Không chuyển được video",
                "duration_limit": "Đã đủ thời gian lướt đã cài đặt",
                "interaction_unconfirmed": "Chưa xác minh được tương tác",
                "customer_stop": "Người dùng yêu cầu dừng",
                "action_blocked": "TikTok đang hạn chế tương tác",
            }
            message += ": " + reasons.get(reason, clean(reason))
    elif kind in ("stats", "video_stats", "video_result"):
        stats = item.get("stats") if isinstance(item.get("stats"), dict) else item
        labels = {
            "videos_watched": "đã xem",
            "videos_liked": "tim",
            "users_followed": "theo dõi",
            "videos_commented": "bình luận",
            "videos_skipped": "bỏ qua",
            "errors": "lỗi",
        }
        summary = [
            f"{label}: {stats[key]}"
            for key, label in labels.items()
            if isinstance(stats.get(key), (int, float))
        ]
        message = "Tiến độ · " + " · ".join(summary) if summary else None
    elif kind == "video_info":
        video = item.get("video") if isinstance(item.get("video"), dict) else item
        message = "Đang xem video" + (
            f" của @{clean(video['author']).lstrip('@')[:80]}"
            if video.get("author")
            else ""
        )
    elif kind == "action":
        label = {
            "like": "Đã thả tim",
            "follow": "Đã theo dõi",
            "comment": "Đã bình luận",
        }.get(clean(item.get("action")))
        message = (
            label + (f" · {clean(item['target'])[:80]}" if item.get("target") else "")
            if label
            else None
        )
    elif kind == "pause":
        message = f"Nghỉ {clean(item.get('duration', ''))[:12]} giây"
    elif kind not in ("log", "error", "protocol_error"):
        # Unknown diagnostic/telemetry events do not become empty technical labels.
        return
    if not message:
        return
    emit(message, serial, job, level)


class StderrLines:
    """Incremental UTF-8 with bounded partial lines, independent of pipe chunk boundaries."""

    def __init__(self, write):
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.pending = ""
        self.write = write

    def feed(self, data, final=False):
        text = self.pending + self.decoder.decode(data, final=final)
        lines = text.split("\n")
        self.pending = lines.pop()
        for line in lines:
            self.write(clean(line))
        while len(self.pending) > 4096:
            self.write(clean(self.pending[:4096]))
            self.pending = self.pending[4096:]
        if final and self.pending:
            self.write(clean(self.pending))
            self.pending = ""
