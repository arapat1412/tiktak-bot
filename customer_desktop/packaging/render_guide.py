"""Render guide illustrations from synthetic data; never reads a real phone/account."""

import argparse
from pathlib import Path
import tempfile
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea, QLabel
from customer_desktop.paths import prepare_paths
from customer_desktop.services import DesktopService
from customer_desktop.ui import MainWindow, BrowseDialog, PublishDialog, apply_style
from customer_desktop.domain import build_browse

parser = argparse.ArgumentParser()
parser.add_argument("--output", default="customer_desktop/resources")
parser.add_argument("--width", type=int, default=1320)
parser.add_argument("--height", type=int, default=760)
args = parser.parse_args()
app = QApplication([])
apply_style(app)
root = prepare_paths(tempfile.mkdtemp(prefix="taktik-guide-"))
s = DesktopService(root, prepare=False)
s.timer.stop()
s.refresh_devices = lambda: None
s.store.set_setting("onboarded", True)
s.store.discover(
    [
        dict(
            serial="DEMO-SONY",
            model="Sony Xperia 5 II",
            connection="online",
            package="fixture",
            version="47.4.3",
            android="12",
        ),
        dict(serial="DEMO-02", model="Điện thoại 02", connection="offline"),
    ]
)
s.store.save_device("DEMO-SONY", "Sony Xperia 5 II", "Nhóm thử", "tai_khoan_thu")
out = Path(args.output)
out.mkdir(parents=True, exist_ok=True)
w = MainWindow(s)
w.refresh_timer.stop()
for label in w.findChildren(QLabel):
    if label.text() == str(root):
        label.setText("C:/Users/KhachHang/AppData/Local/TikTokKorean")
w.resize(args.width, args.height)
w.show()
app.processEvents()
# An explicit visible selection makes the guide's available actions clear.
for row in range(w.device_table.rowCount()):
    if w.device_table.item(row, 0).data(Qt.UserRole) == "DEMO-SONY":
        w.check_clicked_device(row, 1)
w.grab().save(str(out / "guide-devices.png"))
w.search.setText("không có máy")
app.processEvents()
w.grab().save(str(out / "guide-search-empty.png"))
w.search.clear()
for index, name in ((1, "queue-empty"), (2, "results-empty"), (3, "settings")):
    w.nav.setCurrentRow(index)
    app.processEvents()
    w.grab().save(str(out / f"guide-{name}.png"))
w.nav.setCurrentRow(0)
devices = [d for d in s.store.devices() if d["serial"] == "DEMO-SONY"]
b = BrowseDialog(s, devices, w)
b.show()
app.processEvents()
b.grab().save(str(out / "guide-browse.png"))
b.comments.setPlainText("Nội dung khách tự nhập\n한글 예시")
app.processEvents()
b.grab().save(str(out / "guide-natural.png"))
b.close()
p = PublishDialog(
    s,
    devices,
    w,
    initial=dict(
        localPath="C:/Ví dụ/video-01.mp4",
        caption="Một ngày mới thật đẹp.\n오늘도 좋은 하루!",
        hashtags=["#hello"],
    ),
)
p.show()
app.processEvents()
p.grab().save(str(out / "guide-publish.png"))
area = next(a for a in p.findChildren(QScrollArea) if a.widget().isAncestorOf(p.rows))
area.ensureWidgetVisible(p.rows)
app.processEvents()
p.grab().save(str(out / "guide-publish-review.png"))
p.close()
# Display-only fixtures: the service timer is stopped, so these never start a worker.
ids = s.store.enqueue(
    [
        dict(serial="DEMO-SONY", kind="browse", payload=build_browse("DEMO-SONY", {})),
        dict(
            serial="DEMO-SONY",
            kind="browse",
            payload=build_browse("DEMO-SONY", {}),
            run_at=time.time() + 3600,
        ),
        dict(serial="DEMO-SONY", kind="browse", payload=build_browse("DEMO-SONY", {})),
        dict(serial="DEMO-SONY", kind="browse", payload=build_browse("DEMO-SONY", {})),
    ],
    "display-only-guide",
)
for jid, state, message in (
    (ids[2], "succeeded", "Engine xác nhận hoàn tất phiên; đã xem 10 video."),
    (
        ids[3],
        "needs_review",
        "Chưa xác nhận được tương tác. Kiểm tra trên điện thoại trước khi tạo tác vụ mới.",
    ),
):
    s.store.db.execute(
        "UPDATE jobs SET state=?,message=? WHERE id=?", (state, message, jid)
    )
s.store.db.commit()
w.refresh()
for index, name in ((1, "queue"), (2, "results")):
    w.nav.setCurrentRow(index)
    app.processEvents()
    w.grab().save(str(out / f"guide-{name}.png"))
print(
    "Rendered DPR",
    w.devicePixelRatioF(),
    "size",
    w.size().width(),
    w.size().height(),
    "minimum",
    w.minimumSizeHint().width(),
    w.minimumSizeHint().height(),
)
w.allow_close = True
w.close()
s.store.close()
