"""Smoke-test portable GUI/engine with Python removed from the child PATH."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

folder = Path(sys.argv[1]).resolve()
env = {
    **os.environ,
    "PATH": str(Path(os.environ["SystemRoot"]) / "System32")
    + os.pathsep
    + os.environ["SystemRoot"],
    "PYTHONPATH": "",
    "PYTHONHOME": "",
}
env.pop("TAKTIK_DESKTOP_PID", None)
flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
with tempfile.TemporaryDirectory(prefix="taktik kiểm thử ") as temporary:
    root = Path(temporary)
    report = root / "gui.json"
    gui = subprocess.Popen(
        [str(folder / "TikTokKorean.exe"), "--smoke-report", str(report)],
        env=env,
        cwd=folder,
        creationflags=flags,
    )
    try:
        code = gui.wait(timeout=20)
    except subprocess.TimeoutExpired:
        gui.kill()
        gui.wait()
        raise RuntimeError(
            "Frozen GUI did not finish its smoke test; inspect native dependency errors."
        )
    if code or not report.exists():
        raise RuntimeError(f"Frozen GUI smoke test failed: exit {code}")
    data = json.loads(report.read_text(encoding="utf-8"))
    if not (
        data.get("qt_ready")
        and data.get("browse_ready")
        and data.get("icon_ready")
        and data.get("frozen")
        and data.get("utc_offset_seconds") == 25200
    ):
        raise RuntimeError(f"Frozen GUI smoke evidence is incomplete: {data}")
    env["TAKTIK_DB_PATH"] = str(root / "fresh engine.db")
    engine = subprocess.run(
        [str(folder / "engine/customer_engine.exe"), "--prepare-db"],
        env=env,
        capture_output=True,
        timeout=40,
        creationflags=flags,
    )
    if engine.returncode or b'"success": true' not in engine.stdout:
        raise RuntimeError(
            "Frozen engine database smoke failed: "
            + engine.stderr.decode("utf-8", errors="replace")[-1000:]
        )
    locked_env = {
        **env,
        "TAKTIK_CUSTOMER_DATA": str(root / "no-license"),
        "TAKTIK_CUSTOMER_GATE": str(root / "never-open-gate"),
    }
    locked = subprocess.run(
        [
            str(folder / "engine/customer_engine.exe"),
            "tiktok_bridge",
            str(root / "no-config.json"),
        ],
        env=locked_env,
        capture_output=True,
        timeout=6,
        creationflags=flags,
    )
    if locked.returncode != 3 or b"CUSTOMER_LICENSE_INVALID" not in locked.stdout:
        raise RuntimeError(
            "Frozen engine must reject missing license before startup/device actions."
        )
    print(
        "PASS: frozen Qt/SVG/form/timezone/database and independent engine license gate; child PATH has no Python."
    )
