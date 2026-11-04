# Môi trường phát triển trên máy này

Mã nguồn: C:\Bot\tiktak-bot
Python riêng: .venv\Scripts\python.exe (Python 3.12)
ADB: C:\Bot\tools\platform-tools\adb.exe
Đã cài editable package, requirements-dev.txt và requirements-desktop.txt.

Mở PowerShell trong thư mục dự án:

```powershell
# Menu CLI
powershell -ExecutionPolicy Bypass -File .\dev.ps1
# Danh sách workflow (không chạy thao tác trên điện thoại)
powershell -ExecutionPolicy Bypass -File .\dev.ps1 workflows list
# Giao diện desktop tiếng Việt
powershell -ExecutionPolicy Bypass -File .\dev.ps1 -Desktop
# Kiểm thử
powershell -ExecutionPolicy Bypass -File .\dev.ps1 -Test
# Kiểm tra điện thoại
C:\Bot\tools\platform-tools\adb.exe devices -l
```

Sửa code trong taktik\ (engine/CLI) hoặc customer_desktop\ (giao diện).
Cài editable nên thay đổi code có hiệu lực trong lần chạy tiếp theo.
Cấu hình Python cho VS Code đã có trong .vscode\settings.json.
Dữ liệu CLI lưu riêng tại data\taktik-data.db khi dùng dev.ps1.

Để chạy thật: bật USB debugging trên Android, nối USB và chấp nhận quyền ADB.
Kiểm tra COMPATIBILITY.md để chọn phiên bản TikTok/Instagram phù hợp.
Một số thao tác nhập chữ cần ADB Keyboard; chức năng AI cần khóa OpenRouter.
Giao diện desktop có cơ chế license riêng của dự án.
OCR Tesseract và requirements-media.txt chưa cài vì là tính năng tùy chọn.
