"""Regression captures from the Korean Lite phone's real publish attempt."""
from pathlib import Path

from lxml import etree

from taktik.core.social_media.tiktok.services.publish import dialogs
from taktik.core.social_media.tiktok.ui.selectors.flows.publish import (
    PublishMediaPickerSelectors, PublishEditorSelectors, PublishComposerSelectors,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def screen(name):
    from taktik.core.shared.device.ui_dump import parse_ui_dump
    return parse_ui_dump((FIXTURES / ("tt4753_ko_" + name + ".xml")).read_text(encoding="utf-8"))


def test_gallery_selects_media_and_skips_add_access_tile():
    tree = screen("lite_gallery")
    selectors = PublishMediaPickerSelectors()
    matches = tree.xpath(selectors.gallery_first_item[0])
    assert len(matches) == 1
    assert matches[0].get("resource-id").endswith("/oz5")
    assert matches[0].get("bounds") == "[364,596][716,953]"
    assert tree.xpath(" | ".join(selectors.next_btn))


def test_sound_cross_disappears_but_chip_remains():
    selectors = PublishEditorSelectors()
    before, after = screen("lite_photo_editor"), screen("lite_photo_editor_muted")
    assert before.xpath(" | ".join(selectors.sound_remove_btn))
    assert not after.xpath(" | ".join(selectors.sound_remove_btn))
    assert after.xpath(" | ".join(selectors.sound_chip))


def test_photo_description_is_not_title_and_submit_is_exact():
    selectors = PublishComposerSelectors()
    tree = screen("lite_photo_composer")
    assert tree.xpath(selectors.caption_input[0])[0].get("resource-id").endswith("/h_s")
    assert tree.xpath(selectors.post_btn[0])[0].get("text") == "게시"


def test_android_access_picker_returns_to_change_and_grants_media(monkeypatch):
    states = [screen("android_photo_access"), screen("lite_gallery"),
              screen("media_permission"), etree.ElementTree(etree.Element("hierarchy"))]
    actions = []
    class Result:
        def __init__(self, xpath):
            self.matches = states[0].xpath(xpath)
        def wait(self, timeout):
            return bool(self.matches)
        def click(self):
            actions.append(self.matches[0].get("resource-id"))
            states.pop(0)
    class Device:
        def xpath(self, xpath):
            return Result(xpath)
        def press(self, key):
            actions.append(key)
            states.pop(0)
    monkeypatch.setattr(dialogs.time, "sleep", lambda _: None)
    assert dialogs.resolve_media_access_dialog(Device())
    assert actions == ["back", "com.ss.android.ugc.tiktok.lite:id/jln",
                       "com.android.permissioncontroller:id/permission_allow_all_button"]


def test_public_confirmation_blocks_completion_and_matches_only_its_submit():
    from uiautomator2.xpath import XPathEntry
    from taktik.core.social_media.tiktok.services.publish.screen_detector import is_post_screen
    from taktik.core.social_media.tiktok.ui.selectors.locales import active_locale, set_active_locale
    from taktik.core.social_media.tiktok.ui.selectors.shell.navigation import NAVIGATION_SELECTORS
    old = active_locale()
    class Device:
        wait_timeout = 0
        def __init__(self):
            self.xpath = XPathEntry(self)
        def dump_hierarchy(self, **kwargs):
            return (FIXTURES / 'tt4753_ko_lite_public_confirm.xml').read_text(encoding='utf-8')
    try:
        set_active_locale('ko')
        device = Device()
        assert is_post_screen(device)
        selectors = PublishComposerSelectors()
        assert len(device.xpath(' | '.join(selectors.publish_confirm_btn)).all()) == 1
        # Android's own Home key never counts as TikTok's bottom navigation.
        sysui = etree.fromstring('<hierarchy><panel><button package="com.android.systemui" '
                                'content-desc="홈" clickable="true"/></panel></hierarchy>'.encode())
        assert not sysui.xpath(' | '.join(NAVIGATION_SELECTORS.bottom_nav_container))
    finally:
        set_active_locale(old)
