"""Korean TikTok must be recognised from the app's labels — and only from them.

The ko overlay only becomes active once detection commits to 'ko'. A wrong commitment is
worse than none: it strips the correct locale, whereas 'unknown' keeps every locale. The
rules pinned here are the conservative ones:

- only ``text`` / ``content-desc`` VALUES are evidence (a dump's English resource-ids are
  identifiers, not language);
- a language wins only with ``min_score`` AND ``min_ratio`` over EVERY other language, and
  an exact tie stays 'unknown';
- filtering for an additional language removes only expressions clearly in one other
  language: neutral (id-only), mixed, and above all target-language selectors are kept.

TikTok's Korean vocabulary was measured on 47.5.3 (SO-52A, Korean phone).
"""

import pytest

from taktik.core.social_media.tiktok.ui import language


class _FakeDevice:
    def __init__(self, xml):
        self._xml = xml

    def get_xml_dump(self):
        return self._xml


@pytest.fixture(autouse=True)
def _reset_lang():
    """Leave the process exactly as found: detection sets the active locale AND filters the
    shared selector dataclasses IN PLACE, so a decision that escapes amputates a catalogue.
    """
    from taktik.core.social_media.tiktok.ui.selectors.locales import (
        active_locale,
        set_active_locale,
    )

    before = active_locale()
    language._DETECTION._detected_lang = None
    yield
    language._DETECTION._detected_lang = None
    set_active_locale(before)


@pytest.fixture
def _optimized(monkeypatch):
    """Neutralise the destructive half of `detect_and_optimize` and record the language."""
    calls = []
    monkeypatch.setattr(
        language._DETECTION,
        "optimize_selector_dataclass",
        lambda inst, lang: calls.append(lang) or 0,
    )
    return calls


#: Korean app, English user content: seven measured labels, a caption in English.
_KOREAN_UI_ENGLISH_CONTENT = """
<hierarchy>
  <node resource-id="com.zhiliaoapp.musically:id/home_tab" content-desc="홈" clickable="true"/>
  <node resource-id="com.zhiliaoapp.musically:id/friends_tab" content-desc="친구" clickable="true"/>
  <node resource-id="com.zhiliaoapp.musically:id/following_tab" content-desc="팔로잉"/>
  <node resource-id="com.zhiliaoapp.musically:id/for_you_tab" content-desc="추천" selected="true"/>
  <node resource-id="com.zhiliaoapp.musically:id/search_button" content-desc="검색" clickable="true"/>
  <node resource-id="com.zhiliaoapp.musically:id/inbox_tab" content-desc="알림" clickable="true"/>
  <node resource-id="com.zhiliaoapp.musically:id/profile_tab" content-desc="프로필" clickable="true"/>
  <node text="Found my new favourite café — like and follow for more!"/>
</hierarchy>
"""

#: English app, Korean user content: six English labels against one Korean caption.
_ENGLISH_UI_KOREAN_CONTENT = """
<hierarchy>
  <node resource-id="com.zhiliaoapp.musically:id/home_tab" content-desc="Home" clickable="true"/>
  <node resource-id="com.zhiliaoapp.musically:id/friends_tab" content-desc="Friends" clickable="true"/>
  <node resource-id="com.zhiliaoapp.musically:id/inbox_tab" content-desc="Inbox" clickable="true"/>
  <node resource-id="com.zhiliaoapp.musically:id/profile_tab" content-desc="Profile" clickable="true"/>
  <node resource-id="com.zhiliaoapp.musically:id/create_button" content-desc="Create" clickable="true"/>
  <node resource-id="com.zhiliaoapp.musically:id/search_button" content-desc="Search" clickable="true"/>
  <node text="오늘 처음 올리는 영상이에요 홈 친구 팔로잉 추천 검색 모두 감사합니다"/>
</hierarchy>
"""

#: Two words each: below the score floor, so no locale may be stripped.
_LOW_EVIDENCE = """
<hierarchy>
  <node content-desc="홈"/>
  <node content-desc="검색"/>
  <node text="Home"/>
  <node text="Search"/>
</hierarchy>
"""

#: Three words each: enough evidence, but no winner — a tie must not decide.
_TIED = """
<hierarchy>
  <node content-desc="홈"/>
  <node content-desc="친구"/>
  <node content-desc="검색"/>
  <node text="Home"/>
  <node text="Friends"/>
  <node text="Search"/>
</hierarchy>
"""

