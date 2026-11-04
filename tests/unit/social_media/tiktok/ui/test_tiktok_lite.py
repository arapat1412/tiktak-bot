"""Minimal structural reproductions of Samsung Lite 47.5.3 dumps, 2026-11-01."""

import pytest

from taktik.core.clone.packages.package_map import belongs_to_platform
from taktik.core.compat.selectors.setup import apply_version_overrides
from taktik.core.shared.device.ui_dump import parse_ui_dump
from taktik.core.social_media.tiktok.ui.selectors.locales import active_locale, set_active_locale
from taktik.core.social_media.tiktok.ui.selectors.shell.navigation import NAVIGATION_SELECTORS
from taktik.core.social_media.tiktok.ui.selectors.shell.popups import LITE_REWARD_CLOSE_SELECTOR
from taktik.core.social_media.tiktok.ui.selectors.surfaces.video.comments import COMMENT_SELECTORS
from taktik.core.social_media.tiktok.ui.selectors.surfaces.video.engagement import VIDEO_ENGAGEMENT_SELECTORS

PKG = "com.ss.android.ugc.tiktok.lite"


def screen(inner):
    return parse_ui_dump(f'<hierarchy>{inner}</hierarchy>')


def node(rid, inner="", **attrs):
    attributes = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return f'<node class="android.widget.FrameLayout" package="{PKG}" resource-id="{PKG}:id/{rid}" {attributes}>{inner}</node>'


def test_lite_is_a_platform_variant():
    assert belongs_to_platform(PKG, "tiktok")


def test_shared_like_and_share_container_is_disambiguated_by_icon():
    tree = screen(node("g9g", node("g90")) + node("g9g", node("w8z")))
    matches = {el for xp in VIDEO_ENGAGEMENT_SELECTORS.like_button for el in tree.xpath(xp)}
    assert len(matches) == 1
    assert matches.pop().xpath(f'.//*[@resource-id="{PKG}:id/g90"]')


@pytest.mark.parametrize("language", ["en", "ko", None])
def test_lite_comment_gate_survives_same_version_full_app_override(language):
    old = active_locale()
    saved = list(COMMENT_SELECTORS._sheet_indicator_base)
    try:
        set_active_locale(language)
        apply_version_overrides("tiktok", "47.5.3")
        sheet = screen(node("ocq", node("wna") + node("brw") + node("ekg")))
        feed = screen(node("op8") + node("g9g", node("g90")))
        assert any(sheet.xpath(xp) for xp in COMMENT_SELECTORS.sheet_indicator)
        assert not any(feed.xpath(xp) for xp in COMMENT_SELECTORS.sheet_indicator)
    finally:
        apply_version_overrides("tiktok", "43.1.4")
        COMMENT_SELECTORS._sheet_indicator_base = saved
        set_active_locale(old)


def test_korean_home_does_not_click_android_navigation_when_popup_hides_app():
    old = active_locale()
    try:
        set_active_locale("ko")
        tree = screen('<node package="com.android.systemui" content-desc="홈" clickable="true"/>')
        assert not any(tree.xpath(xp) for xp in NAVIGATION_SELECTORS.home_tab)
    finally:
        set_active_locale(old)


def test_reward_close_requires_lite_campaign_and_unique_image():
    image = '<node class="android.widget.ImageView" bounds="[507,1513][573,1580]"/>'
    reward = screen(node("snb", node("sn6", image)))
    assert len(reward.xpath(LITE_REWARD_CLOSE_SELECTOR)) == 1
    assert not screen(node("sn6", image)).xpath(LITE_REWARD_CLOSE_SELECTOR)
    assert not screen(node("snb", node("sn6", image + image))).xpath(LITE_REWARD_CLOSE_SELECTOR)
