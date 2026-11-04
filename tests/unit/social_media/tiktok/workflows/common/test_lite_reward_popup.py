from pathlib import Path
from types import SimpleNamespace

from loguru import logger
import pytest

from taktik.core.shared.device.ui_dump import parse_bounds, parse_ui_dump
from taktik.core.social_media.tiktok.actions.atomic.interaction.popup_actions import (
    PopupActions,
)
from taktik.core.social_media.tiktok.workflows.common.popup_handler import PopupHandler
from taktik.core.social_media.tiktok.workflows.common import popup_handler

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures/tt4753_ko_lite_pig_reward.xml"
PIG = FIXTURE.read_text(encoding="utf-8")
FEED = '<hierarchy><node package="com.ss.android.ugc.tiktok.lite" resource-id="com.ss.android.ugc.tiktok.lite:id/op8"/></hierarchy>'


def football_reward(image_count=1):
    pkg = "com.ss.android.ugc.tiktok.lite"
    return (
        f'<hierarchy><node class="android.widget.FrameLayout" package="{pkg}" resource-id="{pkg}:id/sl8">'
        f'<node class="android.view.View" package="{pkg}" resource-id="{pkg}:id/sl1" content-desc="닫기" bounds="[0,0][1080,2205]"/>'
        f'<node class="android.widget.FrameLayout" package="{pkg}" resource-id="{pkg}:id/sl6">'
        f'<node class="android.view.ViewGroup" package="{pkg}" bounds="[200,979][881,1119]"/>'
        + f'<node class="android.widget.ImageView" package="{pkg}" bounds="[507,1513][573,1580]"/>' * image_count
        + '</node></node></hierarchy>'
    )


def compose_pig(bounds="[506,1663][574,1731]", close_count=1):
    package = 'package="com.ss.android.ugc.tiktok.lite"'
    return (
        f'<hierarchy><node class="androidx.compose.ui.platform.ComposeView" {package}>'
        f'<node class="android.view.View" {package}>'
        f'<node class="android.view.View" {package} text="돼지 저금통 깨고 획득하기"/>'
        f'<node class="android.view.View" {package} text="₩20,000"/>'
        f'<node class="android.view.View" {package} text="시작하기" clickable="true" bounds="[186,1359][894,1495]"/>'
        + f'<node class="android.view.View" {package} content-desc="Close" enabled="true" bounds="{bounds}"/>' * close_count
        + '</node></node></hierarchy>'
    )


class Phone:
    def __init__(self, xml, tap_ok=True, after_tap=FEED):
        self.xml = xml
        self.tree = parse_ui_dump(xml)
        self.taps = []
        self.dumps = 0
        self.tap_ok = tap_ok
        self.after_tap = after_tap

    def dump_hierarchy(self, **kwargs):
        self.dumps += 1
        return self.xml

    def app_current(self):
        return {"package": "com.ss.android.ugc.tiktok.lite"}

    def xpath(self, selector):
        return SimpleNamespace(
            all=lambda: [
                SimpleNamespace(bounds=parse_bounds(n.get("bounds", "")))
                for n in self.tree.xpath(selector)
            ]
        )

    def human_tap(self, bounds, **kwargs):
        self.taps.append(bounds)
        if self.tap_ok and self.after_tap is not None:
            self.xml = self.after_tap
            self.tree = parse_ui_dump(self.xml)
        return self.tap_ok


def actions(phone):
    action = object.__new__(PopupActions)
    action.device = phone
    action.logger = logger
    # No GDPR / dismiss / generic close polling is allowed on this known campaign.
    action._find_and_click = lambda *a, **k: pytest.fail("unrelated selector polling")
    return action


def test_real_pig_card_closes_via_only_the_bottom_x(monkeypatch):
    monkeypatch.setattr(popup_handler.time, "sleep", lambda _: None)
    phone = Phone(PIG)
    handler = PopupHandler(actions(phone), SimpleNamespace(device=phone))
    assert handler.close_all()
    assert phone.taps == [(507, 1623, 573, 1689)]
    assert phone.dumps == 2


def test_generic_popup_entry_also_prioritizes_lite_x():
    phone = Phone(PIG)
    assert actions(phone).close_popup()
    assert phone.taps == [(507, 1623, 573, 1689)]


@pytest.mark.parametrize(
    "xml",
    [
        '<hierarchy><node resource-id="com.ss.android.ugc.tiktok.lite:id/op8"/></hierarchy>',
        PIG.replace("com.ss.android.ugc.tiktok.lite", "com.example.foreign"),
    ],
)
def test_no_tap_on_feed_or_foreign_app(xml):
    phone = Phone(xml)
    assert not actions(phone).close_lite_reward_popup()
    assert phone.taps == []


def test_a_block_is_preserved_even_with_reward_card_present():
    phone = Phone(PIG)
    handler = PopupHandler(actions(phone), SimpleNamespace(device=phone))
    handler.detect = lambda screen=None: {"action_blocked", "lite_reward"}
    assert not handler.close_all()
    assert phone.taps == []


def test_reward_tree_behind_a_foreign_foreground_is_not_tapped():
    phone = Phone(PIG)
    phone.app_current = lambda: {"package": "com.android.settings"}
    assert not actions(phone).close_lite_reward_popup()
    assert phone.taps == []


