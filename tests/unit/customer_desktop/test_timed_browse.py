from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from customer_desktop.adapters.taktik.protocol import ResultTracker
from customer_desktop.domain import natural_browse_options
from customer_desktop.paths import prepare_paths
from customer_desktop.services import DesktopService
from customer_desktop.ui import BrowseDialog
from taktik.core.shared.diagnostics import run_halt
from taktik.core.social_media.tiktok.workflows.automation.for_you import natural
from taktik.core.social_media.tiktok.workflows.automation.for_you import (
    workflow as engine,
)
from taktik.core.social_media.tiktok.workflows.automation.for_you.models import (
    ForYouConfig,
)
from taktik.core.social_media.tiktok.workflows.common.models import VideoWorkflowStats
from taktik.core.social_media.tiktok.workflows.automation.for_you.payload import (
    for_you_config_from_payload,
)


@pytest.fixture
def timed(monkeypatch):
    run_halt.reinitialiser()
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(
        natural,
        "time",
        SimpleNamespace(
            monotonic=lambda: clock.now,
            sleep=lambda seconds: setattr(clock, "now", clock.now + seconds),
        ),
    )
    wf = object.__new__(engine.ForYouWorkflow)
    wf.config = ForYouConfig(
        browse_profile="natural",
        run_duration_minutes=1,
        max_videos=1,
        rest_every_videos=1000,
        warmup_videos=0,
        like_probability=0,
        follow_probability=0,
        comment_probability=0,
    )
    wf.stats = VideoWorkflowStats()
    wf._running = True
    wf.logger = Mock()
    wf._on_video_callback = wf._on_pause_callback = wf._on_stats_callback = None
    wf._on_like_callback = wf._on_follow_callback = None
    wf._stop_if_action_blocked = Mock(return_value=False)
    wf._reset_natural_session()
    yield wf, clock
    run_halt.reinitialiser()


def test_timed_real_loop_ignores_video_cap_and_stops_without_extra_swipe(
    timed, monkeypatch
):
    wf, clock = timed
    info = dict(author="creator", description="caption", is_liked=False)
    wf.detection = SimpleNamespace(
        read_screen=Mock(), get_video_info=Mock(return_value=info)
    )
    for method in (
        "_handle_popups",
        "_handle_comments_section",
        "_handle_suggestion_page",
        "_handle_stuck_video",
        "_train_on_video",
        "_should_skip_video",
    ):
        setattr(wf, method, Mock(return_value=False))
    wf._ensure_on_for_you = Mock(return_value=True)
    wf._wait_if_paused = Mock(return_value=True)
    wf._screen_kind = Mock(return_value="video")
    wf._behavior_reading_scale = Mock(return_value=1)
    wf._send_stats_update = Mock()
    wf.scroll = SimpleNamespace(scroll_to_next_video=Mock(return_value=True))
    monkeypatch.setattr(engine, "video_watch_seconds", lambda *a, **kw: 10)
    stats = wf.run()
    assert stats.completion_reason == "duration_limit"
    assert stats.errors == 0
    assert stats.videos_watched > wf.config.max_videos
    assert wf.scroll.scroll_to_next_video.call_count == stats.videos_watched
    assert 60 <= clock.now < 60.3
    assert not wf._running


def test_watch_and_rest_wait_end_at_deadline(timed):
    wf, clock = timed
    clock.now = 59
    assert not wf._natural_wait(45)
    assert clock.now < 60.3
    assert wf.stats.completion_reason == "duration_limit"
    assert not wf._running


def test_expiry_prevents_new_public_interaction(timed):
    wf, clock = timed
    wf.config.like_probability = 1
    wf.stats.videos_watched = 1
    clock.now = 60
    wf._natural_tap = Mock()
    wf._decide_and_execute_actions(dict(author="creator", description="caption"))
    wf._natural_tap.assert_not_called()
    assert wf.stats.completion_reason == "duration_limit"


def test_inflight_verification_finishes_after_deadline(timed):
    wf, clock = timed
    info = dict(author="creator", description="caption", is_liked=True)
    clock.now = 59.9
    wf._natural_click_once = Mock(return_value=True)
    wf._natural_read = Mock(return_value=(info, None))
    assert wf._natural_tap("like", wf._natural_identity(info))
    assert clock.now > 60
    assert wf._check_limits_reached()
    assert wf.stats.completion_reason == "duration_limit"


def test_expiry_does_not_override_existing_halt(timed):
    wf, clock = timed
    clock.now = 61
    run_halt.demander_arret("device_disconnected", "fixture")
    assert wf._check_limits_reached()
    assert wf.stats.completion_reason == "device_disconnected"