#: TikTok's English resource-ids and not one visible word.
_ENGLISH_ONLY_IDS = """
<hierarchy>
  <node resource-id="com.zhiliaoapp.musically:id/home_tab" class="android.widget.FrameLayout"/>
  <node resource-id="com.zhiliaoapp.musically:id/friends_tab" class="android.widget.FrameLayout"/>
  <node resource-id="com.zhiliaoapp.musically:id/inbox_tab" class="android.widget.FrameLayout"/>
  <node resource-id="com.zhiliaoapp.musically:id/profile_tab" class="android.widget.FrameLayout"/>
  <node resource-id="com.zhiliaoapp.musically:id/comment_tab" class="android.widget.FrameLayout"/>
</hierarchy>
"""


def _detect(xml):
    return language.detect_language(_FakeDevice(xml))


def test_korean_app_wins_despite_english_user_content():
    """The labels of the app say Korean; a caption written in English must not outvote them."""
    assert _detect(_KOREAN_UI_ENGLISH_CONTENT) == "ko"


def test_english_app_wins_despite_korean_user_content():
    """English labels stay decisive even when the visible caption is Korean."""
    assert _detect(_ENGLISH_UI_KOREAN_CONTENT) == "en"


def test_thin_screens_stay_unknown():
    """Two words per language are not a language: 'unknown' keeps every locale."""
    assert _detect(_LOW_EVIDENCE) == "unknown"


def test_a_tie_between_languages_stays_unknown():
    assert _detect(_TIED) == "unknown"


def test_english_resource_ids_alone_never_decide_the_language():
    """Identifiers are not evidence — they used to hand English a free point per word."""
    assert "com.zhiliaoapp.musically" in _ENGLISH_ONLY_IDS
    assert _detect(_ENGLISH_ONLY_IDS) == "unknown"


def test_words_in_resource_ids_are_never_scored():
    """Even Korean-looking ids prove nothing: only text and content-desc are visible text."""
    xml = (
        '<hierarchy><node resource-id="com.zhiliaoapp.musically:id/'
        '홈_친구_검색_프로필"/></hierarchy>'
    )
    assert _detect(xml) == "unknown"


def test_ko_override_is_accepted_and_activates_the_ko_locale(_optimized):
    """The override must be validated against the registered locales, not a frozen pair:
    a hardcoded ('en', 'fr') rejected every new locale."""
    from taktik.core.social_media.tiktok.ui.selectors.locales import (
        active_locale,
        available_locales,
    )

    assert "ko" in available_locales()

    lang = language.detect_and_optimize(_FakeDevice(_KOREAN_UI_ENGLISH_CONTENT), "ko")

    assert lang == "ko"
    assert language.get_detected_language() == "ko"
    assert active_locale() == "ko"
    assert _optimized and set(_optimized) == {"ko"}


# ── Filtering ────────────────────────────────────────────────────────────────

_KOREAN = '//*[@content-desc="홈"]'
_NEUTRAL_ID = '//*[@resource-id="com.zhiliaoapp.musically:id/home_tab"]'
_MIXED_KO_EN = '//*[@text="Home" and @content-desc="홈"]'
_MIXED_FR_EN = '//*[@text="Accueil" and @content-desc="Home"]'
_ENGLISH = '//android.widget.TextView[@text="Home"]'
_FRENCH = '//android.widget.TextView[@text="Accueil"]'


def test_an_additional_language_keeps_neutral_and_mixed_expressions():
    """For 'ko', only expressions clearly in ONE other language go; everything else stays."""
    selectors = [
        _KOREAN,
        _NEUTRAL_ID,
        _MIXED_KO_EN,
        _MIXED_FR_EN,
        _ENGLISH,
        _FRENCH,
    ]

    assert language.filter_selectors(selectors, "ko") == [
        _KOREAN,
        _NEUTRAL_ID,
        _MIXED_KO_EN,
        _MIXED_FR_EN,
    ]


def test_korean_selectors_are_never_removed_by_en_or_fr_filtering():
    """The en/fr rules are unchanged, and Korean is neutral to them — so it is retained."""
    assert language.filter_selectors([_KOREAN, _NEUTRAL_ID, _FRENCH], "en") == [
        _KOREAN,
        _NEUTRAL_ID,
    ]
    assert language.filter_selectors([_KOREAN, _NEUTRAL_ID, _ENGLISH], "fr") == [
        _KOREAN,
        _NEUTRAL_ID,
    ]


def test_korean_is_recognised_only_from_text_attributes():
    assert language._classify_selector(_KOREAN) == "ko"
    assert language._classify_selector(_NEUTRAL_ID) == "neutral"
    assert language._classify_selector(_MIXED_KO_EN) == "neutral"