def test_failed_reward_tap_never_falls_through_to_other_buttons():
    phone = Phone(PIG, tap_ok=False)
    handler = PopupHandler(actions(phone), SimpleNamespace(device=phone))
    with pytest.raises(RuntimeError, match="Không bấm được"):
        handler.close_all()
    assert phone.taps == [(507, 1623, 573, 1689)]


@pytest.mark.parametrize("bounds,expected", [
    ("[506,1663][574,1731]", (506, 1663, 574, 1731)),
    ("[506,1700][574,1768]", (506, 1700, 574, 1768)),
    ("[506,1661][574,1729]", (506, 1661, 574, 1729)),
])
def test_compose_pig_campaign_detected_and_only_x_tapped(monkeypatch, bounds, expected):
    monkeypatch.setattr(popup_handler.time, "sleep", lambda _: None)
    phone = Phone(compose_pig(bounds))
    handler = PopupHandler(actions(phone), SimpleNamespace(device=phone))
    assert 'lite_reward' in handler.detect()
    assert handler.close_all()
    assert phone.taps == [expected]
    assert not handler.detect()


@pytest.mark.parametrize("xml", [
    compose_pig().replace("돼지 저금통 깨고 획득하기", "Unrelated dialog"),
    compose_pig().replace("com.ss.android.ugc.tiktok.lite", "com.example.other"),
    compose_pig().replace("androidx.compose.ui.platform.ComposeView", "android.widget.FrameLayout"),
    compose_pig().replace('enabled="true"', 'enabled="false"'),
])
def test_unrelated_or_disabled_close_never_tapped(xml):
    phone = Phone(xml)
    assert not actions(phone).close_lite_reward_popup()
    assert phone.taps == []
    assert phone.dumps == 0


def test_multiple_campaign_close_buttons_abort_without_tap():
    phone = Phone(compose_pig(close_count=2))
    with pytest.raises(RuntimeError, match="nhiều nút"):
        actions(phone).close_lite_reward_popup()
    assert phone.taps == []


def test_persistent_campaign_is_not_retapped_or_reported_closed(monkeypatch):
    monkeypatch.setattr(popup_handler.time, "sleep", lambda _: None)
    phone = Phone(compose_pig(), after_tap=None)
    handler = PopupHandler(actions(phone), SimpleNamespace(device=phone))
    with pytest.raises(RuntimeError, match="vẫn còn"):
        handler.close_all()
    assert len(phone.taps) == 1
    assert phone.dumps == 6  # detection + five verification reads


@pytest.mark.parametrize("after", ["not XML", "<hierarchy/>", '<hierarchy><node package="com.android.systemui"/></hierarchy>'])
def test_unreadable_post_tap_screen_is_not_success(after):
    phone = Phone(compose_pig(), after_tap=after)
    with pytest.raises(RuntimeError, match="Chưa xác minh"):
        actions(phone).close_lite_reward_popup()
    assert len(phone.taps) == 1


def test_campaign_animation_is_verified_again_without_retapping(monkeypatch):
    waits = []
    monkeypatch.setattr(popup_handler.time, "sleep", waits.append)
    phone = Phone(compose_pig(), after_tap=None)
    reads = iter([compose_pig(), FEED])
    phone.dump_hierarchy = lambda **kwargs: next(reads)
    assert actions(phone).close_lite_reward_popup()
    assert len(phone.taps) == 1
    assert waits == [0.2]


def test_verification_transport_failure_aborts_without_retapping():
    phone = Phone(compose_pig())

    def failed_dump(**kwargs):
        raise OSError("device offline")

    phone.dump_hierarchy = failed_dump
    with pytest.raises(RuntimeError, match="Chưa xác minh"):
        actions(phone).close_lite_reward_popup()
    assert len(phone.taps) == 1


def test_4703_football_campaign_closes_only_bottom_x(monkeypatch):
    monkeypatch.setattr(popup_handler.time, "sleep", lambda _: None)
    phone = Phone(football_reward())
    handler = PopupHandler(actions(phone), SimpleNamespace(device=phone))
    assert 'lite_reward' in handler.detect()
    assert handler.close_all()
    assert phone.taps == [(507, 1513, 573, 1580)]
    assert not handler.detect()


@pytest.mark.parametrize("xml", [
    football_reward(image_count=2),
    football_reward().replace(':id/sl8', ':id/unrelated'),
    football_reward().replace('content-desc="닫기"', 'content-desc="unrelated"'),
    football_reward().replace('com.ss.android.ugc.tiktok.lite', 'com.example.foreign'),
])
def test_4703_campaign_needs_exact_structure_and_unique_x(xml):
    phone = Phone(xml)
    assert not actions(phone).close_lite_reward_popup()
    assert phone.taps == []


def test_4703_persistent_campaign_is_not_reported_closed(monkeypatch):
    monkeypatch.setattr(popup_handler.time, "sleep", lambda _: None)
    phone = Phone(football_reward(), after_tap=None)
    with pytest.raises(RuntimeError, match="vẫn còn"):
        actions(phone).close_lite_reward_popup()
    assert phone.taps == [(507, 1513, 573, 1580)]
