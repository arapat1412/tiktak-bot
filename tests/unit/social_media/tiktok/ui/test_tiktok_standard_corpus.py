"""Real, sanitized Samsung captures; regress both foreground and background controls."""

import hashlib
import json
from pathlib import Path

import pytest

from taktik.core.compat.selectors.setup import apply_version_overrides
from taktik.core.shared.device.ui_dump import parse_ui_dump
from taktik.core.social_media.tiktok.ui.selectors.locales import (
    active_locale,
    set_active_locale,
)
from taktik.core.social_media.tiktok.ui.selectors.shell.navigation import (
    NAVIGATION_SELECTORS,
)
from taktik.core.social_media.tiktok.ui.selectors.flows.publish import (
    PUBLISH_COMPOSER_SELECTORS as COMPOSER,
    PUBLISH_EDITOR_SELECTORS as EDITOR,
    PUBLISH_MEDIA_PICKER_SELECTORS as PICKER,
)
from taktik.core.social_media.tiktok.ui.selectors.surfaces.video.comments import (
    COMMENT_SELECTORS as COMMENTS,
)
from taktik.core.social_media.tiktok.ui.selectors.surfaces.video.engagement import (
    VIDEO_ENGAGEMENT_SELECTORS as ENGAGEMENT,
)
from taktik.core.social_media.tiktok.actions.atomic.detection.screen_reading import (
    popup_families,
)
from taktik.core.social_media.tiktok.workflows.common.popup_handler import PopupHandler

ROOT = Path(__file__).parents[1] / "fixtures" / "standard"
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
PKG = "com.ss.android.ugc.trill"
BUILDS = [
    ("47.1.4", "AXKB"),
    ("47.5.2", "CT7H"),
    ("47.5.3", "QS8Z"),
    ("47.6.3", "QNBP"),
]


def capture(version, device, state):
    record = next(
        d
        for d in MANIFEST["dumps"]
        if (d["version"], d["device"], d["state"]) == (version, device, state)
    )
    xml = (ROOT / record["file"]).read_text(encoding="utf-8")
    return parse_ui_dump(xml), xml


def first(tree, selectors):
    return next((tree.xpath(xp) for xp in selectors if tree.xpath(xp)), [])


@pytest.fixture(autouse=True)
def restore_catalog():
    old = active_locale()
    yield
    apply_version_overrides("tiktok", "43.1.4")
    set_active_locale(old)


@pytest.mark.parametrize("record", MANIFEST["dumps"], ids=lambda d: d["file"])
def test_every_capture_has_provenance_hash_and_valid_xml(record):
    content = (ROOT / record["file"]).read_bytes()
    assert hashlib.sha256(content).hexdigest() == record["sanitized_sha256"]
    assert parse_ui_dump(content.decode("utf-8")) is not None
    assert record["package"] in (PKG, "com.ss.android.ugc.tiktok.lite")
    assert record["app_language"] == "ko"
    assert record["android"] and record["version_code"] and record["state"]
    assert record["adb_port"] in (5037, 5038)


@pytest.mark.parametrize("version,device", BUILDS)
def test_feed_controls_resolve_and_sheet_gate_does_not_fire_on_feed(version, device):
    apply_version_overrides("tiktok", version, package_name=PKG)
    set_active_locale("ko")
    state = (
        "loaded"
        if version == "47.6.3"
        else "feed_ready" if version == "47.5.3" else "feed_loaded"
    )
    tree, _ = capture(version, device, state)
    for selectors in (
        NAVIGATION_SELECTORS.home_tab,
        NAVIGATION_SELECTORS.profile_tab,
        NAVIGATION_SELECTORS.create_button,
        ENGAGEMENT.like_button,
        ENGAGEMENT.comment_button,
    ):
        found = first(tree, selectors)
        assert len(found) == 1
        assert found[0].get("package") == PKG
    assert not first(tree, COMMENTS.sheet_indicator)


@pytest.mark.parametrize("version,device", BUILDS)
@pytest.mark.parametrize("locale", ["ko", "en", None])
def test_sheet_and_foreground_send_do_not_depend_on_translated_positional_fallback(
    version, device, locale
):
    apply_version_overrides("tiktok", version, package_name=PKG)
    set_active_locale(locale)
    state = "comments_draft" if version == "47.6.3" else "comments_draft_native"
    tree, _ = capture(version, device, state)
    assert first(tree, COMMENTS.sheet_indicator)
    sends = first(tree, COMMENTS.post_comment_button)
    # 47.5.2 negative capture: background contains a draft, active composer is EMPTY.
    assert len(sends) == (0 if version == "47.5.2" else 1)
    assert all(n.get("enabled") == "true" and n.get("package") == PKG for n in sends)
    if sends:
        assert sends[0].get("resource-id").split(":id/")[-1] in ("d1y", "d1b", "d33")


@pytest.mark.parametrize("version,device", BUILDS)
def test_sheet_gate_and_close_match_without_locale_including_empty_sheet(
    version, device
):
    apply_version_overrides("tiktok", version, package_name=PKG)
    set_active_locale("en")
    state = "comments_populated" if version == "47.6.3" else "comments_recovered"
    tree, _ = capture(version, device, state)
    assert first(tree, COMMENTS.sheet_indicator)
    assert len(first(tree, COMMENTS.close_button)) == 1
    assert not first(tree, COMMENTS.post_comment_button)


