"""Production readers on anonymized Korean 47.5.3 phone captures; no public actions."""

from pathlib import Path

import pytest
from uiautomator2.xpath import XPathEntry

from taktik.core.compat.selectors.setup import apply_version_overrides
from taktik.core.shared.device.ui_dump import parse_ui_dump
from taktik.core.social_media.tiktok.actions.atomic.detection.detection_actions import (
    DetectionActions,
)
from taktik.core.social_media.tiktok.actions.atomic.interaction.comment_actions import (
    CommentActions,
    comment_composer_is_empty,
)
from taktik.core.social_media.tiktok.actions.base.utils import first_matching
from taktik.core.social_media.tiktok.services.publish.screen_detector import (
    is_gallery_picker_open,
    is_post_screen,
)
from taktik.core.social_media.tiktok.ui.selectors import (
    NAVIGATION_SELECTORS,
    VIDEO_SELECTORS,
)
from taktik.core.social_media.tiktok.ui.selectors.flows.publish import (
    PUBLISH_MEDIA_PICKER_SELECTORS,
    PUBLISH_COMPOSER_SELECTORS,
    PUBLISH_EDITOR_SELECTORS,
)
from taktik.core.social_media.tiktok.ui.selectors.locales import set_active_locale

FIXTURES = Path(__file__).parents[1] / "fixtures"


class Phone:
    wait_timeout = 0.01
    serial = "fixture"

    def __init__(self, name):
        self.xml = (FIXTURES / f"tt4753_ko_{name}.xml").read_text(encoding="utf-8")
        self.xpath = XPathEntry(self)
        self.gestures = []

    def dump_hierarchy(self, *args, **kwargs):
        return self.xml

    def window_size(self):
        return 1080, 2520

    def click(self, *args):
        self.gestures.append(args)


@pytest.fixture(autouse=True)
def korean():
    set_active_locale("ko")
    apply_version_overrides("tiktok", "47.5.3")
    yield
    set_active_locale(None)
    apply_version_overrides("tiktok", "43.1.4")


def first(phone, selectors):
    tree = parse_ui_dump(phone.xml)
    return next((nodes[0] for xpath in selectors if (nodes := tree.xpath(xpath))), None)


def test_feed_is_video_and_not_comment_sheet():
    phone = Phone("feed")
    detection = DetectionActions(phone)
    screen = detection.read_screen()
    assert screen.kind == "video" and screen.for_you
    assert detection.get_video_author(screen) == "Creator"
    assert not CommentActions(phone).is_comment_sheet_open()
    assert first(phone, VIDEO_SELECTORS.like_button).get("resource-id").endswith("/g9b")
    assert (
        first(phone, VIDEO_SELECTORS.comment_button).get("resource-id").endswith("/epr")
    )
    assert (
        first(phone, VIDEO_SELECTORS.follow_button).get("resource-id").endswith("/ixi")
    )
    assert first(phone, NAVIGATION_SELECTORS.for_you_tab) is not None
    assert not phone.gestures


@pytest.mark.parametrize("name", ["comments_empty", "comments_populated"])
def test_both_empty_and_populated_sheets_have_empty_hint_input(name):
    phone = Phone(name)
    action = CommentActions(phone)
    assert action.is_comment_sheet_open()
    assert DetectionActions(phone).read_screen().kind == "comments"
    fields = first_matching(action.device, action.comment_selectors.comment_input)
    assert comment_composer_is_empty(fields)
    assert (
        first(phone, action.comment_selectors.close_button)
        .get("resource-id")
        .endswith("/bs2")
    )
    if name == "comments_populated":
        assert len(action.read_comments()) == 3
    assert not phone.gestures


def test_creation_entry_and_gallery_next():
    feed = Phone("feed")
    assert (
        first(feed, NAVIGATION_SELECTORS.create_button).get("content-desc") == "만들기"
    )
    assert not is_post_screen(Phone("publish_camera"))
    gallery = Phone("publish_gallery")
    assert is_gallery_picker_open(gallery)
    assert not is_post_screen(gallery)
    assert (
        first(gallery, PUBLISH_MEDIA_PICKER_SELECTORS.gallery_first_item)
        .get("resource-id")
        .endswith("/l3z")
    )
    assert (
        first(gallery, PUBLISH_MEDIA_PICKER_SELECTORS.next_btn)
        .get("resource-id")
        .endswith("/y3s")
    )