@pytest.mark.parametrize(
    "duration,reason,errors,exit_code,stopped,expected",
    [
        (1, "duration_limit", 0, 0, False, "succeeded"),
        (0, "duration_limit", 0, 0, False, "needs_review"),
        (1, "duration_limit", 1, 0, False, "needs_review"),
        (1, "duration_limit", 0, 1, False, "needs_review"),
        (1, "duration_limit", 0, 0, True, "needs_review"),
        (1, "feed_stuck", 0, 0, False, "needs_review"),
        (1, "", 0, 0, False, "needs_review"),
    ],
)
def test_result_requires_normal_timed_final_evidence(
    duration, reason, errors, exit_code, stopped, expected
):
    tracker = ResultTracker("browse")
    tracker.expected_videos = 10000
    tracker.expected_duration_minutes = duration
    tracker.observe(
        {
            "type": "video_result",
            "stats": {
                "videos_watched": 0,
                "errors": errors,
                "completion_reason": reason,
            },
        }
    )
    tracker.observe(
        {"type": "status", "status": "completed", "completion_reason": reason}
    )
    assert tracker.finish(exit_code, stopped)[0] == expected
    tracker.final_video = False
    assert tracker.finish(0)[0] == "needs_review"


@pytest.mark.parametrize("value", [-1, 1441, 1.5, float("inf"), "bad"])
def test_invalid_minutes_rejected(value):
    with pytest.raises(ValueError):
        natural_browse_options(run_duration_minutes=value)


def test_duration_payload_roundtrip_and_legacy_default():
    assert "runDurationMinutes" not in natural_browse_options()
    config = for_you_config_from_payload(
        natural_browse_options(run_duration_minutes=45)
    )
    assert config.run_duration_minutes == 45
    assert for_you_config_from_payload({}).run_duration_minutes == 0


def test_timed_recipe_persists_and_submission_uses_minutes(app, tmp_path):
    def open_dialog():
        service = DesktopService(prepare_paths(tmp_path), prepare=False)
        service.timer.stop()
        return service, BrowseDialog(
            service, [dict(serial="fake", name="Máy thử")], None
        )

    service, dialog = open_dialog()
    assert not dialog.timed_run.isChecked()
    dialog.timed_run.setChecked(True)
    dialog.duration_minutes.setValue(17)
    assert not dialog.videos.isEnabled()
    assert "17 phút/máy" in dialog.preview.text()
    dialog.save_recipe()
    dialog.reject()
    service.store.close()

    service, dialog = open_dialog()
    assert dialog.timed_run.isChecked()
    assert dialog.duration_minutes.value() == 17
    dialog.send = Mock()
    dialog.submit()
    assert dialog.send.call_args.args[0][0]["payload"]["runDurationMinutes"] == 17
    dialog.reset_recipe()
    assert not dialog.timed_run.isChecked()
    assert dialog.videos.isEnabled()
    assert "runDurationMinutes" not in dialog.values()
    assert service.store.setting(dialog.RECIPE_KEY)["runDurationMinutes"] == 17
    dialog.reject()
    service.store.close()


def test_runner_accepts_timed_result_from_real_subprocess(app, tmp_path):
    import json
    import sys
    import time
    from PySide6.QtTest import QTest
    from customer_desktop.runner import Runner

    root = prepare_paths(tmp_path)
    payload = natural_browse_options(run_duration_minutes=1)
    job = dict(
        id="timed-fixture", serial="fake", kind="browse", snapshot=json.dumps(payload)
    )
    worker = tmp_path / "timed_worker.py"
    worker.write_text(
        "import json,os,time\nfrom pathlib import Path\n"
        "while not Path(os.environ['TAKTIK_CUSTOMER_GATE']).exists(): time.sleep(.01)\n"
        "print(json.dumps({'type':'video_result','stats':{'videos_watched':0,'errors':0,'completion_reason':'duration_limit'}}),flush=True)\n"
        "print(json.dumps({'type':'status','status':'completed','completion_reason':'duration_limit'}),flush=True)\n",
        encoding="utf-8",
    )
    runner = Runner(
        root,
        job,
        "attempt",
        root / "logs" / "fixture",
        "adb",
        command=(sys.executable, ["-u", str(worker)]),
    )
    results = []
    runner.done.connect(lambda *args: results.append(args))
    runner.start()
    end = time.monotonic() + 8
    while not results and time.monotonic() < end:
        app.processEvents()
        QTest.qWait(10)
    assert results and results[0][0] == "succeeded"
    assert runner.tracker.expected_duration_minutes == 1
