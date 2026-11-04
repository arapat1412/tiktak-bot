"""Validated, explicit camelCase engine snapshots."""

import math
from pathlib import Path

ACTIVE_STATES = ("validating", "starting", "running", "verifying", "stopping")
TERMINAL_STATES = ("succeeded", "failed", "needs_review", "cancelled")
STATE_LABELS = {
    "draft": "Bản nháp",
    "queued": "Đang chờ",
    "scheduled": "Đã đặt lịch",
    "overdue": "Lịch quá hạn",
    "validating": "Đang kiểm tra",
    "starting": "Đang khởi chạy",
    "running": "Đang chạy",
    "verifying": "Đang xác minh",
    "stopping": "Đang dừng",
    "succeeded": "Engine xác nhận hoàn tất",
    "failed": "Thất bại",
    "needs_review": "Cần kiểm tra",
    "cancelled": "Đã hủy",
    "online": "Đã kết nối",
    "offline": "Mất kết nối",
    "unauthorized": "Chưa cấp quyền ADB",
}


def number(value, label, low, high, integer=False):
    try:
        n = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"{label}: cần nhập số.") from None
    if not math.isfinite(n) or not low <= n <= high or (integer and n != int(n)):
        raise ValueError(f"{label}: nhập số {low}–{high}.")
    return int(n) if integer else n


def build_browse(serial, options):
    if not serial or not isinstance(serial, str):
        raise ValueError("Chọn điện thoại trước khi tạo tác vụ.")
    p = {"deviceId": serial, "workflowType": "for_you"}
    p["maxVideos"] = number(options.get("maxVideos", 10), "Số video", 1, 10000, True)
    p["minWatchTime"] = number(
        options.get("minWatchTime", 3), "Thời gian xem tối thiểu", 0.1, 3600
    )
    p["maxWatchTime"] = number(
        options.get("maxWatchTime", 8), "Thời gian xem tối đa", 0.1, 3600
    )
    if p["minWatchTime"] > p["maxWatchTime"]:
        raise ValueError("Thời gian xem tối thiểu phải nhỏ hơn hoặc bằng tối đa.")
    for action, plural in (
        ("like", "Likes"),
        ("follow", "Follows"),
        ("comment", "Comments"),
    ):
        k = action + "Probability"
        p[k] = number(options.get(k, 0), "Tỷ lệ " + action, 0, 100)
        cap = "max" + plural + "PerSession"
        p[cap] = number(options.get(cap, 0), "Giới hạn " + action, 0, 10000, True)
        if p[k] > 0 and p[cap] == 0:
            raise ValueError("Bật " + action + " cần giới hạn phiên lớn hơn 0.")
    comments = options.get("commentTexts", [])
    if not isinstance(comments, list) or any(not isinstance(c, str) for c in comments):
        raise ValueError("Danh sách comment phải chứa văn bản.")
    p["commentTexts"] = [c.strip() for c in comments if c.strip()]
    if p["commentProbability"] > 0 and not p["commentTexts"]:
        raise ValueError("Hãy nhập ít nhất một comment khi bật comment.")
    p.update(
        favoriteProbability=0,
        repostProbability=0,
        maxRepostsPerSession=0,
        pauseAfterActions=10,
        pauseDurationMin=30,
        pauseDurationMax=60,
    )
    profile = options.get("browseProfile", "standard")
    if profile not in ("standard", "natural"):
        raise ValueError("Mẫu nhịp lướt không hợp lệ.")
    p["browseProfile"] = profile
    duration = number(
        options.get("runDurationMinutes", 0), "Thời gian chạy (phút)", 0, 1440, True
    )
    if duration:
        if profile != "natural":
            raise ValueError("Chạy theo thời gian chỉ áp dụng cho Lướt tự nhiên.")
        p["runDurationMinutes"] = duration
    for key, label, default, low in (
        ("warmupVideos", "Video đầu chỉ xem", 3, 0),
        ("actionGapVideos", "Video giữa hai tương tác", 2, 0),
        ("restEveryVideos", "Nghỉ sau số video", 8, 1),
    ):
        p[key] = number(options.get(key, default), label, low, 1000, True)
    if profile == "natural":
        for key, default in (("pauseDurationMin", 20), ("pauseDurationMax", 45)):
            p[key] = number(options.get(key, default), "Khoảng nghỉ", 0.1, 3600)
        if p["pauseDurationMin"] > p["pauseDurationMax"]:
            raise ValueError("Khoảng nghỉ tối thiểu phải nhỏ hơn hoặc bằng tối đa.")
    if options.get("packageName"):
        p["packageName"] = options["packageName"]
    return p


