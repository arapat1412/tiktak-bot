"""The simple customer flow always reaches the bounded natural engine policy."""

from copy import deepcopy

import pytest

from customer_desktop.domain import build_browse, natural_browse_options
from customer_desktop.paths import prepare_paths
from customer_desktop.services import import_specs
from customer_desktop.storage import Store
from taktik.core.social_media.tiktok.workflows.automation.for_you.payload import (
    for_you_config_from_payload,
)


@pytest.mark.parametrize("texts", [None, [], ["", "  "]])
def test_empty_comments_disable_only_commenting(texts):
    p = natural_browse_options(comment_texts=texts)
    config = for_you_config_from_payload(build_browse("fake", p))
    assert config.browse_profile == "natural"
    assert config.max_videos == 20
    assert (config.min_watch_time, config.max_watch_time) == (4, 18)
    assert (config.like_probability, config.follow_probability) == (0.25, 0.05)
    assert (config.max_likes_per_session, config.max_follows_per_session) == (5, 1)
    assert config.comment_probability == config.max_comments_per_session == 0
    assert (
        config.warmup_videos,
        config.action_gap_videos,
        config.rest_every_videos,
    ) == (3, 2, 8)
    assert (config.pause_duration_min, config.pause_duration_max) == (20, 45)
    assert config.favorite_probability == config.repost_probability == 0
    assert "deviceId" not in p


@pytest.mark.parametrize("texts,cap", [(["Một câu"], 1), (["Một", "Hai", "Ba"], 2)])
def test_comment_quota_is_bounded_by_available_unique_text(texts, cap):
    p = natural_browse_options(30, texts)
    assert p["maxVideos"] == 30
    assert p["commentProbability"] == 8
    assert p["maxCommentsPerSession"] == cap
    assert p["commentTexts"] == texts


def test_comments_are_unique_without_mutating_caller_or_other_sessions():
    texts = ["  Xin chào 한글  ", "", "Xin chào 한글", "  "]
    before = deepcopy(texts)
    p = natural_browse_options(comment_texts=texts)
    assert texts == before
    assert p["commentTexts"] == ["Xin chào 한글"]
    assert p["maxCommentsPerSession"] == 1
    p["commentTexts"].append("mutated")
    p["likeProbability"] = 100
    fresh = natural_browse_options()
    assert fresh["commentTexts"] == []
    assert fresh["likeProbability"] == 25


@pytest.mark.parametrize(
    "videos,texts", [(0, []), (1.5, []), (float("inf"), []), (20, "text"), (20, [None])]
)
def test_invalid_single_mode_inputs_are_rejected(videos, texts):
    with pytest.raises(ValueError):
        natural_browse_options(videos, texts)


def test_submission_import_reaches_engine_and_leaves_legacy_data_unchanged(tmp_path):
    root = prepare_paths(tmp_path)
    store = Store(root)
    store.discover(
        [dict(serial="a", connection="online"), dict(serial="b", connection="online")]
    )
    legacy = build_browse("a", dict(likeProbability=90, maxLikesPerSession=20))
    store.save_preset("Mẫu cũ", legacy)
    old_id = store.enqueue([dict(serial="a", kind="browse", payload=legacy)], "old")[0]
    old_snapshot = store.job(old_id)["snapshot"]
    options = natural_browse_options(12, ["Câu thử 한글"])
    specs = [
        dict(serial=s, kind="browse", payload=build_browse(s, options))
        for s in ("a", "b")
    ]
    imported, assets = import_specs(root, specs)
    assert assets == []
    assert [spec["payload"]["deviceId"] for spec in imported] == ["a", "b"]
    for spec in imported:
        config = for_you_config_from_payload(spec["payload"])
        assert config.browse_profile == "natural"
        assert config.like_probability == 0.25
        assert config.comment_texts == ["Câu thử 한글"]
    store.enqueue(imported, "new")
    assert store.job(old_id)["snapshot"] == old_snapshot
    assert store.presets()["Mẫu cũ"] == legacy
    store.close()
