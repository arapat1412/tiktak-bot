# TikTok thường và Lite — bằng chứng ngày 02/11/2026

Chỉ sửa source và kiểm thử. Không build, đóng gói, triển khai, ghi vào database khách hoặc thay bản app Windows đang dùng. Đã đọc AGENTS.md, kiểm tra tracked/untracked và lưu bản chụp source trước khi sửa trong TEMP để đối chiếu; không reset/clean công việc cũ. Command Code không có trên máy, nên dùng fallback trực tiếp theo AGENTS.md.

## Thay đổi

- Inventory trả về tất cả ứng dụng đã cài cùng versionName/versionCode, giữ Lite là mặc định cũ.
- Cập nhật giao diện theo yêu cầu tiếp theo: chọn **Ứng dụng → TikTok Lite / TikTok thường** ngay trong **Lướt tự nhiên** hoặc **Đăng nội dung**. Có thể chọn riêng từng máy trong cùng form. Lựa chọn cũ trong settings vẫn được đọc tương thích; không migration hay sửa snapshot tác vụ cũ.
- Tác vụ mới chốt `packageName` trước khi import media/chạy nền. Manager, kiểm tra foreground, bộ selector theo phiên bản, publish và cleanup dùng package đó. Thiếu package đã chọn thì báo lỗi, không chuyển sang app khác. Định tuyến ADB per-phone/per-worker hiện có giữ nguyên.
- Bộ `tiktok_trill.yaml` được áp dụng theo đúng package và phiên bản đã đo; không ghi đè selector Lite. Phân biệt ô bình luận đang hoạt động với bản phía sau, nút gửi bị khóa/bật, thư viện media nằm phía sau editor, mô tả ảnh với tiêu đề, nút Next với Story/Post.
- Nhận diện Create mở thẳng gallery bằng XML. Không thêm tọa độ cố định. Popup đồng ý nhận quảng cáo bắt buộc trên W15J khiến tác vụ dừng để người dùng xử lý, không tự bấm Allow.
- Không thay nhịp xem/nghỉ, xác suất/giới hạn tương tác, nội dung, lịch, hàng đợi, pause/hold/stop, xác nhận kết quả hay chính sách không gửi/đăng lại khi chưa rõ kết quả.

## Thiết bị thực tế

Package thường trên cả sáu máy: `com.ss.android.ugc.trill`. Package Lite: `com.ss.android.ugc.tiktok.lite`. Các UI quan sát được đều tiếng Hàn; không suy ra ngôn ngữ app chỉ từ locale Android.

| Đuôi serial | ADB | Android | TikTok thường | Lite | Mức kiểm chứng thật |
|---|---:|---:|---|---|---|
| QNBP | 5037 | 10 | 47.6.3 | 47.5.3 | Feed, bình luận/nháp production, hồ sơ, camera, chọn ảnh và video, editor có/không nhạc, caption/hashtag và trước Post |
| 7WKJ | 5037 | 11 | Không cài | 47.5.3 | Dump rewards overlay; Back thủ công và dump feed Lite |
| QS8Z | 5037 | 16 | 47.5.3 | 47.5.3 | Popup gợi ý bạn, feed, bình luận/nháp production, hồ sơ, quyền camera/media, video/editor/caption và trước Post |
| W15J | 5038 | 16 | 47.5.3 | 47.5.3 | Popup đồng ý quảng cáo; Back không đóng. Chưa nghiệm thu luồng sau popup |
| CT7H | 5038 | 13 | 47.5.2 | 47.1.4 | Feed, sheet trống, nháp production, hồ sơ, quyền camera, ảnh/editor/caption và trước Post |
| AXKB | 5038 | 16 | 47.1.4 | 47.5.3 | Feed, bình luận/nháp production, hồ sơ, camera/gallery, ảnh/editor/caption và trước Post |
| 3BJP | 5038 | 16 | 47.6.3 | 47.4.3 | Inventory và dump feed; chưa chạy hết luồng trên máy này |

85 XML đầy đủ cấu trúc được ẩn thông tin cá nhân. `manifest.json` ghi package/version/code, Android, cổng ADB, ngôn ngữ, thời điểm KST, bề mặt thực tế, trạng thái, hash raw và hash fixture của từng dump. Một số tên file giữ tên thao tác lấy dump; hãy đọc `surface` và `notes` để biết màn hình thực tế (ví dụ Create mở thẳng gallery). Không lưu ảnh chụp màn hình hoặc file media vào corpus.

