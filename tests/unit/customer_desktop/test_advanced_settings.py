import json
from unittest.mock import Mock

import pytest

from customer_desktop.domain import natural_browse_options
from customer_desktop.paths import prepare_paths
from customer_desktop.services import DesktopService
from customer_desktop.ui import BrowseDialog
from taktik.core.social_media.tiktok.workflows.automation.for_you.payload import (
    for_you_config_from_payload,
)


def dialog_at(root):
    service = DesktopService(prepare_paths(root), prepare=False)
    service.timer.stop()
    return service, BrowseDialog(
        service, [dict(serial="fixture", name="Máy thử")], None
    )


def close(service, dialog):
    dialog.reject()
    service.store.close()


def test_save_reopen_restores_recipe_and_custom_submission(app, tmp_path):
    service, dialog = dialog_at(tmp_path)
    dialog.videos.setValue(73)
    dialog.comments.setPlainText("Xin chào\n한글\nXin chào")
    fields = dialog.advanced_fields
    fields["minWatchTime"].setValue(7.5)
    fields["maxWatchTime"].setValue(23)
    fields["likeProbability"].setValue(41)
    fields["maxLikesPerSession"].setValue(12)
    fields["commentProbability"].setValue(19)
    fields["maxCommentsPerSession"].setValue(7)
    fields["restEveryVideos"].setValue(15)
    fields["pauseDurationMin"].setValue(31)
    fields["pauseDurationMax"].setValue(80)
    dialog.schedule.enabled.setChecked(True)
    expected = dialog.values()
    dialog.save_recipe_button.click()
    assert "Đã lưu" in dialog.recipe_status.text()
    saved = service.store.setting(dialog.RECIPE_KEY)
    assert set(saved) == {"maxVideos", "commentTexts", "advanced"}
    assert saved["advanced"]["maxCommentsPerSession"] == 7
    close(service, dialog)

    service, dialog = dialog_at(tmp_path)
    assert dialog.values() == expected
    assert not dialog.schedule.enabled.isChecked()
    assert dialog.comments.toPlainText() == "Xin chào\n한글"
    dialog.send = Mock()
    dialog.submit()
    spec = dialog.send.call_args.args[0][0]
    config = for_you_config_from_payload(spec["payload"])
    assert config.max_videos == 73
    assert config.min_watch_time == 7.5
    assert config.like_probability == 0.41
    assert config.max_likes_per_session == 12
    assert config.comment_probability == 0.19
    assert config.max_comments_per_session == 2
    assert config.rest_every_videos == 15
    assert (config.pause_duration_min, config.pause_duration_max) == (31, 80)
    # A later recipe edit cannot mutate an already submitted payload.
    snapshot = json.dumps(spec)
    dialog.advanced_fields["likeProbability"].setValue(3)
    dialog.save_recipe()
    assert json.dumps(spec) == snapshot
    close(service, dialog)


@pytest.mark.parametrize(
    "low,high",
    [("minWatchTime", "maxWatchTime"), ("pauseDurationMin", "pauseDurationMax")],
)
def test_invalid_ranges_disable_actions_and_do_not_overwrite(app, tmp_path, low, high):
    service, dialog = dialog_at(tmp_path)
    dialog.save_recipe()
    saved = service.store.setting(dialog.RECIPE_KEY)
    dialog.advanced_fields[low].setValue(50)
    dialog.advanced_fields[high].setValue(2)
    assert not dialog.create.isEnabled()
    assert not dialog.save_recipe_button.isEnabled()
    assert "tối thiểu" in dialog.preview.text()
    dialog.save_recipe()
    assert service.store.setting(dialog.RECIPE_KEY) == saved
    dialog.advanced_fields[high].setValue(60)
    assert dialog.create.isEnabled()
    assert dialog.save_recipe_button.isEnabled()
    close(service, dialog)


def test_empty_comments_preserve_configured_policy(app, tmp_path):
    service, dialog = dialog_at(tmp_path)
    dialog.advanced_fields["commentProbability"].setValue(35)
    dialog.advanced_fields["maxCommentsPerSession"].setValue(6)
    dialog.save_recipe()
    close(service, dialog)
    service, dialog = dialog_at(tmp_path)
    assert dialog.values()["commentProbability"] == 0
    assert dialog.advanced_fields["commentProbability"].value() == 35
    dialog.comments.setPlainText("Một\nHai\nBa")
    assert dialog.values()["commentProbability"] == 35
    assert dialog.values()["maxCommentsPerSession"] == 3
    close(service, dialog)


def test_reset_and_cancel_only_change_saved_recipe_when_explicitly_saved(app, tmp_path):
    service, dialog = dialog_at(tmp_path)
    dialog.videos.setValue(88)
    dialog.save_recipe()
    dialog.reset_recipe()
    assert dialog.videos.value() == 20
    assert service.store.setting(dialog.RECIPE_KEY)["maxVideos"] == 88
    close(service, dialog)
    service, dialog = dialog_at(tmp_path)
    assert dialog.videos.value() == 88
    dialog.reset_recipe()
    dialog.save_recipe()
    close(service, dialog)
    service, dialog = dialog_at(tmp_path)
    assert dialog.values() == natural_browse_options()
    close(service, dialog)


@pytest.mark.parametrize(
    "saved",
    [
        [],
        {"advanced": {"minWatchTime": 200, "maxWatchTime": 2}},
        {"advanced": {"likeProbability": "bad"}},
        {"commentTexts": "invalid"},
    ],
)
def test_invalid_stored_recipe_falls_back_with_notice(app, tmp_path, saved):
    service, dialog = dialog_at(tmp_path)
    service.store.set_setting(dialog.RECIPE_KEY, saved)
    dialog.reject()
    dialog = BrowseDialog(service, [dict(serial="fixture", name="Máy")], None)
    assert dialog.values() == natural_browse_options()
    assert "đang dùng mặc định" in dialog.recipe_status.text()
    close(service, dialog)


def test_save_error_is_visible_without_claiming_success(app, tmp_path, monkeypatch):
    service, dialog = dialog_at(tmp_path)
    monkeypatch.setattr(
        service.store, "set_setting", Mock(side_effect=OSError("disk full"))
    )
    dialog.save_recipe()
    assert "Chưa lưu được" in dialog.recipe_status.text()
    assert "disk full" in dialog.recipe_status.text()
    close(service, dialog)


@pytest.mark.parametrize(
    "advanced",
    [
        {"likeProbability": 101},
        {"minWatchTime": 50, "maxWatchTime": 2},
        {"commentProbability": 5, "maxCommentsPerSession": 0},
        {"restEveryVideos": 0},
        {"deviceId": "other"},
    ],
)
def test_invalid_custom_policy_is_rejected(advanced):
    with pytest.raises(ValueError):
        natural_browse_options(20, [], advanced)
