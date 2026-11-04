"""Measured 47.5.3 sound cross must not tap the old id, now the sound chooser."""

import pytest
from screen_phone import ScreenPhone

from taktik.core.compat.selectors.setup import apply_version_overrides
from taktik.core.social_media.tiktok.services.publish import navigation
from taktik.core.social_media.tiktok.services.publish.editor_sound import (
    remove_attached_sound,
    SOUND_KEPT,
)
from taktik.core.social_media.tiktok.ui.selectors.flows.publish import (
    PUBLISH_COMPOSER_SELECTORS,
)
from taktik.core.social_media.tiktok.ui.selectors.locales import set_active_locale

SCREENS = {
    "gallery": "tt4753_en_publish_gallery.xml",
    "sound": "tt4753_en_publish_editor_sound.xml",
    "silent": "tt4753_en_publish_editor_no_sound.xml",
    "composer": "tt4753_en_publish_composer.xml",
}
MOVES = {
    ("gallery", "y3s"): "sound",
    ("sound", "e1l"): "silent",
    ("silent", "q25"): "composer",
}


@pytest.fixture(autouse=True)
def version():
    apply_version_overrides("tiktok", "47.5.3")
    set_active_locale("en")
    yield
    apply_version_overrides("tiktok", "43.1.4")
    set_active_locale(None)


def test_sound_removed_before_next_without_opening_sound_chooser_or_story():
    phone = ScreenPhone("sound", SCREENS, MOVES)
    assert (
        navigation.advance_to_post_screen(phone, sleep=lambda _: None)
        == navigation.POST_SCREEN_REACHED
    )
    assert phone.tapped() == ["e1l", "q25"]
    assert phone.screen == "composer"


def test_gallery_selection_advances_through_editor_to_composer():
    phone = ScreenPhone("gallery", SCREENS, MOVES)
    assert navigation.select_first_gallery_item(phone)
    assert (
        navigation.advance_to_post_screen(phone, sleep=lambda _: None)
        == navigation.POST_SCREEN_REACHED
    )
    assert phone.tapped() == ["l3z", "y3s", "e1l", "q25"]


def test_sound_that_cannot_be_removed_still_blocks_next():
    phone = ScreenPhone("sound", SCREENS, {})
    assert remove_attached_sound(phone, sleep=lambda _: None) == SOUND_KEPT
    assert phone.tapped() == ["e1l", "e1l"]


def test_composer_controls_are_caption_and_post_not_editor_or_drafts():
    phone = ScreenPhone("composer", SCREENS, {})
    tree = phone.tree()
    for selectors, expected in (
        (PUBLISH_COMPOSER_SELECTORS.caption_input, "h_n"),
        (PUBLISH_COMPOSER_SELECTORS.post_btn, "tl7"),
    ):
        match = next(tree.xpath(xpath)[0] for xpath in selectors if tree.xpath(xpath))
        assert match.get("resource-id").endswith(":id/" + expected)
    assert not any(
        phone.tree().xpath(xpath)
        for xpath in PUBLISH_COMPOSER_SELECTORS.caption_input
        if "h8e" in xpath
    )
