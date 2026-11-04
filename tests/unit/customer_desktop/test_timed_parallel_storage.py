import json
import time

import pytest

from customer_desktop.paths import prepare_paths
from customer_desktop.storage import Store


def make_store(tmp_path, serials):
    store = Store(prepare_paths(tmp_path))
    store.discover(
        [dict(serial=x, connection="online", model=x, package="test") for x in serials]
    )
    return store


def ordinary(serial):
    return dict(serial=serial, kind="browse", payload={"maxVideos": 1})


def timed(serial, minutes=30):
    return dict(serial=serial, kind="browse", payload={"runDurationMinutes": minutes})


def test_timed_claim_selects_only_browse_jobs_with_a_positive_duration(tmp_path):
    s = make_store(tmp_path, ("publish", "absent", "zero", "timed"))
    ids = s.enqueue(
        [
            dict(
                serial="publish",
                kind="publish",
                payload={"localPath": "clip.mp4", "runDurationMinutes": 30},
            ),
            dict(serial="absent", kind="browse", payload={"maxVideos": 3}),
            dict(serial="zero", kind="browse", payload={"runDurationMinutes": 0}),
            timed("timed", 17),
        ],
        "submission",
    )

    claimed = s.claim(limit=10, timed_only=True)

    assert [j["id"] for j in claimed] == [ids[3]]
    assert json.loads(claimed[0]["snapshot"])["runDurationMinutes"] == 17
    assert s.job(ids[3])["state"] == "validating"
    assert [s.job(i)["state"] for i in ids[:3]] == ["queued"] * 3
    s.close()


def test_timed_claim_honours_max_new(tmp_path):
    s = make_store(tmp_path, ("a", "b", "c"))
    ids = s.enqueue([timed("a"), timed("b"), timed("c")], "submission")

    assert [j["id"] for j in s.claim(limit=10, max_new=2, timed_only=True)] == ids[:2]
    assert s.job(ids[2])["state"] == "queued"
    assert s.claim(limit=10, max_new=0, timed_only=True) == []
    assert s.job(ids[2])["state"] == "queued"
    s.close()


def test_timed_claim_skips_busy_held_offline_and_an_earlier_ordinary_job(tmp_path):
    s = make_store(tmp_path, ("busy", "held", "offline", "ordinary_first", "free"))
    busy_id = s.enqueue([ordinary("busy")], "busy")[0]
    busy_timed_id = s.enqueue([timed("busy")], "busy-timed")[0]
    ordinary_id = s.enqueue([ordinary("ordinary_first")], "ordinary")[0]
    timed_id = s.enqueue([timed("ordinary_first")], "timed-after")[0]
    free_id = s.enqueue([timed("free")], "free")[0]
    s.enqueue([timed("held")], "held")
    s.enqueue([timed("offline")], "offline")
    s.hold("held", True)
    s.db.execute("UPDATE devices SET connection='offline' WHERE serial='offline'")
    s.db.commit()

    assert [j["id"] for j in s.claim(limit=1)] == [busy_id]

    claimed = s.claim(limit=10, timed_only=True)
    assert [j["id"] for j in claimed] == [free_id]
    assert s.job(busy_timed_id)["state"] == "queued"
    assert s.job(timed_id)["state"] == "queued"

    # The ordinary job ahead of it owns the serial's FIFO head, so the timed job waits
    # for that job to finish rather than overtaking it.
    assert [j["id"] for j in s.claim(limit=10)] == [ordinary_id]
    assert s.claim(limit=10, timed_only=True) == []
    s.state(ordinary_id, "succeeded")
    assert [j["id"] for j in s.claim(limit=10, timed_only=True)] == [timed_id]
    s.close()


def test_timed_claim_cap_counts_ordinary_active_workers(tmp_path):
    s = make_store(tmp_path, ("ordinary", "a", "b", "c"))
    ordinary_id = s.enqueue([ordinary("ordinary")], "ordinary")[0]
    timed_ids = s.enqueue([timed("a"), timed("b"), timed("c")], "timed")
    assert [j["id"] for j in s.claim(limit=1)] == [ordinary_id]

    claimed = s.claim(limit=2, timed_only=True)
    assert [j["id"] for j in claimed] == [timed_ids[0]]
    assert [s.job(i)["state"] for i in timed_ids[1:]] == ["queued", "queued"]
    assert s.claim(limit=2, timed_only=True) == []
    s.close()


def test_timed_claim_is_idempotent_and_leaves_snapshots_untouched(tmp_path):
    s = make_store(tmp_path, ("a", "b"))
    specs = [timed("a", 30), timed("b", 45)]
    ids = s.enqueue(specs, "submission")
    assert ids == s.enqueue(specs, "submission")
    before = {jid: s.job(jid)["snapshot"] for jid in ids}

    claimed = s.claim(limit=2, timed_only=True)

    assert [j["id"] for j in claimed] == ids
    assert {j["id"]: j["snapshot"] for j in claimed} == before
    assert [json.loads(j["snapshot"])["runDurationMinutes"] for j in claimed] == [
        30,
        45,
    ]
    assert s.claim(limit=2, timed_only=True) == []
    s.close()


@pytest.mark.parametrize("kwargs", [{}, {"timed_only": False}])
def test_default_claim_still_takes_ordinary_and_timed_jobs(tmp_path, kwargs):
    s = make_store(tmp_path, ("a", "b"))
    ids = s.enqueue([ordinary("a"), timed("b")], "submission")

    assert [j["id"] for j in s.claim(limit=2, **kwargs)] == ids
    assert s.claim(limit=2, **kwargs) == []
    s.close()


def test_timed_claim_tolerates_a_malformed_snapshot(tmp_path):
    s = make_store(tmp_path, ("broken", "valid"))
    now = time.time()
    s.db.execute(
        """INSERT INTO jobs(id,serial,kind,snapshot,state,created,idempotency_key,updated)
           VALUES(?,?,?,?,?,?,?,?)""",
        ("broken-id", "broken", "browse", "{not json", "queued", now, "manual", now),
    )
    s.db.commit()
    valid_id = s.enqueue([timed("valid")], "valid")[0]

    assert [j["id"] for j in s.claim(limit=10, timed_only=True)] == [valid_id]
    assert s.job("broken-id")["state"] == "queued"
    s.close()