@pytest.mark.parametrize("version,device", BUILDS)
def test_real_production_typing_and_clear_pair_has_one_enabled_foreground_send(
    version, device
):
    from types import SimpleNamespace
    from taktik.core.social_media.tiktok.actions.atomic.interaction.comment_actions import (
        comment_composer_is_empty,
    )

    apply_version_overrides("tiktok", version, package_name=PKG)
    set_active_locale("ko")
    tree, _ = capture(version, device, "comments_production_draft")
    assert first(tree, COMMENTS.sheet_indicator)
    inputs = first(tree, COMMENTS.comment_input)
    assert len(inputs) == 1 and inputs[0].get("text") == "Kiem tra nhap"
    assert len(first(tree, COMMENTS.post_comment_button)) == 1
    tree, _ = capture(version, device, "comments_production_cleared")
    inputs = first(tree, COMMENTS.comment_input)
    assert comment_composer_is_empty(
        [SimpleNamespace(text=n.get("text"), attrib=n.attrib) for n in inputs]
    )
    assert not first(tree, COMMENTS.post_comment_button)


@pytest.mark.parametrize("version,device", BUILDS)
def test_gallery_and_editor_next_are_distinct_even_when_old_grid_remains_in_xml(
    version, device
):
    apply_version_overrides("tiktok", version, package_name=PKG)
    set_active_locale("ko")
    gallery = "publish_video_selected" if version == "47.6.3" else "publish_selected"
    editor = "publish_video_editor" if version == "47.6.3" else "publish_editor_stable"
    tree, xml = capture(version, device, gallery)
    assert len(first(tree, PICKER.gallery_first_item)) == 1
    assert PICKER.has_gallery_picker_marker(xml)
    assert len(first(tree, PICKER.next_btn)) == 1
    tree, xml = capture(version, device, editor)
    assert not first(tree, PICKER.gallery_first_item)
    assert not PICKER.has_gallery_picker_marker(xml)
    found = first(tree, PICKER.next_btn)
    assert len(found) == 1
    assert found[0].get("resource-id").split(":id/")[-1] not in ("y4k", "y3s", "y1w")
    assert len(first(tree, EDITOR.sound_remove_btn)) == 1


@pytest.mark.parametrize("version,device", BUILDS)
def test_caption_targets_description_and_post_button_is_never_story_or_draft(
    version, device
):
    apply_version_overrides("tiktok", version, package_name=PKG)
    set_active_locale("ko")
    tree, xml = capture(version, device, "publish_composer")
    inputs = first(tree, COMPOSER.caption_input)
    assert len(inputs) == 1
    assert "설명" in inputs[0].get("hint", "")
    assert COMPOSER.has_post_screen_marker(xml)
    post = first(tree, COMPOSER.post_btn)
    assert len(post) == 1 and post[0].get("text") == "게시"
    sound_state = (
        "publish_video_no_sound" if version == "47.6.3" else "publish_editor_no_sound"
    )
    tree, _ = capture(version, device, sound_state)
    assert first(tree, EDITOR.sound_chip)
    assert not first(tree, EDITOR.sound_remove_btn)


def test_standard_patch_is_exact_build_and_restores_lite_catalog():
    apply_version_overrides("tiktok", "47.5.3")
    before = list(COMMENTS._sheet_indicator_base)
    apply_version_overrides("tiktok", "47.6.3", package_name=PKG)
    assert COMMENTS._post_comment_button_strict
    apply_version_overrides(
        "tiktok", "47.5.3", package_name="com.ss.android.ugc.tiktok.lite"
    )
    assert COMMENTS._sheet_indicator_base == before
    assert not COMMENTS._post_comment_button_strict
    tree = parse_ui_dump(
        (ROOT.parent / "tt4753_ko_lite_comment_composer.xml").read_text(
            encoding="utf-8"
        )
    )
    set_active_locale("ko")
    assert first(tree, COMMENTS.post_comment_button)
    apply_version_overrides("tiktok", "47.6.4", package_name=PKG)
    assert not COMMENTS._post_comment_button_strict  # no guessed build inheritance


def test_mandatory_marketing_consent_stops_without_tapping_allow():
    tree, _ = capture("47.5.3", "W15J", "marketing_back")
    families = popup_families(lambda selectors: bool(first(tree, selectors)))
    assert "manual_consent" in families
    handler = PopupHandler(object(), object())
    handler.detect = lambda screen=None: families
    with pytest.raises(RuntimeError, match="marketing-consent"):
        handler.close_all()


def test_live_lite_feed_still_uses_lite_controls_after_standard_catalog():
    apply_version_overrides("tiktok", "47.6.3", package_name=PKG)
    apply_version_overrides(
        "tiktok", "47.5.3", package_name="com.ss.android.ugc.tiktok.lite"
    )
    set_active_locale("ko")
    tree, _ = capture("47.5.3", "7WKJ", "lite_back")
    for selectors in (
        NAVIGATION_SELECTORS.home_tab,
        NAVIGATION_SELECTORS.create_button,
        ENGAGEMENT.like_button,
        ENGAGEMENT.comment_button,
    ):
        found = first(tree, selectors)
        assert len(found) == 1
        assert found[0].get("package") == "com.ss.android.ugc.tiktok.lite"
    assert not COMMENTS._post_comment_button_strict


def test_create_directly_opening_gallery_skips_the_camera_upload_tap():
    from types import SimpleNamespace
    from taktik.core.social_media.tiktok.services.publish.navigation import (
        tap_upload_button,
    )

    apply_version_overrides("tiktok", "47.6.3", package_name=PKG)
    _, xml = capture("47.6.3", "QNBP", "publish_camera")
    # No xpath/click API: finding the actual grid is sufficient evidence here.
    assert tap_upload_button(SimpleNamespace(dump_hierarchy=lambda **kw: xml))
