"""The composer emptiness proof and the comment sheet closing sequence.

`comment_composer_is_empty` is the single proof a comment left the field. Android can paint the
input's HINT as its text, so a text equal to the hint is empty; an absent or unreadable field is
unknown, never proof. `post_comment` confirms on that helper, not on "our submitted text
disappeared": a different real draft still sitting in the field is not a sent comment.

`close_comments` taps Close, then presses Back at most three times, re-reading the sheet before
each press. The IME and an overlay can consume Back; no further Back is sent once the sheet closes.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from taktik.core.social_media.tiktok.actions.atomic.interaction import (
    comment_actions as module,
)
from taktik.core.social_media.tiktok.actions.atomic.interaction.comment_actions import (
    CommentActions,
    comment_composer_is_empty,
)
from taktik.core.social_media.tiktok.ui.selectors.surfaces.video.comments import (
    COMMENT_SELECTORS,
)


@pytest.fixture(autouse=True)
def _instant_waits(monkeypatch):
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)


# --- the shared emptiness helper -------------------------------------------------------------


def _node(text, hint=None):
    return SimpleNamespace(text=text, attrib={} if hint is None else {"hint": hint})


class _Unreadable:
    attrib = {}

    @property
    def text(self):
        raise RuntimeError("the dump could not be read")


@pytest.mark.parametrize(
    "inputs, expected",
    [
        ([], False),
        ([_Unreadable()], False),
        ([_node("")], True),
        ([_node("Add comment...", "Add comment...")], True),
        ([_node("Add comment...", "Add comment... ")], True),
        ([_node("Xin chào")], False),
        ([_node("Xin chào", "Add comment...")], False),
        ([_node(""), _node("Xin chào")], False),
    ],
)
def test_composer_is_empty_only_for_the_hint_or_no_text(inputs, expected):
    assert comment_composer_is_empty(inputs) is expected


# --- post_comment confirms on the helper, not on the submitted text vanishing -----------------


def _post_actions(monkeypatch, composer_after_send):
    actions = CommentActions.__new__(CommentActions)
    actions.device = object()
    actions.logger = Mock()
    actions.comment_selectors = COMMENT_SELECTORS
    actions.is_comment_sheet_open = lambda: True
    actions._focus_and_type = lambda text: True
    actions._human_like_delay = lambda action_type="general": None
    send = Mock()

    def lookup(_device, selectors):
        if selectors == COMMENT_SELECTORS.post_comment_button:
            return [send]
        if selectors == COMMENT_SELECTORS.comment_input:
            return composer_after_send
        return []

    monkeypatch.setattr(module, "first_matching", lookup)
    monkeypatch.setattr(module, "tap_element_human", Mock(return_value=True))
    return actions, send


def test_post_comment_confirms_when_only_the_hint_remains(monkeypatch):
    actions, _ = _post_actions(monkeypatch, [_node("Add comment...", "Add comment...")])

    assert actions.post_comment("Xin chào") is True


def test_post_comment_does_not_confirm_a_different_real_draft(monkeypatch):
    """The submitted text DID disappear; the field still holds someone else's draft."""
    actions, _ = _post_actions(monkeypatch, [_node("brouillon", "Add comment...")])

    assert actions.post_comment("Xin chào") is False


def test_post_comment_cannot_confirm_a_missing_field(monkeypatch):
    actions, _ = _post_actions(monkeypatch, [])

    assert actions.post_comment("Xin chào") is False


# --- close_comments: Close first, then at most two Backs, re-reading the sheet ---------------


class _Query:
    def __init__(self, nodes=()):
        self._nodes = list(nodes)

    def all(self):
        return self._nodes


class _Node:
    def __init__(self, text=""):
        self.text = text


class _Feed:
    """A fake screen that knows whether the comment sheet panel is up.

    `back_closes_after` is how many Backs are swallowed before the sheet closes: 1 models a first
    Back that only hides the IME, 0 closes at once, None is a stuck sheet.
    """

    def __init__(self, *, sheet_open, back_closes_after=0):
        self.sheet_open = sheet_open
        self.back_closes_after = back_closes_after
        self.presses = []

    def xpath(self, selector):
        if selector in COMMENT_SELECTORS.sheet_indicator:
            return _Query([_Node()] if self.sheet_open else [])
        return _Query()

    def press(self, key):
        self.presses.append(key)
        if (
            self.back_closes_after is not None
            and len(self.presses) > self.back_closes_after
        ):
            self.sheet_open = False


def _close_actions(device, find_and_click):
    actions = CommentActions.__new__(CommentActions)
    actions.device = device
    actions.logger = Mock()
    actions.comment_selectors = COMMENT_SELECTORS
    actions._find_and_click = find_and_click
    return actions


def test_close_button_dismisses_the_sheet_without_pressing_back():
    feed = _Feed(sheet_open=True)
    find_and_click = Mock(side_effect=lambda selectors, timeout: _click_close(feed))
    actions = _close_actions(feed, find_and_click)

    assert actions.close_comments() is True
    assert feed.presses == []
    find_and_click.assert_called_once_with(COMMENT_SELECTORS.close_button, timeout=3)


def test_a_back_that_only_hides_the_ime_is_followed_by_one_that_closes_the_sheet():
    feed = _Feed(sheet_open=True, back_closes_after=1)
    actions = _close_actions(feed, Mock(return_value=False))

    assert actions.close_comments() is True
    assert feed.presses == ["back", "back"]


def test_no_second_back_once_the_first_one_closed_the_sheet():
    feed = _Feed(sheet_open=True, back_closes_after=0)
    actions = _close_actions(feed, Mock(return_value=False))

    assert actions.close_comments() is True
    assert feed.presses == ["back"]


def test_overlay_and_ime_can_consume_back_before_sheet_closes():
    feed = _Feed(sheet_open=True, back_closes_after=2)
    actions = _close_actions(feed, Mock(return_value=False))
    assert actions.close_comments() is True
    assert feed.presses == ["back", "back", "back"]


def test_a_stuck_sheet_gets_three_backs_and_reports_failure():
    feed = _Feed(sheet_open=True, back_closes_after=None)
    actions = _close_actions(feed, Mock(return_value=False))

    assert actions.close_comments() is False
    assert feed.presses == ["back", "back", "back"]


def _click_close(feed):
    feed.sheet_open = False
    return True
