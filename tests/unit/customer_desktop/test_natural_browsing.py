"""Exercise the real opt-in policy with fake UI observations and a controllable clock."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from customer_desktop.domain import build_browse
from customer_desktop.adapters.taktik.protocol import ResultTracker
from taktik.core.shared.diagnostics import run_halt
from taktik.core.social_media.tiktok.workflows.automation.for_you.models import (
    ForYouConfig,
)
from taktik.core.social_media.tiktok.workflows.automation.for_you.payload import (
    for_you_config_from_payload,
)
from taktik.core.social_media.tiktok.workflows.automation.for_you.workflow import (
    ForYouWorkflow,
)
from taktik.core.social_media.tiktok.workflows.automation.for_you import natural
from taktik.core.social_media.tiktok.workflows.common.models import VideoWorkflowStats


@pytest.fixture(autouse=True)
def clean_halt(monkeypatch):
    run_halt.reinitialiser()
    monkeypatch.setattr(natural, "emit_step", lambda *a, **kw: None)
    monkeypatch.setattr(natural.random, "shuffle", lambda a: None)
    monkeypatch.setattr(natural.random, "random", lambda: 0)
    yield
    run_halt.reinitialiser()


def workflow(**settings):
    wf = object.__new__(ForYouWorkflow)
    wf.config = ForYouConfig(browse_profile="natural", **settings)
    wf.stats = VideoWorkflowStats()
    wf.logger = Mock()
    wf._running = True
    wf._on_pause_callback = None
    wf._on_stats_callback = None
    wf._on_like_callback = None
    wf._on_follow_callback = None
    wf._reset_natural_session()
    wf._stop_if_action_blocked = Mock(return_value=False)
    wf._natural_wait = Mock(return_value=True)
    return wf


def video(index):
    return dict(
        author=f"creator-{index}", description=f"caption-{index}", is_liked=False
    )


def test_domain_engine_roundtrip_and_comment_requirement():
    options = dict(
        browseProfile="natural",
        warmupVideos=4,
        actionGapVideos=3,
        restEveryVideos=6,
        pauseDurationMin=11,
        pauseDurationMax=19,
        commentProbability=8,
        maxCommentsPerSession=2,
    )
    with pytest.raises(ValueError, match="comment"):
        build_browse("fake", options)
    config = for_you_config_from_payload(
        build_browse("fake", options | {"commentTexts": ["Xin chào", "한글"]})
    )
    assert (
        config.browse_profile,
        config.warmup_videos,
        config.action_gap_videos,
        config.rest_every_videos,
        config.pause_duration_min,
        config.pause_duration_max,
    ) == ("natural", 4, 3, 6, 11, 19)
    assert config.comment_texts == ["Xin chào", "한글"]
    assert config.favorite_probability == config.repost_probability == 0


@pytest.mark.parametrize(
    "options",
    [
        {"browseProfile": "oops"},
        {"warmupVideos": -1},
        {"actionGapVideos": 1.5},
        {"restEveryVideos": 0},
        {"pauseDurationMin": float("inf")},
        {"pauseDurationMin": 50, "pauseDurationMax": 20},
    ],
)
def test_invalid_natural_payload_refused(options):
    with pytest.raises(ValueError):
        build_browse("fake", {"browseProfile": "natural"} | options)


def test_warmup_spacing_one_action_and_continue_after_quota():
    wf = workflow(
        like_probability=1,
        follow_probability=1,
        comment_probability=1,
        max_likes_per_session=2,
        max_follows_per_session=0,
        max_comments_per_session=0,
        warmup_videos=3,
        action_gap_videos=2,
    )
    actions = []
    wf._natural_tap = (
        lambda action, key: actions.append((wf.stats.videos_watched, action)) or True
    )
    for n in range(1, 13):
        wf.stats.videos_watched = n
        wf._natural_read = lambda: (
            video(n),
            SimpleNamespace(kind="video", for_you=True),
        )
        wf._decide_and_execute_actions(video(n))
        assert not wf._check_limits_reached()
    assert actions == [(4, "like"), (7, "like")]
    assert wf.stats.videos_watched == 12
    assert wf.stats.videos_liked == 2


def test_only_one_of_multiple_eligible_actions():
    wf = workflow(
        warmup_videos=0,
        like_probability=1,
        follow_probability=1,
        comment_probability=1,
        comment_texts=["hello"],
    )
    wf.stats.videos_watched = 1
    wf._natural_read = lambda: (video(1), None)
    wf._natural_tap = Mock(return_value=True)
    wf._natural_comment = Mock(return_value=True)
    wf._decide_and_execute_actions(video(1))
    assert wf._natural_tap.call_count == 1
    wf._natural_comment.assert_not_called()


def test_real_workflow_watches_full_session_after_like_quota(monkeypatch):
    from taktik.core.social_media.tiktok.workflows.automation.for_you import (
        workflow as module,
    )

    monkeypatch.setattr(module, "emit_step", lambda *a, **kw: None)
    wf = workflow(
        max_videos=8,
        like_probability=1,
        max_likes_per_session=1,
        follow_probability=0,
        comment_probability=0,
        rest_every_videos=4,
    )
    state = {"index": 1, "liked": False}
    screen = SimpleNamespace(kind="video", for_you=True)

    def info(**kwargs):
        return video(state["index"]) | {"is_liked": state["liked"]}

    def click():
        state["liked"] = True
        return True

    def swipe():
        state["index"] += 1
        state["liked"] = False
        return True

    wf.detection = SimpleNamespace(read_screen=lambda: screen, get_video_info=info)
    wf._natural_click_once = Mock(side_effect=lambda action: click())
    wf.scroll = SimpleNamespace(scroll_to_next_video=Mock(side_effect=swipe))
    wf._ensure_on_for_you = lambda: True
    wf._wait_if_paused = lambda: True
    wf._handle_popups = lambda *a: False
    wf._handle_comments_section = lambda *a: False
    wf._handle_suggestion_page = lambda *a: False
    wf._handle_stuck_video = lambda *a: False
    wf._train_on_video = lambda *a: False
    wf._behavior_reading_scale = lambda *a: 1
    wf._pause_length = lambda: 25
    wf._on_pause_callback = Mock()
    wf._on_video_callback = None
    result = wf.run()
    assert result.videos_watched == 8
    assert result.videos_liked == 1
    assert result.completion_reason == ""
    wf._natural_click_once.assert_called_once_with("like")
    assert wf.scroll.scroll_to_next_video.call_count == 7
    wf._on_pause_callback.assert_called_once_with(25)


def test_uncertain_tap_halts_and_never_counts_or_retries():
    wf = workflow(warmup_videos=0, like_probability=1)
    wf.stats.videos_watched = 1
    wf._natural_read = lambda: (video(1), None)
    wf._natural_tap = Mock(return_value=False)
    wf._decide_and_execute_actions(video(1))
    wf._decide_and_execute_actions(video(1))
    assert not wf._running
    assert wf.stats.videos_liked == 0
    assert wf._natural_tap.call_count == 1
    assert wf._check_limits_reached()
    tracker = ResultTracker("browse")
    tracker.expected_videos = 1
    tracker.observe({"type": "video_result", "stats": wf.stats.to_dict()})
    assert tracker.finish(0)[0] == "needs_review"


def test_tap_must_confirm_on_same_video():
    wf = workflow()
    wf._natural_click_once = Mock(return_value=True)
    wf._natural_read = lambda: (video(2) | {"is_liked": True}, None)
    assert not wf._natural_tap("like", wf._natural_identity(video(1)))
    wf._natural_click_once.assert_called_once_with("like")
    wf._natural_read = lambda: (video(1) | {"is_liked": True}, None)
    assert wf._natural_tap("like", wf._natural_identity(video(1)))


def test_no_follow_without_observed_follow_button():
    wf = workflow(warmup_videos=0, like_probability=0, follow_probability=1)
    wf.stats.videos_watched = 1
    wf._natural_read = lambda: (video(1), object())
    wf.detection = SimpleNamespace(_element_exists=lambda *a, **kw: False)
    wf._natural_tap = Mock()
    wf._decide_and_execute_actions(video(1))
    wf._natural_tap.assert_not_called()


def test_existing_action_block_prevents_tap():
    wf = workflow(warmup_videos=0, like_probability=1)
    wf.stats.videos_watched = 1
    wf._natural_read = lambda: (video(1), None)
    wf._stop_if_action_blocked = Mock(return_value=True)
    wf._natural_tap = Mock()
    wf._decide_and_execute_actions(video(1))
    wf._natural_tap.assert_not_called()


def test_follow_requires_same_video_and_button_disappearing():
    wf = workflow()
    wf._natural_click_once = Mock(return_value=True)
    wf._natural_read = lambda: (video(1), object())
    wf.detection = SimpleNamespace(_element_exists=lambda *a, **kw: False)
    assert wf._natural_tap("follow", wf._natural_identity(video(1)))
    wf.detection._element_exists = lambda *a, **kw: True
    assert not wf._natural_tap("follow", wf._natural_identity(video(1)))


def test_uncertain_public_tap_has_no_fallback(monkeypatch):
    from taktik.core.shared.behavior import tap
    from taktik.core.social_media.tiktok.actions.base import utils

    wf = workflow()
    element = Mock()
    wf.click = SimpleNamespace(device=object())
    monkeypatch.setattr(utils, "first_matching", lambda *args: [element])
    injection = Mock(return_value=False)
    monkeypatch.setattr(tap, "tap_element_human", injection)
    assert not wf._natural_click_once("like")
    injection.assert_called_once()
    element.click.assert_not_called()


def test_uncertain_comment_send_has_no_fallback(monkeypatch):
    from taktik.core.social_media.tiktok.actions.atomic.interaction import (
        comment_actions as module,
    )

    actions = object.__new__(module.CommentActions)
    actions.device = object()
    actions.logger = Mock()
    actions.comment_selectors = SimpleNamespace(post_comment_button=["send"])
    actions.is_comment_sheet_open = lambda: True
    actions._focus_and_type = lambda text: True
    element = Mock()
    monkeypatch.setattr(module, "first_matching", lambda *args: [element])
    injection = Mock(return_value=False)
    monkeypatch.setattr(module, "tap_element_human", injection)
    assert not actions.post_comment("hello", single_attempt=True)
    injection.assert_called_once()
    element.click.assert_not_called()


def test_wait_and_rest_are_interruptible(monkeypatch):
    wf = workflow(rest_every_videos=2)
    del wf._natural_wait
    now = [0.0]
    monkeypatch.setattr(natural.time, "monotonic", lambda: now[0])

    def sleep(seconds):
        assert seconds <= 0.2
        now[0] += seconds
        wf.stop()

    monkeypatch.setattr(natural.time, "sleep", sleep)
    wf.stats.videos_watched = 2
    wf._pause_length = lambda: 45
    wf._check_pause_needed()
    assert now[0] <= 0.2
    assert not wf._running


def test_comments_not_reused_even_when_list_has_duplicates():
    wf = workflow(
        warmup_videos=0,
        action_gap_videos=0,
        like_probability=0,
        follow_probability=0,
        comment_probability=1,
        comment_texts=["Xin chào", "Xin chào", "한글"],
        max_comments_per_session=10,
    )
    sent = []

    def send(text):
        sent.append(text)
        wf._natural_used_comments.add(text)
        return True

    wf._natural_comment = send
    for n in range(1, 5):
        wf.stats.videos_watched = n
        wf._natural_read = lambda: (video(n), None)
        wf._decide_and_execute_actions(video(n))
    assert sorted(sent) == ["Xin chào", "한글"]
    assert wf.stats.videos_commented == 2


def _composer(value):
    """The input as the dump shows it: `("text", "hint")` when Android exposes a hint."""
    if isinstance(value, tuple):
        text, hint = value
        return SimpleNamespace(text=text, attrib={"hint": hint})
    return SimpleNamespace(text=value)


@pytest.mark.parametrize(
    "new_row, composer, sheet, expected",
    [
        (True, "", True, True),
        (True, ("Add comment...", "Add comment..."), True, True),
        (False, ("Add comment...", "Add comment..."), True, False),
        (False, "", True, False),
        (True, None, True, False),
        (True, "Xin chào 한글", True, False),
        (True, ("brouillon", "Add comment..."), True, False),
        (True, "", False, False),
    ],
)
def test_comment_requires_new_row_and_observed_empty_composer(
    monkeypatch, new_row, composer, sheet, expected
):
    from taktik.core.social_media.tiktok.actions.base import utils

    wf = workflow()
    wf._current_video_author = "creator"
    posted = [False]
    actions = SimpleNamespace(
        device=object(),
        comment_selectors=SimpleNamespace(comment_input=["input"]),
        open_comments=lambda: True,
        is_comment_sheet_open=lambda: sheet,
        read_comments=lambda **kw: (
            [{"text": "Xin chào 한글"}] if posted[0] and new_row else []
        ),
        close_comments=Mock(return_value=True),
    )

    def post(text, *, single_attempt=False):
        assert text == "Xin chào 한글"
        assert single_attempt
        posted[0] = True
        return True

    actions.post_comment = Mock(side_effect=post)
    wf._comment_actions = lambda: actions
    wf._record_posted_comment = Mock()
    monkeypatch.setattr(
        utils,
        "first_matching",
        lambda *a: [] if composer is None else [_composer(composer)],
    )
    assert wf._natural_comment("Xin chào 한글") == expected
    actions.post_comment.assert_called_once()
    assert wf._record_posted_comment.call_count == int(expected)
    assert actions.close_comments.call_count == int(expected)


def test_existing_same_text_is_not_proof_of_new_comment(monkeypatch):
    from taktik.core.social_media.tiktok.actions.base import utils

    wf = workflow()
    wf._current_video_author = "creator"
    actions = SimpleNamespace(
        device=object(),
        comment_selectors=SimpleNamespace(comment_input=["input"]),
        open_comments=lambda: True,
        post_comment=Mock(return_value=True),
        is_comment_sheet_open=lambda: True,
        read_comments=lambda **kw: [{"text": "hello"}],
        close_comments=Mock(),
    )
    wf._comment_actions = lambda: actions
    monkeypatch.setattr(utils, "first_matching", lambda *a: [SimpleNamespace(text="")])
    assert not wf._natural_comment("hello")
    actions.post_comment.assert_called_once()
    actions.close_comments.assert_not_called()
