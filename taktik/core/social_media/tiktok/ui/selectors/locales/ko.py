"""Korean customer automation labels, measured on trill 47.5.3 (SO-52A).

Only the navigation, feed, comment and video publishing surfaces are covered.
Resource-id anchors remain in the version catalog. No translated auth/DM guesses.
"""

_COMMENT_HEADER = (
    '//android.widget.TextView[translate(@text,"‎‏","")="댓글" '
    'or starts-with(translate(@text,"‎‏",""),"댓글 ")]'
)
_COMMENT_SHEET_WITHOUT_CLOSE = (
    _COMMENT_HEADER
    + '/ancestor::*[starts-with(@package,"com.ss.android.ugc.")][.//android.widget.EditText[@clickable="true"]][1]'
)
_COMMENT_SHEET = _COMMENT_HEADER + '[//*[@content-desc="닫기"]][//android.widget.EditText]'
_LIKE = (
    '//*[starts-with(@content-desc,"동영상에 ") and contains(@content-desc,"좋아요")]'
)
_COMMENTS = '//*[starts-with(@content-desc,"댓글을 읽거나 추가합니다.")]'
_SHARE = '//*[starts-with(@content-desc,"동영상을 공유합니다.")]'
_FAVORITE = '//*[starts-with(@content-desc,"이 동영상을 즐겨찾기에 추가하거나") ]'