`live_checks.json` ghi bốn phiên nhập nháp bằng chính `CommentActions._focus_and_type`, đọc lại nội dung, kiểm tra có đúng một nút gửi bật, `discard_draft`, `close_comments` và trả bàn phím về như trước. Không gọi `post_comment`; không đăng bài, tim hoặc follow. Đã thử đồng thời trên cả 5037 và 5038.

Trong probe đầu, XPath.set_text của uiautomator2 tự cài/chuyển helper IME trên QS8Z, CT7H và AXKB. Đã gỡ chính helper vừa cài và khôi phục IME theo lịch sử hệ thống. Bốn lần kiểm tra production sau đó đều xác nhận IME ban đầu = IME khôi phục và không còn helper. Tệp video thử riêng đã được dọn khỏi cả bốn máy; không xóa media khác.

## Kiểm thử

Runtime `.venv` cũ trỏ tới Python không tồn tại của máy trước. Dùng Python 3.10.11 embeddable trong TEMP với site-packages sẵn có; không sửa `.venv` hay thêm dependency repository.

- `pytest tests/unit/social_media/tiktok/ui/test_tiktok_standard_corpus.py tests/unit/customer_desktop/test_tiktok_app_choice.py -q --tb=short`: **127 passed**. Bao gồm UI chọn hai app, chốt package trước tác vụ nền, lịch bất biến, thiếu app không fallback, XML/metadata, paired draft/clear, Lite sau standard và gallery trực tiếp.
- Kiểm tra cuối sau đối chiếu baseline và định dạng: nhóm trên cộng `test_multi_adb.py`, `test_tiktok_selected_package.py`, `test_compat_overrides_on_connect.py`: **158 passed**, 5.69 giây. 85 file XML khớp đủ 85 mục manifest, có đủ metadata bắt buộc.
- Suite `tests/unit/customer_desktop tests/unit/social_media/tiktok tests/unit/bridges/tiktok tests/unit/compat`: **2026 passed, 9 failed**, 162.36 giây. Chín lỗi có sẵn: thiếu `admin/cap_license.py` và tám ca dữ liệu công bố tương thích. Đã tái hiện lỗi metadata với app_builds/overrides của bản chụp trước sửa; không tự gán trạng thái validated hoặc thay dữ liệu cũ để làm xanh test. Hai ca corpus bổ sung cuối được kiểm tra trong nhóm 127 ở trên.
- `tests/unit/shared/device tests/unit/clone`: **311 passed, 9 failed, 1 skipped**. Chín ca `test_app_primitives.py` vẫn kỳ vọng mặc định TikTok thường/danh sách ba package, trong khi source trước tác vụ này đã chuyển sang Lite-first và thêm variant. Không thay các mặc định đó. Các thay đổi foreground theo package đã có kiểm thử riêng và suite connect/selected-package qua.
- `test_compat_overrides_on_connect.py` và `test_tiktok_selected_package.py`: **11 passed** trong nhóm 108 cùng corpus tại thời điểm chạy. Bao gồm package phiên bản được chọn và cleanup đúng app.
- Flake8 F821/F822/F823/E999 trên vùng sửa và `git diff --check`: qua. Không chạy build theo yêu cầu.

## Giới hạn và bước tiếp

- Phạm vi live là bốn phiên bản nêu trên, UI tiếng Hàn. Không khẳng định hỗ trợ đầy đủ phiên bản/ngôn ngữ chưa dump.
- Chưa nghiệm thu kết quả đăng thật/tim/comment/follow trên TikTok thường; mới kiểm tra selector, điều hướng, nháp và kiểm thử kết quả giả lập của cơ chế hiện có. Người dùng đã cho phép thao tác công khai, nhưng chưa chỉ định bài/nội dung/tài khoản để đăng nghiệm thu; không đăng nội dung tùy ý.
- Cần người dùng xử lý quyết định popup quảng cáo trên W15J. Có thể chọn rõ tài khoản, media và caption nếu muốn nghiệm thu đăng thật.
- Bản Windows đang sử dụng chưa có tính năng mới vì không build/cập nhật. Build, đóng gói hoặc triển khai cần lệnh riêng của người dùng.
