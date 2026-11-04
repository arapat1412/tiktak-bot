"""Korean Lite surfaces measured on the affected customer phones."""
import pytest
from lxml import etree
from taktik.core.social_media.tiktok.ui.selectors.locales import ko

PKG = "com.ss.android.ugc.tiktok.lite"

def tree(body):
    return etree.fromstring((f'<root><panel package="{PKG}">' + body + '</panel></root>').encode())

def test_sheet_without_labelled_close_is_open():
    screen = tree('<android.widget.TextView text="&#8206;댓글 4개"/>'
                  '<android.widget.EditText clickable="true"/>')
    assert screen.xpath(ko._COMMENT_SHEET_WITHOUT_CLOSE)

def test_header_without_composer_is_not_a_sheet():
    assert not tree('<android.widget.TextView text="댓글 4개"/>').xpath(ko._COMMENT_SHEET_WITHOUT_CLOSE)

def test_composer_without_header_is_not_a_sheet():
    assert not tree('<android.widget.EditText clickable="true"/>').xpath(ko._COMMENT_SHEET_WITHOUT_CLOSE)

def test_for_you_tab_can_expose_text_instead_of_description():
    screen = tree('<tab text="추천" selected="true"/>')
    assert any(screen.xpath(s) for s in ko.STRINGS["navigation.for_you_tab"])
    screen.xpath('//tab')[0].set('selected', 'false')
    assert not any(screen.xpath(s) for s in ko.STRINGS["navigation.for_you_tab"])

def test_korean_send_control_is_not_an_unresolved_resource():
    screen = tree(f'<android.widget.Button package="{PKG}" content-desc="댓글 게시" clickable="true"/>')
    assert any(screen.xpath(s) for s in ko.STRINGS["comment.post_comment_button"])
    screen.xpath('//android.widget.Button')[0].set('content-desc', '검색')
    assert not any(screen.xpath(s) for s in ko.STRINGS["comment.post_comment_button"])


@pytest.mark.parametrize("publish_flow", [False, True])
def test_opaque_checkin_layer_uses_back_and_confirms_dismissal(monkeypatch, publish_flow):
    from uiautomator2.xpath import XPathEntry
    from taktik.core.social_media.tiktok.actions.atomic.interaction import popup_actions as mod

    class Device:
        wait_timeout = 0
        def __init__(self):
            self.presses = []
            self.xpath = XPathEntry(self)
        def dump_hierarchy(self, *args, **kwargs):
            body = ('<node class="android.view.View" package="' + PKG + '" '
                    'resource-id="' + PKG + ':id/sn5" content-desc="@2131829478" '
                    'clickable="true" bounds="[0,0][1080,2094]"/>')
            if self.presses:
                body = '<node class="android.view.View" package="' + PKG + '"/>'
            return '<hierarchy>' + body + '</hierarchy>'
        def press(self, key):
            self.presses.append(key)
        def click(self, *args):
            raise AssertionError("The full-screen layer must never be tapped")

    device = Device()
    actions = mod.PopupActions(device)
    monkeypatch.setattr(mod, "foreground_package", lambda _: PKG)
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)
    if publish_flow:
        from taktik.core.social_media.tiktok.services.publish.dialogs import dismiss_post_popups
        assert dismiss_post_popups(device, sleep=lambda _: None)
    else:
        assert actions.close_lite_reward_popup()
    assert device.presses == ["back"]


def test_rating_dismissal_is_scoped_to_rating_sheet():
    screen = tree(f'<sheet package="{PKG}" content-desc="하단 시트">'
                  '<label text="별을 탭하여 경험을 평가하세요"/>'
                  '<button content-desc="닫기" clickable="true"/></sheet>')
    selectors = ko.STRINGS["popup.dismiss_button"]
    assert any(screen.xpath(s) for s in selectors)
    screen.xpath('//label')[0].set('text', '댓글')
    assert not any(screen.xpath(s) for s in selectors)
