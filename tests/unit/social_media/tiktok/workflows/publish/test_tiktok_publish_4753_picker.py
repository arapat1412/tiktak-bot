"""The TikTok 47.5.3 gallery, from the failed capture of 2026-10-29 (com.ss.android.ugc.trill,
English).

The screenshot showed the gallery open while the run reported `gallery_not_opened`: the inherited
47.0.3 override looked for the selection box `l34`, which 47.5.3 does not draw. The first cell's
button is `l3z` [275,362][341,428], inside the cell under `viewpager_choose_media`; Next is `y3s`
[551,2313][1047,2434]. The fixture is a minimal anonymized excerpt of that dump, with Next enabled
as it is once the first cell is ticked.

The production detector and navigation functions run on it through `ScreenPhone`, which reads the
XPath exactly as the phone does and hit-tests each tap. The 47.0.3 and 43.1.4 captures stay in the
list, so the override must still find them.
"""

import pytest
from screen_phone import ScreenPhone

from taktik.core.compat.selectors.setup import apply_version_overrides
from taktik.core.shared.device.ui_dump import parse_ui_dump
from taktik.core.social_media.tiktok.services.publish.navigation import (
    POST_SCREEN_NOT_REACHED,
    advance_to_post_screen,
    select_first_gallery_item,
)
from taktik.core.social_media.tiktok.services.publish.screen_detector import (
    is_gallery_picker_open,
)
from taktik.core.social_media.tiktok.ui.selectors.flows.publish import (
    PUBLISH_MEDIA_PICKER_SELECTORS,
)
from taktik.core.social_media.tiktok.ui.selectors.locales import set_active_locale
from unit.paths import CORE

FIXTURES = CORE / "tests/unit/social_media/tiktok/fixtures"

GALLERY_47_5_3 = "tt4753_en_publish_gallery.xml"
CAMERA_47_5_3 = "tt4753_en_publish_camera.xml"
GALLERY_47_0_3 = "tt4703_fr_publish_gallery.xml"
GALLERY_SELECTED_47_0_3 = "tt4703_fr_publish_gallery_selected.xml"
GALLERY_43_1_4 = "tt4314_fr_publish_gallery.xml"


def _screen(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _phone(name: str) -> ScreenPhone:
    return ScreenPhone("screen", {"screen": name}, {})


def _first_match(name: str, xpaths):
    """(resource-id after `:id/`, bounds) of what the first matching xpath finds, or None."""
    tree = parse_ui_dump(_screen(name))
    for xpath in xpaths:
        nodes = tree.xpath(xpath)
        if nodes:
            return nodes[0].get("resource-id", "").split(":id/")[-1], nodes[0].get(
                "bounds"
            )
    return None


@pytest.fixture(autouse=True)
def english():
    set_active_locale("en")
    yield
    set_active_locale(None)


@pytest.fixture
def on_47_5_3():
    apply_version_overrides("tiktok", "47.5.3")
    yield
    apply_version_overrides("tiktok", "43.1.4")


def test_the_baseline_does_not_see_the_47_5_3_gallery():
    """The defect of 2026-10-29: the gallery is on screen and the run says it is not."""
    assert not is_gallery_picker_open(_phone(GALLERY_47_5_3))
    assert (
        _first_match(GALLERY_47_5_3, PUBLISH_MEDIA_PICKER_SELECTORS.gallery_first_item)
        is None
    )


def test_on_47_5_3_the_gallery_is_open_by_its_first_cell(on_47_5_3):
    assert is_gallery_picker_open(_phone(GALLERY_47_5_3))


def test_on_47_5_3_the_first_cell_is_the_l3z_button_at_its_real_bounds(on_47_5_3):
    phone = _phone(GALLERY_47_5_3)

    assert select_first_gallery_item(phone)
    assert phone.tapped() == ["l3z"]
    assert phone.taps[0].bounds == "[275,362][341,428]"


def test_on_47_5_3_the_l3z_xpath_is_exact_and_inside_the_gallery(on_47_5_3):
    """An `l3z` outside the pager and an `l3z0` beside the real button must not win."""
    decoy = (
        "<hierarchy>"
        '<node class="android.widget.Button" resource-id="com.x:id/l3z" bounds="[0,0][40,40]" />'
        '<node resource-id="com.x:id/viewpager_choose_media">'
        '<node class="android.widget.Button" resource-id="com.x:id/l3z0" bounds="[50,50][90,90]" />'
        '<node class="android.widget.Button" resource-id="com.x:id/l3z" '
        'bounds="[275,362][341,428]" />'
        "</node>"
        "</hierarchy>"
    )

    nodes = parse_ui_dump(decoy).xpath(
        next(
            xpath
            for xpath in PUBLISH_MEDIA_PICKER_SELECTORS.gallery_first_item
            if '"l3z"' in xpath
        )
    )

    assert [(node.get("resource-id"), node.get("bounds")) for node in nodes] == [
        ("com.x:id/l3z", "[275,362][341,428]")
    ]


def test_on_47_5_3_next_is_the_y3s_button(on_47_5_3):
    phone = _phone(GALLERY_47_5_3)

    assert advance_to_post_screen(phone, attempts=1, sleep=lambda _seconds: None) == (
        POST_SCREEN_NOT_REACHED
    )
    assert phone.tapped() == ["y3s"]
    assert phone.taps[0].bounds == "[551,2313][1047,2434]"


def test_on_47_5_3_the_camera_is_not_taken_for_the_gallery(on_47_5_3):
    """The same dump carries the camera's upload entry; the gallery selector must ignore it."""
    phone = _phone(CAMERA_47_5_3)

    assert not is_gallery_picker_open(phone)
    assert not select_first_gallery_item(phone, log=lambda _level, _message: None)
    assert phone.taps == []
    assert _first_match(CAMERA_47_5_3, PUBLISH_MEDIA_PICKER_SELECTORS.upload_btn)[
        0
    ] == ("upload_hot_area")


def test_on_47_5_3_the_47_0_3_gallery_is_still_selected(on_47_5_3):
    phone = _phone(GALLERY_47_0_3)

    assert is_gallery_picker_open(phone)
    assert select_first_gallery_item(phone)
    assert phone.tapped() == ["l34"]


def test_on_47_5_3_the_43_1_4_gallery_is_still_seen(on_47_5_3):
    assert is_gallery_picker_open(_phone(GALLERY_43_1_4))
    assert (
        _first_match(GALLERY_43_1_4, PUBLISH_MEDIA_PICKER_SELECTORS.gallery_first_item)[
            0
        ]
        == "mub"
    )


def test_on_47_5_3_next_falls_back_to_the_47_0_3_gallery_button(on_47_5_3):
    phone = _phone(GALLERY_SELECTED_47_0_3)

    assert advance_to_post_screen(phone, attempts=1, sleep=lambda _seconds: None) == (
        POST_SCREEN_NOT_REACHED
    )
    assert phone.tapped() == ["xyk"]