BROWSE_ADVANCED_DEFAULTS = dict(
    minWatchTime=4,
    maxWatchTime=18,
    likeProbability=25,
    maxLikesPerSession=5,
    followProbability=5,
    maxFollowsPerSession=1,
    commentProbability=8,
    maxCommentsPerSession=2,
    warmupVideos=3,
    actionGapVideos=2,
    restEveryVideos=8,
    pauseDurationMin=20,
    pauseDurationMax=45,
)


def natural_browse_options(
    max_videos=20, comment_texts=None, advanced=None, run_duration_minutes=0
):
    """Validate a customer recipe and produce an independent engine snapshot."""
    if comment_texts is None:
        comment_texts = []
    if not isinstance(comment_texts, list) or any(
        not isinstance(t, str) for t in comment_texts
    ):
        raise ValueError("Danh sách bình luận phải chứa văn bản.")
    comments = list(dict.fromkeys(t.strip() for t in comment_texts if t.strip()))
    if advanced is None:
        advanced = {}
    if (
        not isinstance(advanced, dict)
        or advanced.keys() - BROWSE_ADVANCED_DEFAULTS.keys()
    ):
        raise ValueError("Cài đặt nâng cao không hợp lệ.")
    settings = BROWSE_ADVANCED_DEFAULTS | advanced
    # Validate the saved comment policy even when there are currently no texts.
    probability = number(settings["commentProbability"], "Tỷ lệ bình luận", 0, 100)
    cap = number(
        settings["maxCommentsPerSession"], "Giới hạn bình luận", 0, 10000, True
    )
    if probability > 0 and cap == 0:
        raise ValueError("Bật bình luận cần giới hạn phiên lớn hơn 0.")
    settings.update(
        commentProbability=probability if comments else 0,
        maxCommentsPerSession=min(cap, len(comments)),
    )
    payload = build_browse(
        "preview",
        dict(
            browseProfile="natural",
            maxVideos=max_videos,
            runDurationMinutes=run_duration_minutes,
            **settings,
            commentTexts=comments,
        ),
    )
    payload.pop("deviceId")
    return payload


def build_publish(serial, path, caption, hashtags, expected_account=""):
    """Publish on the logged-in account; ignore the legacy account label."""
    if not serial:
        raise ValueError("Chọn điện thoại trước khi tạo tác vụ.")
    file = Path(path).resolve()
    try:
        with file.open("rb") as stream:
            if not stream.read(1):
                raise ValueError("Video rỗng.")
    except OSError:
        raise ValueError(
            "Không đọc được video. Hãy kiểm tra đường dẫn và quyền truy cập."
        ) from None
    if file.suffix.lower() not in (
        ".mp4",
        ".mov",
        ".m4v",
        ".webm",
        ".png",
        ".jpg",
        ".jpeg",
    ):
        raise ValueError("Chọn video MP4/MOV/M4V/WEBM hoặc ảnh PNG/JPG.")
    if not isinstance(caption, str):
        raise ValueError("Caption không hợp lệ.")
    if isinstance(hashtags, str):
        hashtags = hashtags.split()
    tags = ["#" + h.strip().lstrip("#") for h in hashtags if h.strip().lstrip("#")]
    if len(tags) > 5:
        raise ValueError("TikTok hỗ trợ tối đa 5 hashtag trong tác vụ này.")
    return dict(
        deviceId=serial,
        localPath=str(file),
        caption=caption,
        hashtags=tags,
    )
