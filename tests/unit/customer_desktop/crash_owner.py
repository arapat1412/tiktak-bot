"""An abruptly exiting GUI owner; no hardware. Used only by the Windows test."""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from PySide6.QtCore import QCoreApplication, QProcess, QTimer
from customer_desktop.process_guard import JobGuard

app = QCoreApplication([])
directory = Path(sys.argv[1])
directory.mkdir(exist_ok=True)
os.environ["TAKTIK_CUSTOMER_GATE"] = str(directory / "gate")
os.environ["TAKTIK_CUSTOMER_STOP"] = str(directory / "stop")
p = QProcess()
guard = None
buffer = bytearray()


def started():
    global guard
    guard = JobGuard(int(p.processId()))
    (directory / "gate").touch()


def output():
    buffer.extend(bytes(p.readAllStandardOutput()))
    if b"\n" not in buffer:
        return
    for line in buffer.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "fixture_child":
            (directory / "pids.json").write_text(
                json.dumps({"bridge": int(p.processId()), "child": e["pid"]})
            )
            os._exit(0)


p.started.connect(started)
p.readyReadStandardOutput.connect(output)
p.start(
    sys.executable, ["-u", str(Path(__file__).with_name("fake_worker.py")), "child"]
)
QTimer.singleShot(10000, lambda: os._exit(2))
app.exec()