STRINGS = {
    "publish_editor.popup_cancel_buttons": [
        '//*[@resource-id="com.sec.android.app.launcher:id/add_item_cancel_button"]'
        '[//*[@resource-id="com.sec.android.app.launcher:id/add_item_title"]]',
        '//*[@resource-id="com.sec.android.app.launcher:id/cancel_button"]'
        '[//*[@resource-id="com.sec.android.app.launcher:id/add_item_title"]]'
    ],
    "profile.profile_menu_button": ['//*[@content-desc="프로필 메뉴"][@clickable="true"]'],
    "profile.username_anchors": [
        '//android.widget.Button[starts-with(@text,"@")][@package="com.ss.android.ugc.trill"]',
    ],
    "profile.edit_profile_button": ['//*[@text="편집"][@package!="com.android.systemui"]'],
    "profile.stat_label_following": ["팔로잉"],
    "profile.stat_label_followers": ["팔로워"],
    "profile.stat_label_likes": ["좋아요"],
    "popup.dismiss_button": [
        '//*[@text="나중에"][@package!="com.android.systemui"]',
        '//*[@content-desc="하단 시트"][@package="com.ss.android.ugc.tiktok.lite"]'
        '[.//*[@text="별을 탭하여 경험을 평가하세요"]]'
        '//*[@content-desc="닫기"][@clickable="true"]',
    ],
    "navigation.home_tab": ['//*[@content-desc="홈"][@clickable="true"][@package!="com.android.systemui"]'],
    "navigation.home_tab_selected": ['//*[@content-desc="홈"][@selected="true"]'],
    "navigation.friends_tab": ['//*[@content-desc="친구"][@clickable="true"]'],
    "navigation.following_tab": ['//*[@content-desc="팔로잉"]'],
    "navigation.for_you_tab": ['//*[@content-desc="추천" or @text="추천"][@selected="true"]'],
    "navigation.create_button": ['//*[@content-desc="만들기"][@clickable="true"]'],
    "navigation.inbox_tab": ['//*[@content-desc="알림"][@clickable="true"]'],
    "navigation.inbox_tab_selected": ['//*[@content-desc="알림"][@selected="true"]'],
    "navigation.profile_tab": ['//*[@content-desc="프로필"][@clickable="true"]'],
    "navigation.search_button": ['//*[@content-desc="검색"][@clickable="true"]'],
    "navigation.shop_tab": ['//*[@content-desc="숍"][@clickable="true"]'],
    "navigation.bottom_nav_container_anchors": [
        '//*[@content-desc="홈"][@clickable="true"]'
        '[starts-with(@package,"com.ss.android.ugc.")]/..'
    ],
    "video_creator.creator_profile_image": [
        '//*[contains(@content-desc," 님의 프로필")]'
    ],
    "video_creator.follow_button": [
        '//*[substring(@content-desc,string-length(@content-desc)-3)=" 팔로우"]'
    ],
    "video_engagement.like_button": [_LIKE],
    "video_engagement.like_button_for_count": [_LIKE],
    "video_engagement.like_button_content_desc_fallbacks": [_LIKE],
    "video_engagement.comment_button": [_COMMENTS],
    "video_engagement.comment_button_for_count": [_COMMENTS],
    "video_engagement.share_button": [_SHARE],
    "video_engagement.favorite_button": [_FAVORITE],
    "video_engagement.like_count_anchors": [_LIKE + '/descendant::*[@text!=""][1]'],
    "video_engagement.comment_count_anchors": [
        _COMMENTS + '/descendant::*[@text!=""][1]'
    ],
    "video_engagement.share_count_anchors": [_SHARE + '/descendant::*[@text!=""][1]'],
    "video_engagement.favorite_count_anchors": [
        _FAVORITE + '/descendant::*[@text!=""][1]'
    ],
    "video_state.video_page_indicator": [
        '//*[@content-desc="동영상"][contains(@resource-id,":id/long_press_layout")]'
    ],
    "video_state.video_already_liked": [
        '//*[@content-desc="좋아요"][@selected="true"]'
    ],
    "video_state.video_liked_indicator": [
        '//*[@content-desc="좋아요"][@selected="true"]'
    ],
    "video_state.unlike_indicator": ['//*[@content-desc="좋아요"][@selected="true"]'],
    "video_state.like_button_unliked": [_LIKE + '[not(.//*[@selected="true"])]'],
    "video_state.ad_label": ['//*[@text="광고"]'],
    "video_media.sound_button": ['//*[starts-with(@content-desc,"사운드:")]'],
    "comment.sheet_indicator": [_COMMENT_SHEET, _COMMENT_SHEET_WITHOUT_CLOSE],
    "comment.comment_input": [
        '//android.widget.EditText[contains(@hint,"따듯한 말 한마디")]',
        '//android.widget.EditText[contains(@hint,"댓글")]',
    ],
    "comment.comment_count_header": [_COMMENT_HEADER],
    "comment.reply_button": ['//*[@text="답글"]'],
    "comment.close_button": ['//*[@content-desc="닫기"][@clickable="true"]'],
    "comment.post_comment_button": [
        '//android.widget.Button[@content-desc="댓글 게시"][starts-with(@package,"com.ss.android.ugc.")][@clickable="true"]',
        '//*[@content-desc="다른 사용자 멘션"]/following::android.widget.Button[starts-with(@content-desc,"@")][1]'
    ],
    "publish_creation_entry.create_btn": [
        '//*[@content-desc="만들기"][@clickable="true"]'
    ],
    "publish_creation_entry.home_ready_indicators": [
        '//*[@content-desc="만들기"][@clickable="true"]'
    ],
    "publish_media_picker.next_btn": [
        '//android.widget.Button[starts-with(@text,"다음")]',
        '//android.widget.TextView[@text="다음"]/ancestor::*[@clickable="true"][1]',
    ],
    "publish_composer.caption_input": [
        '//android.widget.EditText[@hint="설명을 추가하세요..."]'
    ],
    "publish_composer.post_btn": ['//android.widget.Button[@text="게시"]'],
    "publish_composer.publish_confirm_dialog": [
        '//*[@package="com.ss.android.ugc.tiktok.lite"][@text="동영상을 공개적으로 게시하시겠습니까?"]'
    ],
    "publish_composer.publish_confirm_btn": [
        '//*[@package="com.ss.android.ugc.tiktok.lite"][@text="지금 게시"][@clickable="true"]'
        '[//*[@text="동영상을 공개적으로 게시하시겠습니까?"]]'
    ],
    "publish_composer.post_screen_xml_markers": ['hint="설명을 추가하세요..."'],
}
