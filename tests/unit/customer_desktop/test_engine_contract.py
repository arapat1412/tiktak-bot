import pytest


def test_publish_cancel_not_swallowed_by_diagnostic_hook(monkeypatch):
    from bridges.tiktok.publish.bridge import TikTokPublishBridge
    from taktik.core.shared.diagnostics import run_halt
    from taktik.core.social_media.tiktok.workflows.publish.upload_workflow import (
        TikTokUploadWorkflow,
    )

    bridge = TikTokPublishBridge.__new__(TikTokPublishBridge)
    monkeypatch.setattr(run_halt, "arret_demande", lambda: {"code": "customer_stop"})
    workflow = TikTokUploadWorkflow(
        None, "fixture", step_hook=lambda phase: bridge._capture_phase(None, phase)
    )
    with pytest.raises(KeyboardInterrupt):
        workflow._capture("07_before_post")


def test_full_stats_opt_in_preserves_legacy_wire_contract(monkeypatch):
    from bridges.tiktok.common import video_callbacks as module
    from taktik.core.social_media.tiktok.workflows.common.models import (
        VideoWorkflowStats,
    )

    events = []
    monkeypatch.setattr(
        module, "send_message", lambda kind, **kw: events.append((kind, kw))
    )
    monkeypatch.setattr(module, "send_stats", lambda **kw: None)
    monkeypatch.setattr(module, "send_status", lambda *args: None)
    stats = VideoWorkflowStats()
    stats.videos_commented = 2
    monkeypatch.delenv("TAKTIK_CUSTOMER_EVENTS", raising=False)
    module.send_final_video_stats(stats)
    assert events == []
    monkeypatch.setenv("TAKTIK_CUSTOMER_EVENTS", "1")
    module.send_final_video_stats(stats)
    assert events[0][0] == "video_result"
    assert events[0][1]["stats"]["videos_commented"] == 2


def test_caption_survives_ime_switch_losing_focus(monkeypatch):
    from types import SimpleNamespace
    from taktik.core.social_media.tiktok.workflows.publish import (
        upload_workflow as module,
    )

    device = SimpleNamespace(focused=False)

    def focus():
        device.focused = True

    def switch_and_clear(*args, **kwargs):
        device.focused = False
        return True

    def type_checked(*args, **kwargs):
        return device.focused

    monkeypatch.setattr(
        module, "find_element", lambda *a, **k: SimpleNamespace(click=focus)
    )
    monkeypatch.setattr(module, "clear_caption_text", switch_and_clear)
    monkeypatch.setattr(module, "type_caption_checked", type_checked)
    monkeypatch.setattr(module, "dismiss_keyboard", lambda *a, **k: True)
    monkeypatch.setattr(module.time, "sleep", lambda *args: None)
    workflow = module.TikTokUploadWorkflow(device, "fixture")
    assert workflow._fill_caption("Chào 한글", [])


@pytest.mark.parametrize(
    "reason, expected",
    [
        ("interaction_unconfirmed", "stopped"),
        ("", "completed"),
        ("duration_limit", "completed"),
    ],
)
def test_final_stats_message_reports_interaction_halt(monkeypatch, reason, expected):
    from types import SimpleNamespace
    from bridges.tiktok.common import video_callbacks as module
    from taktik.core.social_media.tiktok.workflows.common.models import (
        VideoWorkflowStats,
    )

    messages, successes, warnings = [], [], []
    monkeypatch.setattr(module, "send_message", lambda kind, **kw: messages.append(kw))
    monkeypatch.setattr(
        module,
        "send_status",
        lambda status, message: messages.append({"message": message}),
    )
    monkeypatch.setattr(module, "send_stats", lambda **kw: None)
    monkeypatch.setattr(
        module,
        "logger",
        SimpleNamespace(success=successes.append, warning=warnings.append),
    )
    monkeypatch.delenv("TAKTIK_CUSTOMER_EVENTS", raising=False)
    stats = VideoWorkflowStats()
    stats.completion_reason = reason
    module.send_final_video_stats(stats)
    assert expected in messages[-1]["message"]
    assert bool(warnings) == (expected == "stopped")
    assert bool(successes) == (expected == "completed")
    if reason:
        assert messages[-1]["completion_reason"] == reason


@pytest.mark.parametrize("halt", [None, {"code": "interaction_unconfirmed"}])
def test_dispatcher_does_not_log_success_after_halt(monkeypatch, halt):
    from types import SimpleNamespace
    from bridges.tiktok.automation import dispatcher as module

    successes, warnings = [], []
    monkeypatch.setattr(
        module,
        "logger",
        SimpleNamespace(
            info=lambda *a: None, success=successes.append, warning=warnings.append
        ),
    )
    monkeypatch.setattr(module, "reset_network_if_enabled", lambda *a: True)
    monkeypatch.setattr(
        module, "dispatch_tiktok_workflow", lambda config: (True, "for_you")
    )
    monkeypatch.setattr(module, "force_stop_tiktok", lambda *a: None)
    monkeypatch.setattr(module.run_halt, "arret_demande", lambda: halt)
    assert module.TikTokDispatcherBridge({}).run() == 0
    assert bool(successes) == (halt is None)
    assert bool(warnings) == (halt is not None)
