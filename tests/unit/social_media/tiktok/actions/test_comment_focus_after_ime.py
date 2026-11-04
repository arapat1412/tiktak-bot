from types import SimpleNamespace

from loguru import logger
import pytest

from taktik.core.social_media.tiktok.actions.atomic.interaction import (
    comment_actions as module,
)
from taktik.core.social_media.tiktok.ui.selectors.locales import (
    active_locale,
    set_active_locale,
)
from taktik.core.shared.device.ui_dump import parse_ui_dump


def test_ime_resize_refinds_composer_before_tap_and_typing(monkeypatch):
    state = {"switched": False, "focused": False, "text": ""}
    old, fresh = object(), object()
    action = object.__new__(module.CommentActions)
    action.device = state
    action.comment_selectors = module.COMMENT_SELECTORS
    action.logger = logger
    action._get_device_serial = lambda: "fixture-phone"
    action._human_like_delay = lambda _: None

    monkeypatch.setattr(
        module, "first_matching", lambda *a: [fresh if state["switched"] else old]
    )
    monkeypatch.setattr(
        module, "ensure_taktik_keyboard", lambda serial: state.update(switched=True)
    )

    def tap(device, element, **kwargs):
        assert element is fresh, "stale pre-IME coordinates must never be tapped"
        state["focused"] = True
        return True

    def type_checked(device, serial, text, **kwargs):
        assert state["focused"]
        state["text"] = text
        return True

    monkeypatch.setattr(module, "tap_element_human", tap)
    monkeypatch.setattr(module, "type_text_checked", type_checked)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    action._composer_holds = lambda text: state["text"] == text
    assert action._focus_and_type("controlled test")


def test_no_typing_when_composer_disappears_after_ime_switch(monkeypatch):
    state = {"switched": False}
    action = object.__new__(module.CommentActions)
    action.device = state
    action.comment_selectors = module.COMMENT_SELECTORS
    action.logger = logger
    action._get_device_serial = lambda: "fixture-phone"
    monkeypatch.setattr(
        module, "first_matching", lambda *a: [] if state["switched"] else [object()]
    )
    monkeypatch.setattr(
        module, "ensure_taktik_keyboard", lambda serial: state.update(switched=True)
    )
    monkeypatch.setattr(
        module,
        "type_text_checked",
        lambda *a, **k: pytest.fail("typing without composer"),
    )
    assert not action._focus_and_type("controlled test")


def test_focused_typed_composer_wins_over_background_hint():
    old = active_locale()
    set_active_locale("ko")
    try:
        tree = parse_ui_dump("""<hierarchy>
          <node class="android.widget.EditText" text="따듯한 말 한마디 해주세요..."
            hint="따듯한 말 한마디 해주세요..." focused="false" clickable="false"/>
          <node class="android.widget.EditText" text="controlled test"
            focused="true" clickable="true"/>
        </hierarchy>""")
        action = object.__new__(module.CommentActions)
        action.comment_selectors = module.COMMENT_SELECTORS

        def xpath(selector):
            return SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(text=n.get("text"), attrib=dict(n.attrib))
                    for n in tree.xpath(selector)
                ]
            )

        action.device = SimpleNamespace(xpath=xpath)
        assert action._composer_holds("controlled test")
        assert not action._composer_holds("different test")
    finally:
        set_active_locale(old)
