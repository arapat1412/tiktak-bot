"""Lite 47.5.3 controls measured during the authorized 2026-11-01 publication test."""

import pytest

from taktik.core.compat.selectors.setup import apply_version_overrides
from taktik.core.shared.device.ui_dump import parse_ui_dump
from taktik.core.social_media.tiktok.ui.selectors.flows.publish import (
    PUBLISH_MEDIA_PICKER_SELECTORS as PICKER,
    PUBLISH_EDITOR_SELECTORS as EDITOR,
    PUBLISH_COMPOSER_SELECTORS as COMPOSER,
)
from taktik.core.social_media.tiktok.ui.selectors.locales import (
    active_locale,
    set_active_locale,
)

PKG = "com.ss.android.ugc.tiktok.lite"


@pytest.fixture(autouse=True)
def lite_version():
    old = active_locale()
    set_active_locale("ko")
    apply_version_overrides("tiktok", "47.5.3")
    yield
    apply_version_overrides("tiktok", "43.1.4")
    set_active_locale(old)


def tree(xml):
    return parse_ui_dump("<hierarchy>" + xml.replace("PKG", PKG) + "</hierarchy>")


def test_gallery_selection_is_scoped_and_takes_only_newest_cell():
    screen = tree("""<node resource-id="PKG:id/viewpager_choose_media">
      <node class="android.widget.GridView" resource-id="PKG:id/jnt">
        <node class="android.widget.Button" resource-id="PKG:id/l45" bounds="[273,362][341,430]"/>
        <node class="android.widget.Button" resource-id="PKG:id/l45" bounds="[630,362][698,430]"/>
      </node></node><node class="android.widget.Button" resource-id="PKG:id/l45"/>""")
    hits = screen.xpath(PICKER.gallery_first_item[0])
    assert len(hits) == 1
    assert hits[0].get("bounds") == "[273,362][341,430]"
    assert PICKER.has_gallery_picker_marker('resource-id="' + PKG + ':id/jnt"')


def test_editor_sound_cross_does_not_match_generic_close_or_sound_picker():
    screen = tree("""<node resource-id="PKG:id/e1f" clickable="true">
      <node resource-id="PKG:id/e1g" content-desc="닫기"/></node>
      <node resource-id="PKG:id/e1r" clickable="true"/>
      <node resource-id="PKG:id/l5s" content-desc="닫기"/>""")
    hits = screen.xpath(EDITOR.sound_remove_btn[0])
    assert len(hits) == 1
    assert hits[0].get("resource-id") == PKG + ":id/e1f"


def test_gallery_and_editor_next_never_match_story_publish_control():
    screen = tree(
        """<node class="android.widget.Button" resource-id="PKG:id/y3z" text="다음"/>
      <node class="android.widget.TextView" resource-id="PKG:id/q2d" text="다음"/>
      <node class="android.widget.TextView" resource-id="PKG:id/tv_quick_publish" text="스토리"/>"""
    )
    hits = {n.get("resource-id") for xp in PICKER.next_btn for n in screen.xpath(xp)}
    assert PKG + ":id/y3z" in hits and PKG + ":id/q2d" in hits
    assert PKG + ":id/tv_quick_publish" not in hits


def test_composer_controls_are_exact_and_distinct_from_drafts():
    screen = tree("""<node class="android.widget.EditText" resource-id="PKG:id/h_s"/>
      <node class="android.widget.Button" resource-id="PKG:id/tld" text="게시"/>
      <node class="android.widget.Button" resource-id="PKG:id/gk5" text="임시 저장"/>
      <node class="android.widget.Button" resource-id="PKG:id/tldx"/>""")
    assert len(screen.xpath(COMPOSER.caption_input[0])) == 1
    hits = screen.xpath(COMPOSER.post_btn[0])
    assert len(hits) == 1 and hits[0].get("resource-id") == PKG + ":id/tld"


def test_post_publish_widget_cancel_requires_samsung_widget_dialog():
    cancel = '<node resource-id="com.sec.android.app.launcher:id/cancel_button"/>'
    widget = '<node resource-id="com.sec.android.app.launcher:id/add_item_title"/>'
    assert len(tree(widget + cancel).xpath(EDITOR.popup_cancel_buttons[0])) == 1
    assert not tree(cancel).xpath(EDITOR.popup_cancel_buttons[0])