def test_avatar_fallback_removes_korean_profile_suffix():
    from lxml import etree

    phone = Phone("feed")
    root = etree.fromstring(phone.xml.encode())
    for node in root.xpath('//*[@resource-id="com.ss.android.ugc.trill:id/title"]'):
        node.getparent().remove(node)
    phone.xml = etree.tostring(root, encoding="unicode")
    assert DetectionActions(phone).get_video_author() == "Creator"


def test_real_hangul_draft_has_send_control_and_is_not_empty():
    phone = Phone("comments_draft")
    action = CommentActions(phone)
    assert action.is_comment_sheet_open()
    assert not comment_composer_is_empty(
        first_matching(action.device, action.comment_selectors.comment_input)
    )
    assert (
        first(phone, action.comment_selectors.post_comment_button)
        .get("resource-id")
        .endswith("/d1b")
    )
    assert not phone.gestures


def test_sheet_stays_open_when_android_marks_input_nonclickable():
    from lxml import etree

    phone = Phone("comments_populated")
    root = etree.fromstring(phone.xml.encode())
    for node in root.xpath('//node[@class="android.widget.EditText"]'):
        node.set("clickable", "false")
    phone.xml = etree.tostring(root, encoding="unicode")
    assert CommentActions(phone).is_comment_sheet_open()
    assert DetectionActions(phone).read_screen().kind == "comments"


@pytest.mark.parametrize(
    "text,count", [("6.3만", 63000), ("1.2억", 120000000), ("2천", 2000)]
)
def test_korean_compact_counts_preserve_filter_thresholds(text, count):
    from taktik.core.shared.actions.utils import ActionUtils, parse_count

    assert parse_count(text) == count
    assert ActionUtils.parse_number_from_text(text) == count


def test_detects_korean_on_captured_feed():
    from taktik.core.social_media.tiktok.ui import language

    try:
        assert language.detect_language(Phone("feed")) == "ko"
    finally:
        language.reset_detected_language()


def test_advertisement_is_recognised_in_korean():
    assert DetectionActions(Phone("ad")).read_screen().kind == "ad"


@pytest.mark.parametrize(
    "name",
    ["publish_camera", "publish_gallery", "publish_editor_sound", "publish_composer"],
)
def test_publish_surfaces_are_not_comment_sheets(name):
    assert not CommentActions(Phone(name)).is_comment_sheet_open()


def test_optimization_preserves_korean_and_neutral_fields():
    from dataclasses import dataclass, field
    from taktik.core.social_media.tiktok.ui import language

    @dataclass
    class Selectors:
        values: list = field(
            default_factory=lambda: [
                '//*[@text="Home"]',
                '//*[@text="Accueil"]',
                '//*[@content-desc="홈"]',
                '//*[@resource-id="pkg:id/home"]',
            ]
        )

    selectors = Selectors()
    assert language.optimize_selector_dataclass(selectors, "ko") == 2
    assert selectors.values == [
        '//*[@content-desc="홈"]',
        '//*[@resource-id="pkg:id/home"]',
    ]


def test_editor_next_does_not_select_story_and_remove_cross_is_known():
    editor = Phone("publish_editor_sound")
    assert not is_post_screen(editor)
    assert (
        first(editor, PUBLISH_MEDIA_PICKER_SELECTORS.next_btn)
        .get("resource-id")
        .endswith("/q25")
    )
    assert (
        first(editor, PUBLISH_EDITOR_SELECTORS.sound_remove_btn)
        .get("resource-id")
        .endswith("/e1l")
    )
    clean = Phone("publish_editor_no_sound")
    assert first(clean, PUBLISH_EDITOR_SELECTORS.sound_remove_btn) is None


def test_composer_caption_and_post_are_distinct_from_drafts():
    phone = Phone("publish_composer")
    assert is_post_screen(phone)
    assert (
        first(phone, PUBLISH_COMPOSER_SELECTORS.caption_input)
        .get("resource-id")
        .endswith("/h_n")
    )
    assert (
        first(phone, PUBLISH_COMPOSER_SELECTORS.post_btn)
        .get("resource-id")
        .endswith("/tl7")
    )
    assert not phone.gestures
