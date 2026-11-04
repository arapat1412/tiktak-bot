"""Run a real Qt/QProcess load test with synthetic devices, never real ADB.

python -m customer_desktop.packaging.load_test --devices 50 --report build/load.json
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from types import SimpleNamespace

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from customer_desktop.domain import build_browse, natural_browse_options
from customer_desktop.paths import prepare_paths
from customer_desktop.runner import Runner
from customer_desktop.services import DesktopService
from customer_desktop.ui import MainWindow, apply_style


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--devices", type=int, default=50, choices=range(2, 51))
    parser.add_argument("--events", type=int, default=1000)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--stop-all", action="store_true")
    parser.add_argument("--timed-minutes", type=int, default=0, choices=range(1441))
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    apply_style(app)
    with tempfile.TemporaryDirectory(prefix="taktik-load-") as tmp:
        root = prepare_paths(tmp)
        release = root / "release.fixture"
        created, refreshes, heartbeats, worker_starts = [], [], [], []
        started = time.monotonic()
        previous = [started]

        def runner_factory(root, job, aid, directory, adb, parent=None):
            r = Runner(
                root,
                job,
                aid,
                directory,
                adb,
                parent,
                command=(
                    sys.executable,
                    [
                        "-u",
                        str(Path(__file__).with_name("load_worker.py")),
                        str(release),
                        str(len(created)),
                        str(args.events),
                        str(args.timed_minutes),
                    ],
                ),
            )
            r.started.connect(lambda *_: worker_starts.append(time.monotonic()))
            created.append(r)
            return r

        class Window(MainWindow):
            def refresh(self, *_):
                before = time.monotonic()
                super().refresh()
                refreshes.append(time.monotonic() - before)

        service = DesktopService(
            root,
            runner_factory=runner_factory,
            prepare=False,
            license_manager=SimpleNamespace(
                check=lambda: SimpleNamespace(valid=True, message="Fixture license")
            ),
        )
        service.timer.stop()
        service.refresh_devices = (
            lambda: None
        )  # No discovery/ADB, including MainWindow's singleShot.
        service.store.set_setting("onboarded", True)
        if not args.timed_minutes:
            service.store.set_setting("max_parallel", args.devices)
            service.store.set_setting(
                "launch_interval", 0.03
            )  # Test acceleration only.
        service.store.discover(
            [
                dict(
                    serial=f"FIXTURE-{i:02}",
                    model=f"Máy thử {i:02}",
                    connection="online",
                    package="fixture",
                )
                for i in range(args.devices)
            ]
        )
        specs = [
            dict(
                serial=d["serial"],
                kind="browse",
                payload=build_browse(
                    d["serial"],
                    (
                        natural_browse_options(
                            max_videos=1, run_duration_minutes=args.timed_minutes
                        )
                        if args.timed_minutes
                        else {"maxVideos": 1}
                    ),
                ),
            )
            for d in service.store.devices()
        ]
        history = service.store.enqueue([specs[0]] * 1000, "history")
        with service.store.transaction():
            service.store.db.execute("UPDATE jobs SET state='succeeded'")
        ids = service.store.enqueue(specs + specs, "load")
        window = Window(service)
        window.resize(1366, 768)
        window.show()
        window.select_all_visible(True)

        def heartbeat():
            now = time.monotonic()
            heartbeats.append(now - previous[0])
            previous[0] = now

        pulse = QTimer()
        pulse.setInterval(10)
        pulse.timeout.connect(heartbeat)
        pulse.start()
        service.timer.setInterval(50)
        service.timer.start()
        peak = 0
        error = ""
        released = False
        deadline = started + 120
        try:
            while time.monotonic() < deadline:
                app.processEvents()
                QTest.qWait(2)
                active = list(service.runners.values())
                peak = max(peak, len(active))
                assert len(active) <= args.devices
                assert len({r.job["serial"] for r in active}) == len(active)
                if len(active) == len(worker_starts) == args.devices and not released:
                    # Stop admission before releasing any slot; duplicate queued
                    # jobs prove the test cannot accidentally replay a result.
                    service.ready = False
                    if args.stop_all:
                        for r in active:
                            service.stop_serial(r.job["serial"])
                    else:
                        service.stop_serial(active[1].job["serial"])
                    release.touch()
                    released = True
                if released and not active and not service.tasks:
                    break
            assert released and not service.runners, "Load test timed out"
            assert len(created) == args.devices
            if args.timed_minutes:
                assert service.store.setting("max_parallel", 1) == 1
                assert service.store.setting("launch_interval", 2) == 2
                assert all(
                    json.loads(service.store.job(jid)["snapshot"])["runDurationMinutes"]
                    == args.timed_minutes
                    for jid in ids
                )
            states = Counter(
                service.store.job(jid)["state"] for jid in ids[: args.devices]
            )
            expected = (
                {"needs_review": args.devices}
                if args.stop_all
                else {"succeeded": args.devices - 2, "needs_review": 2}
            )
            assert states == expected, states
            assert all(
                service.store.job(jid)["state"] == "queued"
                for jid in ids[args.devices :]
            )
            assert len(window.selected_serials()) == args.devices
            rows = service.store.rows(
                "SELECT attempt_id,MAX(seq) n FROM job_events GROUP BY attempt_id"
            )
            assert len(rows) == args.devices and all(
                r["n"] >= args.events for r in rows
            )
            assert heartbeats and max(heartbeats) < 2.0, "Qt heartbeat stalled over2s"
        except Exception as exc:
            error = repr(exc)
        finally:
            service.timer.stop()
            service.shutdown()
            release.touch()
            end = time.monotonic() + 20
            while (service.runners or service.tasks) and time.monotonic() < end:
                app.processEvents()
                QTest.qWait(10)
                service.tick()
            pulse.stop()
            report = dict(
                success=not error,
                error=error,
                fixture_only=True,
                real_engine=False,
                real_phones=0,
                devices=args.devices,
                stop_all=args.stop_all,
                timed_minutes=args.timed_minutes,
                configured_max_parallel=service.store.setting("max_parallel", 1),
                configured_launch_interval=service.store.setting("launch_interval", 2),
                started_workers=len(worker_starts),
                start_spread_seconds=(
                    round(max(worker_starts) - min(worker_starts), 3)
                    if worker_starts
                    else None
                ),
                peak_workers=peak,
                created_workers=len(created),
                duration_seconds=round(time.monotonic() - started, 3),
                heartbeat_max_ms=round(max(heartbeats, default=0) * 1000, 2),
                heartbeat_p95_ms=(
                    round(sorted(heartbeats)[int(len(heartbeats) * 0.95)] * 1000, 2)
                    if heartbeats
                    else None
                ),
                ui_refresh_count=len(refreshes),
                ui_refresh_max_ms=round(max(refreshes, default=0) * 1000, 2),
                ui_refresh_median_ms=(
                    round(statistics.median(refreshes) * 1000, 2) if refreshes else None
                ),
                persisted_events=service.store.db.execute(
                    "SELECT COUNT(*) FROM job_events"
                ).fetchone()[0],
                final_states=dict(
                    Counter(
                        service.store.job(jid)["state"] for jid in ids[: args.devices]
                    )
                ),
                capacity=service.capacity,
            )
            window.update_timer.stop()
            window.allow_close = True
            window.close()
            service.store.close()
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(report, ensure_ascii=False))
        return 1 if error else 0


if __name__ == "__main__":
    raise SystemExit(main())
