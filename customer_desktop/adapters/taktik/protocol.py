"""Bounded byte-oriented JSON-lines decoding and conservative result classification."""

import json


class LineDecoder:
    def __init__(self, max_line=256 * 1024):
        self.buffer = bytearray()
        self.max_line = max_line
        self.discarding = False

    def feed(self, chunk, final=False):
        events = []
        # Split before decoding: multibyte UTF-8 stays intact across reads.
        for part in chunk.splitlines(keepends=True):
            ended = part.endswith(b"\n")
            if self.discarding:
                if ended:
                    self.discarding = False
                continue
            if len(self.buffer) + len(part) > self.max_line:
                self.buffer.clear()
                self.discarding = not ended
                events.append(
                    {"type": "protocol_error", "message": "Dòng sự kiện vượt giới hạn."}
                )
                continue
            self.buffer.extend(part)
            if ended:
                events.extend(self._line())
        if final and self.buffer:
            events.extend(self._line())
        return events

    def _line(self):
        raw = bytes(self.buffer).strip()
        self.buffer.clear()
        if not raw:
            return []
        try:
            value = json.loads(raw.decode("utf-8"))
            if isinstance(value, dict):
                return [value]
        except (ValueError, UnicodeError):
            pass
        return [{"type": "raw", "message": raw.decode("utf-8", errors="replace")}]


class ResultTracker:
    def __init__(self, kind):
        self.kind = kind
        self.stats = {}
        self.error = False
        self.completed = False
        self.final_video = False
        self.upload = []
        self.reason = ""
        self.expected_videos = 1
        self.expected_duration_minutes = 0
        self.failure_message = ""

    def observe(self, e):
        kind = e.get("type")
        if kind in ("error", "protocol_error") or (
            kind == "status" and e.get("status") == "error"
        ):
            self.error = True
            words = str(e.get("error") or e.get("message") or "").lower()
            if e.get("error_code") == "CUSTOMER_LICENSE_INVALID":
                self.failure_message = str(
                    e.get("error")
                    or "License không còn hợp lệ. Hãy kích hoạt hoặc gia hạn."
                )
            elif e.get("error_code") == "CUSTOMER_KEYBOARD_MISSING":
                self.failure_message = "Điện thoại thiếu bàn phím Taktik / ADB tương thích để nhập nội dung."
            elif "notification obscures" in words:
                self.failure_message = "Thông báo nổi đang che TikTok. Đóng thông báo trên điện thoại rồi kiểm tra lại."
            elif "account differs" in words:
                self.failure_message = "Tài khoản đang mở không khớp tài khoản dự kiến. Chưa đăng nội dung."
            elif "screen cannot be read" in words:
                self.failure_message = (
                    "Không đọc được màn hình TikTok; đã dừng để kiểm tra."
                )
        if kind == "status" and e.get("status") == "completed":
            self.completed = True
            self.reason = e.get("completion_reason") or self.reason
        if kind == "upload_result":
            self.upload.append(e.get("success"))
            messages = {
                "gallery_not_opened": "Không nhận diện được thư viện TikTok. Kiểm tra phiên bản ứng dụng.",
                "caption_fill_failed": "Không nhập và đọc lại được caption; chưa bấm Đăng. Kiểm tra bàn phím trên điện thoại.",
                "sound_not_removed": "Chưa gỡ được nhạc TikTok tự gắn; chưa đăng.",
                "publish_not_committed": "Chưa xác minh được bài đăng. Kiểm tra trên TikTok trước khi tạo tác vụ mới.",
                "action_blocked": "TikTok đang giới hạn thao tác. Giữ máy và xử lý thủ công.",
            }
            if e.get("success") is not True:
                self.error = True
                self.failure_message = messages.get(
                    e.get("error_type"), self.failure_message
                )
        if kind in ("stats", "video_result") and isinstance(e.get("stats"), dict):
            # Only engine-confirmed counters, never infer comment counts from clicks.
            self.stats.update(
                {
                    k: v
                    for k, v in e["stats"].items()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)
                }
            )
            self.reason = e["stats"].get("completion_reason") or self.reason
            if kind == "video_result":
                self.final_video = True
        if self.reason == "interaction_unconfirmed":
            self.failure_message = "Chưa xác nhận được tương tác trên TikTok. Kiểm tra điện thoại; không tự gửi lại."

    def finish(self, exit_code, stopped=False):
        if stopped:
            return (
                "needs_review",
                "Đã dừng. Đối chiếu điện thoại trước khi tạo tác vụ mới.",
            )
        timed_complete = (
            self.expected_duration_minutes > 0 and self.reason == "duration_limit"
        )
        if (
            self.error
            or self.stats.get("errors", 0)
            or (self.reason and not timed_complete)
        ):
            return (
                "needs_review",
                self.failure_message
                or "Engine báo lỗi hoặc kết thúc sớm; xem chi tiết và kiểm tra điện thoại.",
            )
        if exit_code != 0:
            return "needs_review", "Engine kết thúc bất thường; không tự chạy lại."
        if self.kind == "publish":
            if self.upload and all(v is True for v in self.upload):
                return (
                    "succeeded",
                    "Engine xác nhận đăng xong. Kiểm tra bài đăng trong TikTok.",
                )
        elif (
            self.completed
            and self.final_video
            and (
                timed_complete
                or (
                    not self.expected_duration_minutes
                    and self.stats.get("videos_watched", 0) >= self.expected_videos
                )
            )
        ):
            return "succeeded", (
                "Đã chạy đủ thời gian lướt đã cài đặt."
                if timed_complete
                else "Engine xác nhận hoàn tất phiên."
            )
        return (
            "needs_review",
            "Thiếu hoặc mâu thuẫn kết quả cuối; cần kiểm tra, không tự chạy lại.",
        )
