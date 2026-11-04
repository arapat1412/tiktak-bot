"""Subprocess fixture for load_test.py. No engine, network, or device access."""

import json
import os
from pathlib import Path
import sys
import time


def main():
    release, ordinal, event_count = (
        Path(sys.argv[1]),
        int(sys.argv[2]),
        int(sys.argv[3]),
    )
    timed_minutes = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    gate = Path(os.environ["TAKTIK_CUSTOMER_GATE"])
    stop = Path(os.environ["TAKTIK_CUSTOMER_STOP"])
    deadline = time.monotonic() + 120
    while not gate.exists():
        if time.monotonic() > deadline:
            return 126
        time.sleep(0.01)
    print(json.dumps(dict(type="status", status="running")), flush=True)
    while not release.exists() and not stop.exists():
        if time.monotonic() > deadline:
            return 125
        time.sleep(0.02)
    # >64KB/channel exercises bounded drainage and a final result after a burst.
    lines = [
        json.dumps(
            dict(type="log", message="Fixture Việt 한글 " + "x" * 140, sequence=i),
            ensure_ascii=False,
        )
        for i in range(event_count)
    ]
    os.write(1, ("\n".join(lines) + "\n").encode("utf-8"))
    os.write(2, b"fixture diagnostic\n" * 5000)
    if ordinal != 0:
        completion = {"completion_reason": "duration_limit"} if timed_minutes else {}
        print(
            json.dumps(
                dict(
                    type="video_result",
                    stats=dict(videos_watched=1, errors=0, **completion),
                )
            ),
            flush=True,
        )
        print(
            json.dumps(dict(type="status", status="completed", **completion)),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
