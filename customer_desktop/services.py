"""Queue, one-shot schedules, recovery and background I/O."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid
import zipfile

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, QProcess

from customer_desktop.devices import scan_devices, DeviceInventory
from customer_desktop.adb_server import AdbEndpoint, discover_server_ports, recovery_endpoint
from customer_desktop.domain import build_browse, build_publish
from customer_desktop.process_guard import process_identity
from customer_desktop.runner import Runner, engine_command, environment
from customer_desktop.storage import Store
from customer_desktop.keyboard import restore_keyboard, install_keyboard
from customer_desktop.capacity import (
    MAX_PARALLEL,
    sample_capacity,
    parallel_limit,
    launch_interval,
)


class TaskSignals(QObject):
    done = Signal(object)
    error = Signal(str)


class Task(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = TaskSignals()

    def run(self):
        try:
            self.signals.done.emit(self.fn())
        except Exception as exc:
            self.signals.error.emit(str(exc))


def import_specs(root, specs):
    """Immutable managed media. Hashing/copying/checks stay outside the GUI thread."""
    ready, assets = [], []
    for spec in specs:
        payload = dict(spec["payload"])
        if spec["kind"] == "publish":
            payload = build_publish(
                spec["serial"],
                payload["localPath"],
                payload.get("caption", ""),
                payload.get("hashtags", []),
                payload.get("botUsername", ""),
            ) | {k: v for k, v in payload.items() if k == "packageName"}
            source = Path(payload["localPath"])
            temp = Path(root) / "media" / (uuid.uuid4().hex + ".tmp")
            digest = hashlib.sha256()
            try:
                with source.open("rb") as src, temp.open("wb") as dst:
                    while chunk := src.read(1024 * 1024):
                        digest.update(chunk)
                        dst.write(chunk)
                asset_id = digest.hexdigest()
                target = temp.with_name(asset_id + source.suffix.lower())
                if target.exists():
                    temp.unlink()
                else:
                    temp.replace(target)
                assets.append(
                    dict(
                        id=asset_id,
                        path=str(target),
                        source=str(source),
                        size=target.stat().st_size,
                        sha256=asset_id,
                    )
                )
                payload["localPath"] = str(target)
                payload["_customerMediaHash"] = asset_id
            finally:
                temp.unlink(missing_ok=True)
        else:
            payload = build_browse(spec["serial"], payload)
        run_at = spec.get("run_at")
        if run_at is not None and (
            not isinstance(run_at, (int, float)) or run_at <= time.time()
        ):
            raise ValueError("Giờ đặt lịch phải ở tương lai (Asia/Bangkok, UTC+7).")
        ready.append({**spec, "payload": payload})
    return ready, assets


def validate_job(job):
    payload = json.loads(job["snapshot"])
    if job["kind"] == "publish":
        build_publish(
            job["serial"],
            payload["localPath"],
            payload.get("caption", ""),
            payload.get("hashtags", []),
            payload.get("botUsername", ""),
        )
        if expected := payload.get("_customerMediaHash"):
            h = hashlib.sha256()
            with open(payload["localPath"], "rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    h.update(chunk)
            if h.hexdigest() != expected:
                raise ValueError(
                    "Video quản lý đã thay đổi. Tạo lại tác vụ sau khi kiểm tra."
                )
    else:
        build_browse(job["serial"], payload)
    return True


from customer_desktop.licensing import LicenseManager, LicenseError


class DesktopService(QObject):
    changed = Signal()
    notice = Signal(str)
    submitted = Signal(list)
    closing_ready = Signal()
    capacity_changed = Signal()
    keyboard_finished = Signal(list)

    def __init__(
        self,
        root,
        parent=None,
        runner_factory=Runner,
        prepare=True,
        capacity_probe=None,
        clock=None,
        license_manager=None,
    ):
        super().__init__(parent)
        self.root = Path(root)
        self.license_manager = license_manager or LicenseManager(root)
        self.license_status = self.license_manager.check()
        self.next_license_check = 0
        self.store = Store(root)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self.cleanup_pool = QThreadPool(self)
        self.cleanup_pool.setMaxThreadCount(4)
        self.monitor_pool = QThreadPool(self)
        self.monitor_pool.setMaxThreadCount(1)
        self.inventory_pool = QThreadPool(self)
        self.inventory_pool.setMaxThreadCount(1)
        self.clock = clock or time.monotonic
        self.capacity_probe = capacity_probe or sample_capacity
        self.capacity = None
        self.capacity_at = None
        self.capacity_pending = False
        self.next_capacity = 0
        self.next_launch = 0
        self.next_inventory = 0
        self.inventory_at = None
        self.inventory_error = ""
        self.last_admission_reason = None
        self.poll_devices = prepare
        self.pending_events = {}
        self.pending_event_bytes = 0
        self.tasks = set()
        self.runners = {}
        self.validating = set()
        self.runner_factory = runner_factory
        self.ready = not prepare
        self.closing = False
        self.scanning = False
        self.keyboard_installing = set()
        self.inventory = DeviceInventory()
        self.device_ports = {}
        self.submitting = False
        self.recovery = self.store.unfinished()
        self.recovering_ids = set()
        self.last_tick = time.time()
        self.dirty = False
        self.store.due(time.time(), overdue=True)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.prepare_process = None
        if prepare:
            QTimer.singleShot(0, self.prepare_engine)

    @property
    def adb(self):
        # Let the child process resolve PATH. shutil.which here repeatedly stats
        # every PATH directory on the GUI thread (very costly with50 workers).
        return self.store.setting("adb", "") or "adb"

    def adb_for(self, serial):
        return AdbEndpoint(
            self.adb, self.device_ports.get(serial, self.store.setting("adb_port", 5037))
        )

    def background(self, fn, done, failed=None, pool=None):
        task = Task(fn)
        self.tasks.add(task)

        def finish(value):
            self.tasks.discard(task)
            try:
                done(value)
            except Exception as exc:
                (failed or self.notice.emit)("Không xử lý được dữ liệu: " + str(exc))

        def error(message):
            self.tasks.discard(task)
            (failed or self.notice.emit)(message)

        task.signals.done.connect(finish)
        task.signals.error.connect(error)
        (pool or self.pool).start(task)

    @property
    def admission_reason(self):
        if self.keyboard_installing:
            return "Đang cài bàn phím; hàng đợi sẽ tiếp tục khi cài xong."
        if not self.license_status.valid:
            return self.license_status.message
        if self.capacity_at is None:
            return "Đang kiểm tra RAM và dung lượng đĩa trước khi nhận việc mới."
        if self.clock() - self.capacity_at > 15:
            return "Số đo tài nguyên đã cũ; chờ kiểm tra trước khi nhận việc mới."
        reason = self.capacity.get("reason", "")
        if reason:
            return reason
        if self.poll_devices:
            if self.inventory_error:
                return "Chưa kiểm tra được ADB; tạm chờ nhận việc mới."
            if self.inventory_at is None or self.clock() - self.inventory_at > 45:
                return "Chờ cập nhật kết nối điện thoại trước khi nhận việc mới."
        return ""

    def _poll_capacity(self):
        if self.capacity_pending or self.clock() < self.next_capacity:
            return
        self.capacity_pending = True
        self.next_capacity = self.clock() + 5

        def finish(value):
            self.capacity_pending = False
            self.capacity, self.capacity_at = value, self.clock()
            self.capacity_changed.emit()
            # Also supports a single manual tick while the periodic timer is stopped.
            if not self.closing:
                self.tick()

        self.background(
            lambda: self.capacity_probe(self.root),
            finish,
            lambda message: finish(dict(reason="Không đo được tài nguyên: " + message)),
            pool=self.monitor_pool,
        )

    def flush_events(self):
        if not self.pending_events:
            return
        self.store.event_batches(
            [(aid, items, seq) for aid, (items, seq) in self.pending_events.items()]
        )
        self.pending_events.clear()
        self.pending_event_bytes = 0

    def prepare_engine(self):
        p = self.prepare_process = QProcess(self)
        p.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        env = environment(self.root, self.adb)
        env.remove("TAKTIK_DESKTOP_PID")
        p.setProcessEnvironment(env)
        self.prepare_out = bytearray()
        self.prepare_err = bytearray()

        def collect(buffer, data):
            buffer.extend(data)
            if len(buffer) > 65536:
                del buffer[:-65536]

        p.readyReadStandardOutput.connect(
            lambda: collect(self.prepare_out, bytes(p.readAllStandardOutput()))
        )
        p.readyReadStandardError.connect(
            lambda: collect(self.prepare_err, bytes(p.readAllStandardError()))
        )

        def finish(code, *_):
            self.prepare_out.extend(bytes(p.readAllStandardOutput()))
            try:
                lines = [
                    json.loads(line)
                    for line in self.prepare_out.decode("utf-8").splitlines()
                    if line.startswith("{")
                ]
                self.ready = code == 0 and any(
                    e.get("type") == "database_ready" and e.get("success") is True
                    for e in lines
                )
            except ValueError:
                self.ready = False
            (self.root / "logs" / "database-prepare.log").write_bytes(
                bytes(self.prepare_out[-65536:]) + bytes(self.prepare_err[-65536:])
            )
            self.notice.emit(
                "Engine sẵn sàng."
                if self.ready
                else "Chưa chuẩn bị được database engine. Xem nhật ký, đóng rồi mở lại ứng dụng."
            )
            self.changed.emit()

        p.finished.connect(finish)
        p.errorOccurred.connect(
            lambda e: (
                self.notice.emit("Không mở được engine: " + p.errorString())
                if e == QProcess.FailedToStart
                else None
            )
        )
        exe, args = engine_command()
        p.start(exe, [*args, "--prepare-db"])
        QTimer.singleShot(
            60000, lambda: p.kill() if p.state() != QProcess.NotRunning else None
        )

    def refresh_devices(self):
        if self.scanning or self.closing:
            return
        self.scanning = True
        self.next_inventory = self.clock() + 10

        def finish(devices):
            self.scanning = False
            self.inventory_at = self.clock()
            self.inventory_error = ""
            self.device_ports = {
                d["serial"]: d["adb_port"] for d in devices
                if d["connection"] == "online" and "adb_port" in d
            }
            self.store.discover(devices)
            online = {d["serial"] for d in devices if d["connection"] == "online"}
            for jid, runner in list(self.runners.items()):
                serial = runner.job["serial"]
                launched_port = getattr(getattr(runner, "adb", None), "port", None)
                moved = launched_port is not None and self.device_ports.get(serial) != launched_port
                if serial not in online or moved:
                    self.stop_serial(runner.job["serial"])
            self.changed.emit()
            if not devices:
                self.notice.emit(
                    "Chưa thấy điện thoại. Cắm USB, bật USB debugging và chấp nhận quyền ADB."
                )

        def fail(message):
            self.scanning = False
            self.inventory_error = message
            self.notice.emit("Không đọc được ADB: " + message)

        adb = self.adb
        primary = self.store.setting("adb_port", 5037)
        self.background(
            lambda: scan_devices(adb, inventory=self.inventory,
                                 ports=discover_server_ports(primary), start_if_missing=True),
            finish,
            fail,
            pool=self.inventory_pool,
        )

    def install_device_keyboard(self, serial):
        # Preserve the single-device API and its validation errors.
        device = next((d for d in self.store.devices() if d["serial"] == serial), None)
        if not device or device["connection"] != "online":
            raise ValueError("Chọn điện thoại đã kết nối và chấp nhận quyền ADB.")
        if not self.manual_ready(serial):
            raise ValueError("Máy đang chạy tác vụ hoặc đang cài bàn phím. Chờ xong rồi thử lại.")
        self.install_device_keyboards([serial])

    def install_device_keyboards(self, serials):
        if self.closing:
            raise ValueError("Ứng dụng đang đóng; hãy mở lại trước khi cài bàn phím.")
        if self.keyboard_installing:
            raise ValueError("Đang cài bàn phím. Chờ đợt hiện tại hoàn tất.")
        serials = list(dict.fromkeys(serials))
        if not serials:
            raise ValueError("Chọn ít nhất một điện thoại để cài ADBKeyboard.")
        devices = {d["serial"]: d for d in self.store.devices()}
        pending, results = [], []
        for serial in serials:
            device = devices.get(serial)
            reason = (
                "Chưa kết nối hoặc chưa chấp nhận quyền ADB."
                if not device or device["connection"] != "online"
                else "Máy còn tác vụ đang chạy hoặc đang phục hồi."
                if not self.manual_ready(serial) else ""
            )
            if reason:
                results.append(dict(serial=serial, status="skipped", message=reason))
            else:
                pending.append(serial)
        reserved = set(pending)
        self.keyboard_installing.update(reserved)
        self.changed.emit()

        def complete():
            self.keyboard_installing.difference_update(reserved)
            self.changed.emit()
            ordered = sorted(results, key=lambda r: serials.index(r["serial"]))
            counts = {key: sum(r["status"] == key for r in ordered)
                      for key in ("installed", "existing", "failed", "skipped")}
            self.notice.emit(
                f"ADBKeyboard: đã cài {counts['installed']}, có sẵn {counts['existing']}, "
                f"lỗi {counts['failed']}, bỏ qua {counts['skipped']}."
            )
            self.keyboard_finished.emit(ordered)

        def next_device():
            if self.closing:
                results.extend(dict(serial=s, status="skipped", message="Ứng dụng đang đóng.") for s in pending)
                pending.clear()
            if not pending:
                complete()
                return
            serial = pending.pop(0)
            target = self.adb_for(serial)
            self.notice.emit(f"{serial}: đang kiểm tra và cài ADBKeyboard…")

            def finished(result=None, failure=None):
                if failure:
                    status, detail = "failed", failure
                else:
                    status = "existing" if result["already_installed"] else "installed"
                    detail = "Đã có sẵn, đã kiểm tra và bật." if status == "existing" else "Đã cài và bật."
                results.append(dict(serial=serial, status=status, message=detail))
                self.notice.emit(f"{serial}: {detail}")
                next_device()

            self.background(
                lambda: install_keyboard(target, serial),
                finished,
                lambda message: finished(failure=message),
            )

        next_device()

    def submit(self, specs, submission_id=None):
        self.license_status = self.license_manager.check()
        if not self.license_status.valid:
            raise LicenseError(self.license_status.message)
        if self.closing or self.submitting:
            return
        devices = {d["serial"]: d for d in self.store.devices()}
        for spec in specs:
            if spec["serial"] not in devices:
                raise ValueError("Điện thoại không còn trong danh sách.")
        # Copy before background import. Choices made later cannot retarget this job.
        specs = [{**s, "payload": dict(s["payload"])} for s in specs]
        for spec in specs:
            device = devices[spec["serial"]]
            package = (
                spec["payload"].get("packageName")
                or device.get("selected_package")
                or device["package"]
            )
            installed = {a["package"] for a in device.get("applications", [])}
            if not package or (installed and package not in installed) or (
                device.get("selected_package") and package not in installed
            ) or (
                spec["payload"].get("packageName") and package not in installed
            ):
                raise ValueError("Ứng dụng TikTok đã chọn không còn trên máy; hãy làm mới và chọn lại.")
            spec["payload"]["packageName"] = package
        self.submitting = True
        key = submission_id or uuid.uuid4().hex

        def finish(data):
            ready, assets = data
            with self.store.transaction():
                for a in assets:
                    self.store.db.execute(
                        "INSERT OR IGNORE INTO media_assets VALUES(?,?,?,?,?)",
                        tuple(a[k] for k in ("id", "path", "source", "size", "sha256")),
                    )
            ids = self.store.enqueue(ready, key)
            self.submitting = False
            self.submitted.emit(ids)
            self.changed.emit()

        def fail(message):
            self.submitting = False
            self.notice.emit("Chưa tạo tác vụ: " + message)

        self.background(lambda: import_specs(self.root, specs), finish, fail)

    def tick(self):
        if self.clock() >= self.next_license_check:
            self.next_license_check = self.clock() + 5
            previous = self.license_status
            self.license_status = self.license_manager.check()
            if not self.license_status.valid:
                for runner in list(self.runners.values()):
                    self.stop_serial(runner.job["serial"])
                if previous.valid:
                    self.notice.emit(self.license_status.message)
            if previous != self.license_status:
                self.capacity_changed.emit()
        self.flush_events()
        now = time.time()
        gap = now - self.last_tick > 15 or now < self.last_tick
        self.store.due(now, overdue=gap)
        self.last_tick = now
        if gap and self.runners:
            for runner in list(self.runners.values()):
                self.stop_serial(runner.job["serial"])
            self.notice.emit(
                "PC vừa thức dậy hoặc đồng hồ thay đổi. Đã yêu cầu dừng các phiên đang chạy để đối chiếu điện thoại."
            )
        # Never reset DB while a matching/unknown old process might still drive a phone.
        for job in list(self.recovery):
            if job["id"] in self.recovering_ids:
                continue
            identity = process_identity(job.get("pid"))
            if identity is not None and (
                identity == "unknown"
                or job.get("identity") in (None, "unknown")
                or identity == job["identity"]
            ):
                continue
            self.recovering_ids.add(job["id"])

            def recovered(message="", j=job):
                if j.get("attempt_id"):
                    self.store.end_attempt(
                        j["attempt_id"],
                        {
                            "state": "interrupted",
                            "message": "Ứng dụng bị gián đoạn; không chạy lại tự động.",
                        },
                    )
                self.store.state(
                    j["id"],
                    "needs_review",
                    "Phiên trước bị gián đoạn. Kiểm tra điện thoại trước khi chạy mới. "
                    + message,
                )
                self.store.hold(j["serial"])
                self.recovery.remove(j)
                self.recovering_ids.discard(j["id"])
                self.changed.emit()

            adb = self.adb_for(job["serial"])
            self.background(
                lambda j=job, target=adb: restore_keyboard(
                    recovery_endpoint(target, j["serial"], j.get("log_dir") or self.root / "logs" / "absent"),
                    j["serial"],
                    j.get("log_dir") or self.root / "logs" / "absent",
                ),
                lambda _, fn=recovered: fn(),
                lambda msg, fn=recovered: fn("Chưa khôi phục bàn phím: " + msg),
                pool=self.cleanup_pool,
            )
        if self.closing:
            if (
                not self.runners
                and not self.validating
                and not self.tasks
                and (
                    not self.prepare_process
                    or self.prepare_process.state() == QProcess.NotRunning
                )
            ):
                self.closing_ready.emit()
            return
        self._poll_capacity()
        if self.poll_devices and self.clock() >= self.next_inventory:
            self.refresh_devices()
        if self.admission_reason != self.last_admission_reason:
            self.last_admission_reason = self.admission_reason
            self.capacity_changed.emit()
        self._admit_jobs()
        if self.dirty:
            self.dirty = False
            self.changed.emit()

    def _admit_jobs(self):
        if not self.ready or self.closing or self.admission_reason:
            return
        # Timed sessions run together on the selected phones. Bound preparation
        # work while refilling from callbacks, without the ordinary launch delay.
        jobs = self.store.claim(
            MAX_PARALLEL, max_new=max(0, 4 - len(self.validating)), timed_only=True
        )
        if not jobs and not self.validating and self.clock() >= self.next_launch:
            jobs = self.store.claim(
                parallel_limit(self.store.setting("max_parallel", 1)), max_new=1
            )
        for job in jobs:
            self.validating.add(job["id"])
            self.background(
                lambda j=job: validate_job(j),
                lambda _, j=job: self._validated(j),
                lambda msg, j=job: self._validation_failed(j, msg),
            )

    def _validated(self, job):
        self._launch(job)
        self._admit_jobs()

    def _validation_failed(self, job, message):
        self.validating.discard(job["id"])
        self.store.state(job["id"], "failed", message)
        self.changed.emit()
        self._admit_jobs()

    def _launch(self, job):
        self.license_status = self.license_manager.check()
        self.validating.discard(job["id"])
        devices = {d["serial"]: d for d in self.store.devices()}
        device = devices[job["serial"]]
        if (
            self.closing
            or device["hold"]
            or self.store.job(job["id"])["state"] != "validating"
        ):
            self.store.state(job["id"], "cancelled", "Đã hủy trước khi khởi chạy.")
            self.changed.emit()
            return
        if device["connection"] != "online" or not device["package"]:
            self.store.state(
                job["id"], "failed", "Điện thoại mất kết nối hoặc chưa cài TikTok."
            )
            self.changed.emit()
            return
        # Admission may have changed during hashing. This attempt has not started;
        # returning it to the queue cannot replay an interaction.
        if self.admission_reason:
            self.store.state(job["id"], "queued", self.admission_reason)
            self.changed.emit()
            return
        aid = uuid.uuid4().hex
        directory = self.root / "logs" / job["id"] / aid
        attempt = self.store.attempt(job, directory, aid)
        # The actual attempt ID is the storage ID, also used in config/artifacts.
        try:
            runner = self.runner_factory(
                self.root, job, attempt, directory, self.adb_for(job["serial"]), self
            )
        except Exception as exc:
            self.store.end_attempt(attempt, {"state": "failed", "message": str(exc)})
            self.store.state(
                job["id"], "failed", "Không chuẩn bị được worker: " + str(exc)
            )
            self.changed.emit()
            return
        self.runners[job["id"]] = runner
        self.store.state(job["id"], "starting", "Đang mở engine...")
        seq = [0]
        event_bytes = [0]

        def events(items):
            # Bound DB event growth; raw capped logs remain available per attempt.
            keep = []
            keep_bytes = 0
            for event in items[: max(0, 10000 - seq[0])]:
                size = len(json.dumps(event, ensure_ascii=False).encode("utf-8"))
                profile = event.get("profile")
                if event.get("type") == "bot_profile" and isinstance(profile, dict):
                    # Avatars can exceed the event limit; retain the own-account
                    # handle so restart backfill does not lose it with the image.
                    event = {
                        "type": "bot_profile",
                        "profile": {"username": profile.get("username")},
                    }
                    size = len(json.dumps(event, ensure_ascii=False).encode("utf-8"))
                if size > 8192:
                    event = {
                        "type": event.get("type", "unknown"),
                        "raw_log": "stdout.jsonl",
                        "message": "Sự kiện lớn được lưu trong nhật ký gốc.",
                        "bytes": size,
                    }
                    size = 200
                if event_bytes[0] + size > 8 * 1024 * 1024:
                    break
                keep.append(event)
                keep_bytes += size
                event_bytes[0] += size
            if keep:
                if attempt not in self.pending_events:
                    self.pending_events[attempt] = ([], seq[0])
                self.pending_events[attempt][0].extend(keep)
                self.pending_event_bytes += keep_bytes
                seq[0] += len(keep)
                if self.pending_event_bytes >= 512 * 1024:
                    self.flush_events()
            for e in items:
                if (
                    e.get("type") == "bot_profile"
                    and not runner.stopped
                    and self.runners.get(job["id"]) is runner
                ):
                    profile = e.get("profile")
                    if isinstance(profile, dict):
                        self.store.observe_account(job["serial"], profile.get("username"))
                if e.get("type") == "status" and not runner.stopped:
                    status = e.get("status")
                    messages = {
                        "connecting": "Đang kết nối điện thoại.",
                        "verifying_account": "Đang đối chiếu tài khoản TikTok.",
                        "navigating": "Đang mở màn hình đăng.",
                        "selecting": "Đang chọn video / ảnh.",
                        "filling": "Đang nhập nội dung.",
                        "publishing": "Đang đăng; chờ TikTok xác nhận.",
                        "running": "Engine đang chạy.",
                        "completed": "Đang xác minh kết quả.",
                        "success": "Đang xác minh kết quả.",
                    }
                    if status in messages:
                        self.store.state(
                            job["id"],
                            (
                                "verifying"
                                if status in ("completed", "success")
                                else "running"
                            ),
                            messages[status],
                        )
                if (
                    e.get("type") == "log"
                    and "Pushing file to device:" in e.get("message", "")
                    and not runner.stopped
                ):
                    self.store.state(
                        job["id"], "running", "Đang chuyển video / ảnh vào điện thoại."
                    )
            self.dirty = True

        def started(pid, identity):
            self.store.started(attempt, pid, identity)
            self.store.state(
                job["id"],
                "stopping" if runner.stopped else "running",
                "Đang dừng..." if runner.stopped else "Engine đang chạy.",
            )
            self.dirty = True

        def done(state, message, result):
            self.flush_events()

            def cleaned(restore_error=""):
                final_state = "needs_review" if restore_error else state
                final_message = message + (
                    " Chưa khôi phục bàn phím: " + restore_error
                    if restore_error
                    else ""
                )
                self.store.end_attempt(
                    attempt,
                    {
                        **result,
                        "state": final_state,
                        "message": final_message,
                        "keyboard_restored": not bool(restore_error),
                    },
                )
                self.store.state(job["id"], final_state, final_message)
                if final_state == "needs_review":
                    self.store.hold(job["serial"])
                self.runners.pop(job["id"], None)
                runner.deleteLater()
                self.changed.emit()

            self.store.state(
                job["id"], "stopping", "Worker đã dừng; đang khôi phục bàn phím gốc."
            )
            adb = self.adb_for(job["serial"])
            self.background(
                lambda: restore_keyboard(recovery_endpoint(adb, job["serial"], directory), job["serial"], directory),
                lambda _: cleaned(),
                cleaned,
                pool=self.cleanup_pool,
            )

        runner.events.connect(events)
        runner.started.connect(started)
        runner.done.connect(done)
        if not (
            job["kind"] == "browse"
            and json.loads(job["snapshot"]).get("runDurationMinutes", 0) > 0
        ):
            self.next_launch = self.clock() + launch_interval(
                self.store.setting("launch_interval", 2)
            )
        runner.start()
        self.changed.emit()

    def device_removal_reason(self, serials):
        selected = set(serials)
        if self.closing:
            return "Ứng dụng đang đóng; hãy chờ mở lại trước khi xóa máy."
        if self.submitting:
            return "Đang tạo tác vụ; hãy chờ hoàn tất trước khi xóa máy."
        if selected & self.keyboard_installing:
            return "Máy đang cài bàn phím; hãy chờ hoàn tất trước khi xóa."
        if any(r.job["serial"] in selected for r in self.runners.values()):
            return "Máy còn worker hoặc đang khôi phục bàn phím; hãy chờ kết thúc."
        if any(j["serial"] in selected for j in self.recovery):
            return "Máy đang phục hồi phiên trước; hãy chờ xử lý xong."
        for jid in self.validating:
            job = self.store.job(jid)
            if job and job["serial"] in selected:
                return "Máy đang chuẩn bị tác vụ; hãy chờ kết thúc."
        return self.store.device_removal_reason(selected)

    def remove_devices(self, serials):
        serials = list(dict.fromkeys(serials))
        reason = self.device_removal_reason(serials)
        if reason:
            raise ValueError(reason)
        count = self.store.remove_devices(serials)
        for serial in serials:
            self.device_ports.pop(serial, None)
        self.changed.emit()
        return count

    def stop_serial(self, serial):
        self.store.hold(serial, True)
        for jid, runner in list(self.runners.items()):
            if runner.job["serial"] == serial:
                self.store.state(
                    jid, "stopping", "Đang dừng; chờ worker và tiến trình con kết thúc."
                )
                runner.stop()
        self.changed.emit()

    def manual_ready(self, serial):
        return serial not in self.keyboard_installing and not any(
            j["serial"] == serial for j in self.store.unfinished()
        )

    def release_serial(self, serial):
        if not self.manual_ready(serial):
            raise ValueError(
                "Máy còn worker đang chạy hoặc đang phục hồi. Chờ dừng xong."
            )
        self.store.hold(serial, False)
        self.changed.emit()

    def cancel(self, jid):
        self.store.decide_waiting(jid, "cancelled")
        self.changed.emit()

    def run_waiting(self, jid):
        self.store.decide_waiting(jid, "queued")
        self.changed.emit()

    def shutdown(self):
        self.closing = True
        for d in self.store.devices():
            if any(r.job["serial"] == d["serial"] for r in self.runners.values()):
                self.stop_serial(d["serial"])
        self.tick()

    def support_export(self):
        # Opt-in raw logs are deliberately not included. Avoid captions/accounts/serials,
        # screenshots, database contents or environment secrets in a support bundle.
        report = dict(
            app="TikTokKorean 0.1.0",
            python=sys.version,
            platform=sys.platform,
            jobs=[dict(kind=j["kind"], state=j["state"]) for j in self.store.jobs()],
            settings=dict(
                max_parallel=parallel_limit(self.store.setting("max_parallel", 1))
            ),
            capacity={
                key: (self.capacity or {}).get(key)
                for key in ("disk_free", "memory_available", "memory_total")
            },
        )
        dest = self.root / "exports" / f"ho-tro-{time.time_ns()}.zip"
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(
                "diagnostics.json", json.dumps(report, ensure_ascii=False, indent=2)
            )
        return dest

    def prune_logs(self, days):
        cutoff = time.time() - int(days) * 86400
        active = {
            j["id"]
            for j in self.store.jobs()
            if j["state"] not in ("succeeded", "failed", "needs_review", "cancelled")
        }

        def prune():
            count = 0
            for name in ("logs", "artifacts"):
                for directory in (self.root / name).iterdir():
                    if (
                        directory.is_dir()
                        and directory.name not in active
                        and directory.stat().st_mtime < cutoff
                    ):
                        shutil.rmtree(directory)
                        count += 1
            return count

        self.background(
            prune,
            lambda n: self.notice.emit(
                f"Đã dọn {n} thư mục nhật ký/ảnh quá hạn. Video gốc được giữ nguyên."
            ),
        )
