"""Concurrent real engine database test on disposable data, with no phones.

python -m customer_desktop.packaging.database_load_test --workers 50 --report build/db-load.json
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time


def worker(ordinal, iterations):
    from taktik.core.database.local.service import LocalDatabaseService

    db = LocalDatabaseService()
    try:
        account, _ = db.tiktok.get_or_create_account(f"fixture_{ordinal}")
        assert account is not None
        session = db.tiktok.create_session(account, f"fixture-{ordinal}", "for_you")
        assert session is not None
        for i in range(iterations):
            assert db.tiktok.update_session(session, posts_watched=i + 1)
        assert db.tiktok.end_session(session, stats={"posts_watched": iterations})
        return 0
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=50, choices=range(1, 51))
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--worker", type=int)
    args = parser.parse_args()
    if args.worker is not None:
        return worker(args.worker, args.iterations)
    if args.report is None:
        parser.error("--report required")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="taktik-db-load-") as tmp:
        path = Path(tmp) / "engine.db"
        env = {**os.environ, "TAKTIK_DB_PATH": str(path)}
        env.pop("TAKTIK_DESKTOP_PID", None)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        prepared = subprocess.run(
            [sys.executable, "-m", "customer_desktop.engine_worker", "--prepare-db"],
            env=env,
            capture_output=True,
            timeout=60,
            creationflags=flags,
        )
        if prepared.returncode:
            raise RuntimeError(prepared.stderr.decode(errors="replace")[-1500:])
        env["TAKTIK_DESKTOP_PID"] = str(os.getpid())

        def run(ordinal):
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "customer_desktop.packaging.database_load_test",
                    "--worker",
                    str(ordinal),
                    "--iterations",
                    str(args.iterations),
                ],
                env=env,
                capture_output=True,
                timeout=120,
                creationflags=flags,
            )
            return dict(
                worker=ordinal,
                exit_code=result.returncode,
                error=(
                    result.stderr.decode(errors="replace")[-2000:]
                    if result.returncode
                    else ""
                ),
            )

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(run, range(args.workers)))
        with sqlite3.connect(path) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            accounts = conn.execute(
                "SELECT COUNT(*) FROM accounts WHERE platform='tiktok'"
            ).fetchone()[0]
            sessions = conn.execute(
                "SELECT COUNT(*),SUM(posts_watched) FROM sessions_unified WHERE platform='tiktok' AND status='COMPLETED'"
            ).fetchone()
            wal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()  # sqlite3's context manager commits; it does not close.
        success = (
            all(r["exit_code"] == 0 for r in results)
            and integrity == "ok"
            and accounts == sessions[0] == args.workers
            and sessions[1] == args.workers * args.iterations
        )
        report = dict(
            success=success,
            real_phones=0,
            real_engine_database=True,
            workers=args.workers,
            iterations=args.iterations,
            completed_sessions=sessions[0],
            total_watched=sessions[1],
            accounts=accounts,
            integrity=integrity,
            journal_mode=wal,
            seconds=round(time.monotonic() - started, 3),
            failures=[r for r in results if r["exit_code"]],
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False))
        return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
