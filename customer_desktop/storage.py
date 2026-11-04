"""Application-owned SQLite database; never changes engine tables."""

from contextlib import contextmanager
import json
import re
from pathlib import Path
import sqlite3
import time
import uuid

ACTIVE = ("validating", "starting", "running", "verifying", "stopping")
TERMINAL = ("succeeded", "failed", "needs_review", "cancelled")


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / "app.db"
        self.db = sqlite3.connect(self.path, timeout=5)
        self.db.row_factory = sqlite3.Row
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            self.db.close()
            raise RuntimeError(
                "Dữ liệu được tạo bởi phiên bản mới hơn; hãy nâng cấp ứng dụng."
            )
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        if version == 0:
            if self.path.stat().st_size > 4096:
                self.backup()
            self.db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS devices (
                  serial TEXT PRIMARY KEY, name TEXT NOT NULL, group_name TEXT DEFAULT '',
                  account TEXT DEFAULT '', hold INTEGER DEFAULT 0, connection TEXT DEFAULT 'offline',
                  model TEXT DEFAULT '', package TEXT DEFAULT '', version TEXT DEFAULT '', android TEXT DEFAULT '');
                CREATE TABLE IF NOT EXISTS presets(name TEXT PRIMARY KEY, snapshot TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS media_assets(
                  id TEXT PRIMARY KEY, path TEXT NOT NULL, source TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(
                  id TEXT PRIMARY KEY, serial TEXT REFERENCES devices(serial), kind TEXT NOT NULL,
                  snapshot TEXT NOT NULL, state TEXT NOT NULL, message TEXT DEFAULT '',
                  created REAL NOT NULL, run_at REAL, timezone TEXT DEFAULT 'Asia/Bangkok',
                  idempotency_key TEXT UNIQUE NOT NULL, updated REAL NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_per_device ON jobs(serial)
                  WHERE state IN ('validating','starting','running','verifying','stopping');
                CREATE TABLE IF NOT EXISTS job_attempts(
                  id TEXT PRIMARY KEY, job_id TEXT REFERENCES jobs(id), pid INTEGER,
                  identity TEXT, started REAL NOT NULL, ended REAL, result TEXT, log_dir TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS job_events(
                  attempt_id TEXT REFERENCES job_attempts(id), seq INTEGER, at REAL,
                  type TEXT, payload TEXT, PRIMARY KEY(attempt_id,seq));
                PRAGMA user_version=1;
                COMMIT;
            """)
        # Additive indexes also cover existing schema1 databases, without changing
        # their format or touching immutable snapshots.
        self.db.executescript("""
            CREATE INDEX IF NOT EXISTS jobs_state_created ON jobs(state,created);
            CREATE INDEX IF NOT EXISTS jobs_serial_state_created ON jobs(serial,state,created);
            CREATE INDEX IF NOT EXISTS jobs_schedule ON jobs(state,run_at);
            CREATE INDEX IF NOT EXISTS attempts_job_started ON job_attempts(job_id,started);
        """)
        # A previously online phone is not assumed to still be plugged in.
        self.db.execute("UPDATE devices SET connection='offline'")
        self.db.commit()
        self.backfill_accounts()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args)]

    def setting(self, key, default=None):
        row = self.db.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        self.db.execute(
            "INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value))
        )
        self.db.commit()

    def devices(self):
        forgotten = set(self.setting("forgotten_devices", []))
        app_settings = {
            row["key"]: json.loads(row["value"])
            for row in self.rows(
                "SELECT key,value FROM settings WHERE key LIKE 'tiktok_apps:%' OR key LIKE 'tiktok_choice:%'"
            )
        }
        result = []
        for d in self.rows("SELECT * FROM devices ORDER BY group_name,name,serial"):
            if d["serial"] in forgotten:
                continue
            d["applications"] = app_settings.get("tiktok_apps:" + d["serial"], [])
            d["selected_package"] = app_settings.get("tiktok_choice:" + d["serial"], "")
            if d["selected_package"]:
                d["package"] = d["selected_package"]
                app = next((a for a in d["applications"] if a["package"] == d["package"]), {})
                d["version"] = app.get("version", "")
            result.append(d)
        return result

    def select_tiktok_app(self, serial, package):
        device = next((d for d in self.devices() if d["serial"] == serial), None)
        if device is None:
            raise ValueError("Điện thoại không còn trong danh sách.")
        if package and package not in {a["package"] for a in device["applications"]}:
            raise ValueError("Ứng dụng đã chọn chưa được phát hiện trên điện thoại; hãy làm mới kết nối.")
        self.set_setting("tiktok_choice:" + serial, package)

    def device_removal_reason(self, serials):
        serials = list(dict.fromkeys(serials))
        if not serials:
            return "Chọn điện thoại mất kết nối để xóa khỏi danh sách."
        visible = {d["serial"]: d for d in self.devices()}
        for serial in serials:
            device = visible.get(serial)
            if not device:
                return "Điện thoại không còn trong danh sách; hãy chọn lại."
            label = f"{device['name']} ({serial})"
            if device["connection"] != "offline":
                return f"{label}: chỉ xóa máy đã mất kết nối."
            if self.db.execute(
                "SELECT 1 FROM jobs WHERE serial=? AND state NOT IN (?,?,?,?) LIMIT 1",
                (serial, *TERMINAL),
            ).fetchone():
                return f"{label}: còn tác vụ hoặc lịch chưa kết thúc; hãy xử lý trước khi xóa."
            if self.db.execute(
                """SELECT 1 FROM job_attempts a JOIN jobs j ON j.id=a.job_id
                   WHERE j.serial=? AND a.ended IS NULL LIMIT 1""", (serial,),
            ).fetchone():
                return f"{label}: phiên trước chưa được thu dọn; hãy chờ xử lý xong."
        return ""

    def remove_devices(self, serials):
        """Forget idle offline rows without breaking their historical foreign keys."""
        serials = list(dict.fromkeys(serials))
        with self.transaction():
            reason = self.device_removal_reason(serials)
            if reason:
                raise ValueError(reason)
            forgotten = set(self.setting("forgotten_devices", [])) | set(serials)
            self.db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                            ("forgotten_devices", json.dumps(sorted(forgotten))))
        return len(serials)

    def discover(self, devices):
        with self.transaction():
            forgotten = set(self.setting("forgotten_devices", []))
            restored = set()
            self.db.execute("UPDATE devices SET connection='offline'")
            for d in devices:
                if "applications" in d:
                    self.db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                                    ("tiktok_apps:" + d["serial"], json.dumps(d["applications"])))
                if d["connection"] in ("online", "unauthorized"):
                    restored.add(d["serial"])
                self.db.execute(
                    """INSERT INTO devices(serial,name,connection,model,package,version,android)
                  VALUES(?,?,?,?,?,?,?) ON CONFLICT(serial) DO UPDATE SET
                  connection=excluded.connection,model=excluded.model,package=excluded.package,
                  version=excluded.version,android=excluded.android""",
                    (
                        d["serial"],
                        d.get("model") or d["serial"],
                        d["connection"],
                        d.get("model", ""),
                        d.get("package", ""),
                        d.get("version", ""),
                        d.get("android", ""),
                    ),
                )
            if forgotten & restored:
                self.db.execute("UPDATE settings SET value=? WHERE key=?",
                                (json.dumps(sorted(forgotten - restored)), "forgotten_devices"))

    def save_device(self, serial, name, group_name, account, hold=None):
        self.db.execute(
            "UPDATE devices SET name=?,group_name=?,account=? WHERE serial=?",
            (
                name.strip() or serial,
                group_name.strip(),
                account.strip().lstrip("@"),
                serial,
            ),
        )
        if hold is not None:
            self.db.execute(
                "UPDATE devices SET hold=? WHERE serial=?", (bool(hold), serial)
            )
        self.db.commit()

    def observe_account(self, serial, username):
        """Keep the handle read from this phone's own profile; leave other labels alone."""
        if not isinstance(username, str):
            return False
        username = username.strip().removeprefix("@")
        if not re.fullmatch(r"[\w.]{1,64}", username):
            return False
        changed = self.db.execute(
            "UPDATE devices SET account=? WHERE serial=? AND account<>?",
            (username, serial, username),
        ).rowcount
        self.db.commit()
        return bool(changed)

    def backfill_accounts(self):
        """Recover missing labels from the latest recorded own-profile event, not visits."""
        for device in self.rows("SELECT serial FROM devices WHERE account=''"):
            latest = self.db.execute(
                """SELECT e.payload,a.log_dir FROM job_events e
                   JOIN job_attempts a ON a.id=e.attempt_id
                   JOIN jobs j ON j.id=a.job_id
                   WHERE j.serial=? AND e.type='bot_profile'
                   ORDER BY a.started DESC,e.seq DESC LIMIT 1""",
                (device["serial"],),
            ).fetchone()
            if not latest:
                continue
            try:
                event = json.loads(latest[0])
                profile = event.get("profile")
                if not isinstance(profile, dict) and event.get("raw_log") == "stdout.jsonl":
                    profile = self._own_profile_from_log(latest[1])
                if isinstance(profile, dict):
                    self.observe_account(device["serial"], profile.get("username"))
            except (ValueError, AttributeError, TypeError):
                continue

    def _own_profile_from_log(self, directory):
        """Read bounded legacy diagnostics only within this app's own log directory."""
        directory = Path(directory).resolve()
        if not directory.is_relative_to((self.root / "logs").resolve()):
            return None
        for name in ("stdout.jsonl", "stdout.jsonl.1"):
            try:
                with (directory / name).open("rb") as stream:
                    data = stream.read(4 * 1024 * 1024 + 1)
                if len(data) > 4 * 1024 * 1024:
                    continue
                for line in reversed(data.splitlines()):
                    if len(line) > 256 * 1024:
                        continue
                    try:
                        event = json.loads(line)
                    except (ValueError, UnicodeError):
                        continue
                    if isinstance(event, dict) and event.get("type") == "bot_profile":
                        return event.get("profile")
            except OSError:
                continue
        return None

    def hold(self, serial, value=True):
        self.db.execute(
            "UPDATE devices SET hold=? WHERE serial=?", (bool(value), serial)
        )
        self.db.commit()

    def presets(self):
        return {
            r["name"]: json.loads(r["snapshot"])
            for r in self.rows("SELECT * FROM presets")
        }

    def save_preset(self, name, snapshot):
        self.db.execute(
            "INSERT OR REPLACE INTO presets VALUES(?,?)",
            (name, json.dumps(snapshot, ensure_ascii=False)),
        )
        self.db.commit()

    def enqueue(self, specs, submission_id):
        ids = []
        with self.transaction():
            for i, spec in enumerate(specs):
                key = f"{submission_id}:{i}"
                existing = self.db.execute(
                    "SELECT id FROM jobs WHERE idempotency_key=?", (key,)
                ).fetchone()
                if existing:
                    ids.append(existing[0])
                    continue
                jid = uuid.uuid4().hex
                run_at = spec.get("run_at")
                self.db.execute(
                    """INSERT INTO jobs(id,serial,kind,snapshot,state,created,run_at,idempotency_key,updated)
                  VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        jid,
                        spec["serial"],
                        spec["kind"],
                        json.dumps(spec["payload"], ensure_ascii=False),
                        "scheduled" if run_at else "queued",
                        time.time(),
                        run_at,
                        key,
                        time.time(),
                    ),
                )
                ids.append(jid)
        return ids

    def jobs(self):
        return self.rows(
            """SELECT * FROM jobs WHERE state NOT IN ('succeeded','failed','needs_review','cancelled')
            OR id IN (SELECT id FROM jobs WHERE state IN ('succeeded','failed','needs_review','cancelled')
                      ORDER BY created DESC,rowid DESC LIMIT 1000) ORDER BY created DESC,rowid DESC"""
        )

    def job(self, jid):
        rows = self.rows("SELECT * FROM jobs WHERE id=?", (jid,))
        return rows[0] if rows else None

    def state(self, jid, state, message=""):
        self.db.execute(
            "UPDATE jobs SET state=?,message=?,updated=? WHERE id=? AND (state!=? OR message!=?)",
            (state, message, time.time(), jid, state, message),
        )
        self.db.commit()

    def claim(self, limit=1, max_new=None, timed_only=False):
        """Claim and reserve each serial atomically, including against other DB connections.

        timed_only restricts the claim to browse jobs whose immutable snapshot asks for a
        run duration. The active cap, hold/online checks and per-serial FIFO still consider
        every queued job, so an earlier ordinary job keeps its place.
        """
        claimed = []
        with self.transaction():
            active = self.db.execute(
                "SELECT COUNT(*) FROM jobs WHERE state IN (?,?,?,?,?)", ACTIVE
            ).fetchone()[0]
            slots = max(0, limit - active)
            if max_new is not None:
                slots = min(slots, max(0, int(max_new)))
            if not slots:
                return claimed
            timed_filter = ""
            if timed_only:
                timed_filter = """AND j.kind='browse'
                 AND CASE WHEN json_valid(j.snapshot)
                     THEN CAST(json_extract(j.snapshot,'$.runDurationMinutes') AS REAL) > 0
                     ELSE 0 END"""
            for job in self.rows(
                f"""SELECT j.* FROM jobs j JOIN devices d USING(serial)
                 WHERE j.state='queued' AND d.hold=0 AND d.connection='online'
                 AND NOT EXISTS (SELECT 1 FROM jobs a WHERE a.serial=j.serial
                     AND a.state IN ('validating','starting','running','verifying','stopping'))
                 AND j.id=(SELECT q.id FROM jobs q WHERE q.serial=j.serial AND q.state='queued'
                     ORDER BY q.created,q.rowid LIMIT 1)
                 {timed_filter}
                 ORDER BY j.created,j.rowid LIMIT ?""",
                (slots,),
            ):
                self.db.execute(
                    "UPDATE jobs SET state='validating',updated=? WHERE id=?",
                    (time.time(), job["id"]),
                )
                job["state"] = "validating"
                claimed.append(job)
        return claimed

    def due(self, now, overdue=False):
        # At startup / sleep gap, every past schedule requires a conscious choice.
        with self.transaction():
            self.db.execute(
                "UPDATE jobs SET state=?,message=?,updated=? WHERE state='scheduled' AND run_at<=?",
                (
                    "overdue" if overdue else "queued",
                    "Lịch đã quá hạn; chọn chạy hoặc hủy." if overdue else "",
                    now,
                    now,
                ),
            )

    def decide_waiting(self, jid, action):
        if action not in ("queued", "cancelled"):
            raise ValueError(action)
        self.db.execute(
            "UPDATE jobs SET state=?,message='',run_at=NULL,updated=? WHERE id=? AND state IN ('queued','scheduled','overdue')",
            (action, time.time(), jid),
        )
        self.db.commit()

    def attempt(self, job, log_dir, attempt_id=None):
        aid = attempt_id or uuid.uuid4().hex
        self.db.execute(
            "INSERT INTO job_attempts(id,job_id,started,log_dir) VALUES(?,?,?,?)",
            (aid, job["id"], time.time(), str(log_dir)),
        )
        self.db.commit()
        return aid

    def started(self, aid, pid, identity):
        self.db.execute(
            "UPDATE job_attempts SET pid=?,identity=? WHERE id=?", (pid, identity, aid)
        )
        self.db.commit()

    def end_attempt(self, aid, result):
        self.db.execute(
            "UPDATE job_attempts SET ended=?,result=? WHERE id=?",
            (time.time(), json.dumps(result, ensure_ascii=False), aid),
        )
        self.db.commit()

    def unfinished(self):
        return self.rows(
            """SELECT j.*,a.id AS attempt_id,a.pid,a.identity,a.log_dir FROM jobs j
           LEFT JOIN job_attempts a ON j.id=a.job_id AND a.ended IS NULL
           WHERE j.state IN ('validating','starting','running','verifying','stopping')"""
        )

    def events(self, aid, events, start_seq):
        self.event_batches([(aid, events, start_seq)])

    def event_batches(self, batches):
        """One short transaction for all active workers' bounded diagnostic events."""
        with self.transaction():
            for aid, events, start_seq in batches:
                self._insert_events(aid, events, start_seq)

    def _insert_events(self, aid, events, start_seq):
        self.db.executemany(
            "INSERT OR IGNORE INTO job_events VALUES(?,?,?,?,?)",
            [
                (
                    aid,
                    start_seq + i,
                    time.time(),
                    e.get("type", "unknown"),
                    json.dumps(e, ensure_ascii=False),
                )
                for i, e in enumerate(events)
            ],
        )

    def attempts(self, jid):
        return self.rows(
            "SELECT * FROM job_attempts WHERE job_id=? ORDER BY started DESC", (jid,)
        )

    def backup(self):
        dest = self.root / "backups" / f"app-{time.time_ns()}.db"
        dest.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(dest) as target:
            self.db.backup(target)
        return dest

    def close(self):
        self.db.close()
