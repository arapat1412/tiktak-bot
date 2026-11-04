import json
import sqlite3
import time

import pytest

from customer_desktop.paths import prepare_paths
from customer_desktop.storage import Store
from customer_desktop.services import import_specs, validate_job


def make_store(tmp_path):
    s = Store(prepare_paths(tmp_path))
    s.discover(
        [
            dict(serial=x, connection="online", model=x, package="test")
            for x in ("a", "b")
        ]
    )
    return s


def test_atomic_claim_idempotency_and_snapshots(tmp_path):
    s = make_store(tmp_path)
    payload = {"maxVideos": 1}
    specs = [dict(serial=x, kind="browse", payload=payload) for x in ("a", "a", "b")]
    ids = s.enqueue(specs, "submission")
    assert ids == s.enqueue(specs, "submission")
    payload["maxVideos"] = 99
    assert json.loads(s.job(ids[0])["snapshot"])["maxVideos"] == 1
    assert len(s.claim(1)) == 1
    assert s.claim(1) == []
    assert [j["serial"] for j in s.claim(2)] == ["b"]
    # The SQL partial unique index enforces the rule even outside claim().
    try:
        s.db.execute("UPDATE jobs SET state='running' WHERE id=?", (ids[1],))
    except sqlite3.IntegrityError:
        s.db.rollback()
    else:
        raise AssertionError("Duplicate device was accepted")
    s.close()


def test_schedule_overdue_cancel_and_no_replay(tmp_path):
    s = make_store(tmp_path)
    now = time.time()
    ids = s.enqueue([dict(serial="a", kind="browse", payload={}, run_at=now - 1)], "x")
    s.due(now, overdue=True)
    assert s.job(ids[0])["state"] == "overdue"
    assert s.claim(1) == []
    s.decide_waiting(ids[0], "queued")
    assert len(s.claim(1)) == 1
    s.state(ids[0], "needs_review")
    s.decide_waiting(ids[0], "queued")
    assert s.job(ids[0])["state"] == "needs_review"
    s.close()


def test_persistence_backup_and_hold(tmp_path):
    s = make_store(tmp_path)
    s.save_device("a", "Máy 한글", "Nhóm A", "fixture", True)
    ids = s.enqueue([dict(serial="a", kind="browse", payload={})], "x")
    assert s.claim(2) == []
    backup = s.backup()
    assert backup.is_file()
    s.close()
    s = Store(tmp_path)
    d = next(d for d in s.devices() if d["serial"] == "a")
    assert d["name"] == "Máy 한글" and d["hold"] and d["connection"] == "offline"
    assert s.job(ids[0])["state"] == "queued"
    s.close()


def test_managed_media_hash_and_validation(tmp_path):
    root = prepare_paths(tmp_path / "data")
    source = tmp_path / "một 한글.mp4"
    source.write_bytes(b"fixture media")
    specs = [
        dict(
            kind="publish",
            serial="a",
            payload=dict(localPath=str(source), caption="Chào\n한글"),
        )
    ]
    ready, assets = import_specs(root, specs)
    assert "botUsername" not in ready[0]["payload"]
    path = ready[0]["payload"]["localPath"]
    assert Path(path).read_bytes() == source.read_bytes()
    assert path != str(source)
    job = dict(serial="a", kind="publish", snapshot=json.dumps(ready[0]["payload"]))
    assert validate_job(job)
    Path(path).write_bytes(b"changed")
    with pytest.raises(ValueError, match="thay đổi"):
        validate_job(job)
    assert source.read_bytes() == b"fixture media"


@pytest.mark.parametrize("legacy", ["", "@tai_khoan_cu"])
def test_legacy_account_value_cannot_reintroduce_publish_account(tmp_path, legacy):
    root = prepare_paths(tmp_path / "data")
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture media")
    specs = [
        dict(
            kind="publish",
            serial="a",
            payload=dict(
                localPath=str(source),
                caption="Bài mới",
                hashtags=["#mot"],
                botUsername=legacy,
            ),
        )
    ]
    ready, assets = import_specs(root, specs)
    assert len(assets) == 1
    assert "botUsername" not in ready[0]["payload"]
    job = dict(serial="a", kind="publish", snapshot=json.dumps(ready[0]["payload"]))
    assert validate_job(job)


from pathlib import Path


def test_schema_upgrade_backs_up_and_future_schema_is_refused(tmp_path):
    import pytest

    s = make_store(tmp_path)
    s.save_device("a", "Dữ liệu cũ", "Nhóm", "fixture")
    s.db.execute("PRAGMA user_version=0")
    s.db.commit()
    s.close()
    s = Store(tmp_path)
    assert any(d["name"] == "Dữ liệu cũ" for d in s.devices())
    assert list((tmp_path / "backups").glob("*.db"))
    s.db.execute("PRAGMA user_version=2")
    s.db.commit()
    s.close()
    with pytest.raises(RuntimeError, match="phiên bản mới hơn"):
        Store(tmp_path)
