"""No device access. Actual subprocess fixture for QProcess and Windows containment."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

mode = sys.argv[1]
deadline = time.monotonic() + 10
while not Path(os.environ["TAKTIK_CUSTOMER_GATE"]).exists():
    if time.monotonic() > deadline:
        raise SystemExit(126)
    time.sleep(0.01)


def emit(e):
    data = (json.dumps(e, ensure_ascii=False) + "\n").encode()
    # Exercise multibyte and mid-line chunks through the real pipe.
    for i in range(0, len(data), 3):
        os.write(1, data[i : i + 3])


if mode == "child":
    p = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(120)"])
    emit({"type": "fixture_child", "pid": p.pid})
if mode in ("wait", "child"):
    while not Path(os.environ["TAKTIK_CUSTOMER_STOP"]).exists():
        time.sleep(0.02)
emit({"type": "log", "message": "Xin chào 한글"})
if mode == "error":
    emit({"type": "error", "error": "business failure"})
if mode == "flood":
    os.write(1, b"x" * (8 * 1024 * 1024))
if mode not in ("missing",):
    emit({"type": "upload_result", "success": True})
