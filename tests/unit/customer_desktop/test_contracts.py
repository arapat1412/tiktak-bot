import json
import pytest
from customer_desktop.domain import build_browse, build_publish
from customer_desktop.adapters.taktik.protocol import LineDecoder, ResultTracker
from taktik.core.social_media.tiktok.workflows.common.video_payload import (
    video_settings_from_payload,
)


@pytest.mark.parametrize("value", [0, 1, 100])
def test_percentage_wire_contract(value):
    p = build_browse("serial", dict(likeProbability=value, maxLikesPerSession=10))
    settings = video_settings_from_payload(p)
    assert settings["like_probability"] == value / 100
    assert settings["favorite_probability"] == settings["repost_probability"] == 0


def test_no_implicit_interactions():
    p = build_browse("serial", {})
    s = video_settings_from_payload(p)
    assert all(
        s[k] == 0
        for k in (
            "like_probability",
            "follow_probability",
            "comment_probability",
            "favorite_probability",
            "repost_probability",
        )
    )


@pytest.mark.parametrize(
    "options",
    [
        {"minWatchTime": 10, "maxWatchTime": 1},
        {"likeProbability": 101},
        {"likeProbability": float("nan")},
        {"maxVideos": 0},
        {"maxVideos": 1.5},
        {"maxLikesPerSession": -1},
        {"commentProbability": 1, "maxCommentsPerSession": 1, "commentTexts": []},
        {"followProbability": 1, "maxFollowsPerSession": 0},
        {"maxWatchTime": float("inf")},
    ],
)
def test_invalid_browse_refused(options):
    with pytest.raises(ValueError):
        build_browse("serial", options)


def test_publish_unicode_and_original_preserved(tmp_path):
    path = tmp_path / "ảnh 한글.png"
    path.write_bytes(b"fixture")
    p = build_publish("serial", path, "Xin chào\n안녕하세요", ["#xin_chào"])
    assert p["caption"] == "Xin chào\n안녕하세요"
    assert p["hashtags"] == ["#xin_chào"]
    assert "botUsername" not in p
    assert path.read_bytes() == b"fixture"
    with pytest.raises(ValueError):
        build_publish("", path, "", [])


@pytest.mark.parametrize("legacy", [None, "", "@fixture", "fixture"])
def test_publish_never_requires_or_emits_account(tmp_path, legacy):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"fixture")
    options = {} if legacy is None else {"expected_account": legacy}
    p = build_publish("serial", path, "", [], **options)
    assert "botUsername" not in p


def test_chunked_utf8_and_multiple_lines():
    data = (
        json.dumps({"type": "new_event", "text": "Xin chào 한글"}, ensure_ascii=False)
        + "\ninvalid\n"
        + json.dumps({"type": "stats", "stats": {}})
    ).encode()
    d = LineDecoder()
    events = []
    for byte in data:
        events.extend(d.feed(bytes([byte])))
    events.extend(d.feed(b"", final=True))
    assert events[0]["text"] == "Xin chào 한글"
    assert [e["type"] for e in events] == ["new_event", "raw", "stats"]


def test_oversized_line_does_not_poison_next():
    d = LineDecoder(40)
    assert d.feed(b"x" * 100)[0]["type"] == "protocol_error"
    assert not d.buffer
    assert d.feed(b'tail\n{"type":"status"}\n') == [{"type": "status"}]


@pytest.mark.parametrize(
    "kind,events,code,stopped,expected",
    [
        ("publish", [], 0, False, "needs_review"),
        (
            "publish",
            [{"type": "upload_result", "success": True}],
            0,
            False,
            "succeeded",
        ),
        (
            "publish",
            [{"type": "upload_result", "success": True}],
            0,
            True,
            "needs_review",
        ),
        (
            "publish",
            [
                {"type": "upload_result", "success": True},
                {"type": "error", "error": "lost"},
            ],
            0,
            False,
            "needs_review",
        ),
        (
            "publish",
            [
                {"type": "upload_result", "success": True},
                {"type": "upload_result", "success": False},
            ],
            0,
            False,
            "needs_review",
        ),
        (
            "publish",
            [{"type": "upload_result", "success": True}],
            1,
            False,
            "needs_review",
        ),
        (
            "browse",
            [{"type": "status", "status": "completed"}],
            0,
            False,
            "needs_review",
        ),
        (
            "browse",
            [
                {
                    "type": "video_result",
                    "stats": {"videos_watched": 1, "errors": 0, "videos_commented": 1},
                },
                {"type": "status", "status": "completed"},
            ],
            0,
            False,
            "succeeded",
        ),
        (
            "browse",
            [
                {"type": "video_result", "stats": {"videos_watched": 0}},
                {"type": "status", "status": "completed"},
            ],
            0,
            False,
            "needs_review",
        ),
        (
            "browse",
            [
                {"type": "video_result", "stats": {"videos_watched": 1, "errors": 1}},
                {"type": "status", "status": "completed"},
            ],
            0,
            False,
            "needs_review",
        ),
        (
            "browse",
            [
                {
                    "type": "video_result",
                    "stats": {"videos_watched": 1, "completion_reason": "feed_stuck"},
                },
                {"type": "status", "status": "completed"},
            ],
            0,
            False,
            "needs_review",
        ),
    ],
)
def test_result_contract(kind, events, code, stopped, expected):
    tracker = ResultTracker(kind)
    for e in events:
        tracker.observe(e)
    assert tracker.finish(code, stopped)[0] == expected


def test_partial_run_not_success():
    t = ResultTracker("browse")
    t.expected_videos = 10
    t.observe({"type": "video_result", "stats": {"videos_watched": 1}})
    t.observe({"type": "status", "status": "completed"})
    assert t.finish(0)[0] == "needs_review"
