"""Anonymized real Lite 47.1.4/47.5.3 composer regressions; never send live text."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from loguru import logger

from taktik.core.shared.device.ui_dump import parse_ui_dump
from taktik.core.social_media.tiktok.actions.atomic.interaction import comment_actions as module
from taktik.core.social_media.tiktok.ui.selectors.locales import active_locale, set_active_locale
from taktik.core.social_media.tiktok.ui.selectors.surfaces.video.comments import COMMENT_SELECTORS

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PKG = "com.ss.android.ugc.tiktok.lite:id/"


def tree(name):
    return parse_ui_dump((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("locale", ["ko", "en", None])
@pytest.mark.parametrize("fixture,rid", [
    ("tt4714_ko_lite_comment_composer.xml", "d1s"),
    ("tt4753_ko_lite_comment_composer.xml", "d16"),
    ("tt4763_ko_lite_comment_composer.xml", "d2x"),
])
def test_measured_send_is_unique_inside_foreground_composer(locale, fixture, rid):
    before = active_locale()
    set_active_locale(locale)
    try:
        screen = tree(fixture)
        matches = next(screen.xpath(xp) for xp in COMMENT_SELECTORS.post_comment_button if screen.xpath(xp))
        assert len(matches) == 1
        assert matches[0].get("resource-id") == PKG + rid
        assert matches[0].get("enabled") == "true"
    finally:
        set_active_locale(before)


def test_old_korean_following_axis_selects_attachment_and_send():
    screen = tree("tt4753_ko_lite_comment_composer.xml")
    old = '//*[@content-desc="다른 사용자 멘션"]/following::android.widget.Button[starts-with(@content-desc,"@")][1]'
    assert [n.get("resource-id") for n in screen.xpath(old)] == [PKG+"l29", PKG+"d16"]


def test_standalone_first_comment_composer_is_gated_by_panel_input_and_send():
    screen = tree("tt4714_ko_lite_comment_composer.xml")
    selectors = COMMENT_SELECTORS._sheet_indicator_base
    assert any(screen.xpath(xp) for xp in selectors)
    # It has no comment-count header and cannot be recognized as a regular sheet.
    for missing in ("f32", "ekt", "d1s"):
        invalid = tree("tt4714_ko_lite_comment_composer.xml")
        for node in invalid.xpath('//*[@resource-id="'+PKG+missing+'"]'):
            node.set("resource-id", PKG+"unrelated")
        assert not any(invalid.xpath(xp) for xp in selectors)


def test_4714_regular_sheet_with_unlabelled_close_is_recognized():
    screen = tree("tt4714_ko_lite_comment_sheet.xml")
    assert any(screen.xpath(xp) for xp in COMMENT_SELECTORS._sheet_indicator_base)
    closed = next(screen.xpath(xp) for xp in COMMENT_SELECTORS.close_button if screen.xpath(xp))
    assert len(closed) == 1 and closed[0].get("resource-id") == PKG + "bs8"
    assert closed[0].get("content-desc") == ""
    for missing in ("im6","wo5","bs8"):
        invalid = tree("tt4714_ko_lite_comment_sheet.xml")
        for node in invalid.xpath('//*[@resource-id="'+PKG+missing+'"]'):
            node.set("resource-id", PKG+"unrelated")
        assert not any(invalid.xpath(xp) for xp in COMMENT_SELECTORS._sheet_indicator_base)


@pytest.mark.parametrize("fixture", ["tt4714_ko_lite_comment_composer.xml", "tt4753_ko_lite_comment_composer.xml", "tt4763_ko_lite_comment_composer.xml"])
def test_known_send_is_not_selected_when_disabled_or_outside_its_composer(fixture):
    screen = tree(fixture)
    selectors = COMMENT_SELECTORS._post_comment_button_base
    matches = [n for xp in selectors for n in screen.xpath(xp)]
    assert len(matches) == 1
    matches[0].set("enabled", "false")
    assert not any(screen.xpath(xp) for xp in selectors)
    matches[0].set("enabled", "true")
    for node in screen.xpath('//android.widget.EditText'):
        node.set("resource-id", PKG+"unrelated")
    assert not any(screen.xpath(xp) for xp in selectors)


def test_plain_feed_hint_does_not_count_as_a_comment_surface():
    screen = parse_ui_dump('<hierarchy><node class="android.widget.EditText" '
                           'package="com.ss.android.ugc.tiktok.lite" resource-id="'+PKG+'ekt" '
                           'focused="true" text="test"/></hierarchy>')
    assert not any(screen.xpath(xp) for xp in COMMENT_SELECTORS._sheet_indicator_base)


@pytest.mark.parametrize("send_count,emptied,expected,taps", [(2,False,False,0),(1,False,False,1),(1,True,True,1)])
def test_uncertain_send_is_never_retried_and_ambiguous_control_is_not_tapped(
    monkeypatch, send_count, emptied, expected, taps
):
    action = object.__new__(module.CommentActions)
    action.device = object()
    action.logger = logger
    action.comment_selectors = SimpleNamespace(post_comment_button=["send"], comment_input=["input"])
    action.is_comment_sheet_open = lambda: True
    action._focus_and_type = lambda text: True
    action._human_like_delay = lambda *args: None
    send = [object() for _ in range(send_count)]
    typed = SimpleNamespace(text="unsent test", attrib={})
    monkeypatch.setattr(module, "first_matching", lambda device, selectors: send if selectors == ["send"] else [typed])
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    clicked = []

    def tap(device, target, **kwargs):
        clicked.append(target)
        if emptied:
            typed.text = ""
        return True

    monkeypatch.setattr(module, "tap_element_human", tap)
    assert action.post_comment("unsent test", single_attempt=True) is expected
    assert len(clicked) == taps


def test_4763_background_mention_does_not_select_attachment_as_send():
    screen = tree("tt4763_ko_lite_comment_composer.xml")
    old = '//*[@content-desc="다른 사용자 멘션"]/following::android.widget.Button[starts-with(@content-desc,"@")][1]'
    assert [n.get("resource-id") for n in screen.xpath(old)] == [PKG+"l1l", PKG+"d2x"]
    matches = next(screen.xpath(xp) for xp in COMMENT_SELECTORS._post_comment_button_base if screen.xpath(xp))
    assert len(matches) == 1
    assert matches[0].get("resource-id") == PKG+"d2x"
    assert matches[0].get("bounds") == "[900,1280][1046,1370]"
    for node in screen.xpath('//android.widget.EditText'):
        node.set("focused", "false")
    assert not any(screen.xpath(xp) for xp in COMMENT_SELECTORS._post_comment_button_base)
