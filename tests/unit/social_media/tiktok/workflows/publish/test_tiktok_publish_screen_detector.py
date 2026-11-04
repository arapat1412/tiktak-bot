from taktik.core.social_media.tiktok.services.publish.screen_detector import (
    is_camera_creation_screen,
    is_gallery_picker_open,
    is_post_screen,
    is_video_edit_screen,
    wait_for_tiktok_home,
)


class FakeXpathResult:
    def __init__(self, matches: bool):
        self.matches = matches

    def wait(self, timeout: float = 0) -> bool:
        return self.matches


class FakeDumpDevice:
    def __init__(self, xml: str, matched_xpaths: set[str] | None = None):
        self.xml = xml
        self.matched_xpaths = matched_xpaths or set()

    def dump_hierarchy(self, compressed: bool = False) -> str:
        return self.xml

    def xpath(self, xpath: str) -> FakeXpathResult:
        return FakeXpathResult(xpath in self.matched_xpaths)


def test_is_gallery_picker_open_reads_xml_marker():
    device = FakeDumpDevice('<node resource-id="pkg:id/mub" />')

    assert is_gallery_picker_open(device)


def test_is_camera_creation_screen_reads_xml_markers():
    device = FakeDumpDevice('<node text="Add sound" /><node resource-id="pkg:id/r3r" />')

    assert is_camera_creation_screen(device)


def test_is_post_screen_reads_marker_or_lxml_selector():
    assert is_post_screen(FakeDumpDevice('<node resource-id="pkg:id/g19" />'))

    device = FakeDumpDevice(
        '<hierarchy><node class="android.widget.Button" content-desc="Post" /></hierarchy>'
    )
    assert is_post_screen(device)


def test_is_video_edit_screen_reads_xml_markers():
    device = FakeDumpDevice(
        '<node text="Annuler" /><node text="Enregistrer" /><node resource-id="pkg:id/xay" />'
    )

    assert is_video_edit_screen(device)


def test_wait_for_tiktok_home_returns_when_indicator_matches():
    from taktik.core.social_media.tiktok.ui.selectors.flows.publish import PUBLISH_CREATION_ENTRY_SELECTORS
    matched = {" | ".join(PUBLISH_CREATION_ENTRY_SELECTORS.home_ready_indicators)}
    device = FakeDumpDevice("<hierarchy />", matched_xpaths=matched)

    assert wait_for_tiktok_home(device, timeout=5, log=lambda _level, _msg: None)


def test_korean_create_is_reached_within_short_deadline(monkeypatch):
    from lxml import etree
    from taktik.core.social_media.tiktok.ui.selectors.locales import set_active_locale, active_locale
    from taktik.core.social_media.tiktok.services.publish.navigation import tap_create_button

    # Exact Create node measured in task 75bd85c4; no legacy resource IDs.
    tree = etree.fromstring('<hierarchy><node resource-id="com.ss.android.ugc.tiktok.lite:id/op4" '
                            'content-desc="만들기" clickable="true" bounds="[432,2067][648,2205]"/></hierarchy>'.encode())
    elapsed = [0.0]
    clicks = []
    class Result:
        def __init__(self, xpath):
            self.matches = tree.xpath(xpath)
        def wait(self, timeout):
            elapsed[0] += 0.1 if self.matches else timeout + 1.0
            return bool(self.matches)
        def click(self):
            clicks.extend(self.matches)
    class Device:
        def xpath(self, xpath):
            return Result(xpath)
    previous = active_locale()
    try:
        set_active_locale(None)
        assert wait_for_tiktok_home(Device(), timeout=10, clock=lambda: elapsed[0])
        assert elapsed[0] < 1
        assert tap_create_button(Device())
        assert len(clicks) == 1
        assert clicks[0].get('resource-id').endswith('/op4')
    finally:
        set_active_locale(previous)
