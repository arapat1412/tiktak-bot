from pathlib import Path

import pytest
from uiautomator2.xpath import XPathEntry

from taktik.core.social_media.tiktok.services.profile.profile_actions import STANDARD_PROFILE_PROMPTS
from taktik.core.social_media.tiktok.ui.selectors.locales import ko

FIXTURES = Path(__file__).parents[1] / "fixtures" / "standard"


class Screen:
    wait_timeout = 0
    def __init__(self, xml):
        self.xml = xml
        self.xpath = XPathEntry(self)

    def dump_hierarchy(self, *args, **kwargs):
        return self.xml


@pytest.mark.parametrize("name,index,label", [
    ("ko_4643_save_login.xml", 0, "나중에"),
    ("ko_4643_facebook_permission.xml", 1, "허용 안 함"),
])
def test_optional_profile_prompts_only_select_negative_choice(name, index, label):
    xml = (FIXTURES / name).read_text(encoding="utf-8")
    screen = Screen(xml)
    matches = screen.xpath(STANDARD_PROFILE_PROMPTS[index][0]).all()
    assert len(matches) == 1
    assert matches[0].text == label
    # The same button without its specific dialog must never be selected.
    screen.xml = xml.replace("com.ss.android.ugc.trill:id/visual_area", "unrelated")
    assert not screen.xpath(STANDARD_PROFILE_PROMPTS[index][0]).exists


def test_standard_korean_profile_handle_is_readable():
    screen = Screen((FIXTURES / "ko_4763_own_profile.xml").read_text(encoding="utf-8"))
    matches = screen.xpath(ko.STRINGS["profile.username_anchors"][0]).all()
    assert [m.text for m in matches] == ["@chotuiandi"]


def test_standard_4643_camera_upload_control():
    from taktik.core.social_media.tiktok.ui.selectors.flows.publish import PUBLISH_MEDIA_PICKER_SELECTORS
    screen = Screen((FIXTURES / "ko_4643_camera.xml").read_text(encoding="utf-8"))
    matches = screen.xpath(" | ".join(PUBLISH_MEDIA_PICKER_SELECTORS.upload_btn)).all()
    assert len(matches) == 1
    assert matches[0].attrib["resource-id"].endswith("/upload_hot_area")


def test_standard_4643_gallery_selects_only_first_thumbnail():
    from taktik.core.social_media.tiktok.ui.selectors.flows.publish import PUBLISH_MEDIA_PICKER_SELECTORS as selectors
    xml = (FIXTURES / "ko_4643_gallery.xml").read_text(encoding="utf-8")
    assert selectors.has_gallery_picker_marker(xml)
    matches = Screen(xml).xpath(" | ".join(selectors.gallery_first_item)).all()
    assert len(matches) == 1
    assert matches[0].attrib["resource-id"].endswith("/ofk")


def test_standard_photo_caption_targets_description_before_title():
    from taktik.core.social_media.tiktok.ui.selectors.flows.publish import PUBLISH_COMPOSER_SELECTORS as selectors
    screen = Screen((FIXTURES / "ko_4643_photo_composer.xml").read_text(encoding="utf-8"))
    first = next(screen.xpath(s).all()[0] for s in selectors.caption_input if screen.xpath(s).exists)
    assert first.attrib["resource-id"].endswith("/h00")


def test_standard_editor_sound_cross_disappears_after_removal():
    from taktik.core.social_media.tiktok.ui.selectors.flows.publish import PUBLISH_EDITOR_SELECTORS as selectors
    before = Screen((FIXTURES / "ko_4643_editor.xml").read_text(encoding="utf-8"))
    after = Screen((FIXTURES / "ko_4643_editor_muted.xml").read_text(encoding="utf-8"))
    assert len(before.xpath(" | ".join(selectors.sound_remove_btn)).all()) == 1
    assert not after.xpath(" | ".join(selectors.sound_remove_btn)).exists


def test_samsung_widget_prompt_only_selects_cancel():
    screen = Screen((FIXTURES / "ko_samsung_add_widget.xml").read_text(encoding="utf-8"))
    matches = screen.xpath(" | ".join(ko.STRINGS["publish_editor.popup_cancel_buttons"])).all()
    assert len(matches) == 1
    assert matches[0].text == "취소"


def test_clickable_disabled_comment_send_is_never_tapped(monkeypatch):
    from unittest.mock import Mock
    from taktik.core.social_media.tiktok.actions.atomic.interaction import comment_actions as module
    from taktik.core.social_media.tiktok.ui.selectors.surfaces.video.comments import COMMENT_SELECTORS
    screen = Screen((FIXTURES / "ko_4643_comment_send_disabled.xml").read_text(encoding="utf-8"))
    actions = object.__new__(module.CommentActions)
    actions.device = screen
    actions.logger = Mock()
    actions.comment_selectors = COMMENT_SELECTORS
    actions.is_comment_sheet_open = lambda: True
    actions._focus_and_type = lambda text: True
    injection = Mock(side_effect=AssertionError("disabled controls must not be tapped"))
    monkeypatch.setattr(module, "tap_element_human", injection)
    assert not actions.post_comment("good", single_attempt=True)
    assert actions.last_comment_send_attempted is False
    assert actions.last_comment_skip_reason == "send_disabled"
    injection.assert_not_called()
