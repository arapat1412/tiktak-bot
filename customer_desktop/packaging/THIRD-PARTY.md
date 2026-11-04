# Thông báo nguồn và thành phần đi kèm

Ứng dụng này tái sử dụng TAKTIK public, giấy phép GNU GPL v3; xem LICENSE và NOTICE.
Khi phân phối cho khách, cung cấp toàn bộ mã nguồn tương ứng của phiên bản được giao,
bao gồm customer_desktop, các thay đổi engine, script build, manifest và hướng dẫn build.
Không coi GUI riêng là lý do loại bỏ nghĩa vụ cung cấp nguồn của TAKTIK.

GUI dùng Qt for Python / PySide6 Essentials / Shiboken6, được liên kết động trong thư mục
_internal/PySide6; xem giấy phép LGPL v3/GPL và các bản quyền trong licenses. Không khóa
khách thay thư viện Qt tương thích. Đây là bản dạng thư mục để dễ kiểm tra/thay thư viện.

Engine dùng Python và các thư viện được ghi phiên bản trong licenses/inventory.json.
PyInstaller có ngoại lệ cho bootloader; giấy phép các dependency vẫn áp dụng riêng.
Gói không kèm ADB, driver, Xiaowei, TikTok APK hoặc Tesseract chưa được staged.
ADB hiện có trên máy phải được cấu hình trong Cài đặt nếu không có trong PATH.
Không tự cài driver hay đổi ADB server của khách.

Trước phân phối chính thức, rà soát license inventory và giao nguồn tương ứng cùng binary.
Đây là thông báo kỹ thuật về thành phần build, không phải ý kiến tư vấn pháp lý.

ADBKeyBoard v2.5-dev của senzhk đi kèm dưới dạng APK độc lập trong resources/adb-keyboard,
được phân phối theo GPL-2.0. License, nguồn đúng tag và SHA-256 của APK/nguồn nằm cùng thư mục.
Nguồn dự án: https://github.com/senzhk/ADBKeyBoard . Không sửa mã nguồn bàn phím.
