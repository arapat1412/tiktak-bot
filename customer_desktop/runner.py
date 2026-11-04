"""Nonblocking QProcess bridge host with bounded diagnostics and Windows containment."""

import json
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from customer_desktop.process_guard import JobGuard, process_identity
from customer_desktop.adapters.taktik.protocol import LineDecoder, ResultTracker
from customer_desktop import console
from customer_desktop.adb_server import endpoint_environment


def engine_command():
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).parent / "engine" / "customer_engine.exe"
        return str(exe), []
    return sys.executable, ["-u", "-m", "customer_desktop.engine_worker"]


def environment(root, adb):
    env = QProcessEnvironment.systemEnvironment()
    env.insert("PYTHONIOENCODING", "utf-8")
    env.insert("PYTHONUTF8", "1")
    env.insert("TAKTIK_DB_PATH", str(Path(root) / "engine" / "taktik-data.db"))
    env.insert("ADBUTILS_ADB_PATH", adb)
    if getattr(adb, "port", None) is not None:
        for key, value in endpoint_environment(adb.port).items():
            env.insert(key, value)
    if Path(adb).is_absolute():
        env.insert("PATH", str(Path(adb).parent) + os.pathsep + env.value("PATH"))
    return env


class CappedLog:
    def __init__(self, path, max_bytes=4 * 1024 * 1024):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.size = 0
        self.file = self.path.open("ab")

    def write(self, data):
        if self.size + len(data) > self.max_bytes:
            self.file.close()
            previous = self.path.with_suffix(self.path.suffix + ".1")
            previous.unlink(missing_ok=True)
            self.path.replace(previous)
            self.file = self.path.open("wb")
            self.size = 0
        data = data[-self.max_bytes :]
        self.file.write(data)
        self.file.flush()
        self.size += len(data)

    def close(self):
        self.file.close()


class Runner(QObject):
    events = Signal(list)
    started = Signal(int, str)
    done = Signal(str, str, dict)

    def __init__(self, root, job, aid, directory, adb, parent=None, command=None):
        super().__init__(parent)
        self.root, self.job, self.aid = Path(root), job, aid
        self.adb = adb
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        if getattr(adb, "port", None) is not None:
            (self.directory / "adb-server.json").write_text(
                json.dumps({"port": adb.port}), encoding="utf-8"
            )
        self.stop_path = self.directory / "stop.request"
        self.gate_path = self.directory / "start.allowed"
        self.decoder = LineDecoder()
        self.tracker = ResultTracker(job["kind"])
        self.tracker.expected_videos = json.loads(job["snapshot"]).get("maxVideos", 1)
        self.tracker.expected_duration_minutes = json.loads(job["snapshot"]).get(
            "runDurationMinutes", 0
        )
        self.stdout = CappedLog(self.directory / "stdout.jsonl")
        self.stderr = CappedLog(self.directory / "stderr.log")
        self.console_stderr = console.StderrLines(
            lambda line: console.emit(line, job["serial"], job["id"], "ENGINE")
        )
        self.stopped = False
        self.guard = None
        self.finished = False
        self.exited = False
        self.exit_code = -1
        self.start_error = ""
        self.io_error = False
        self.output_overflow = False
        self.max_buffered = 2 * 1024 * 1024
        self.start_time = time.monotonic()
        self.p = QProcess(self)
        self.p.setProcessChannelMode(QProcess.SeparateChannels)
        self.p.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        env = environment(root, adb)
        env.insert("TAKTIK_CUSTOMER_DATA", str(self.root))
        env.insert("TAKTIK_DESKTOP_PID", str(os.getpid()))
        env.insert("TAKTIK_CUSTOMER_STOP", str(self.stop_path))
        env.insert("TAKTIK_CUSTOMER_GATE", str(self.gate_path))
        env.insert("TAKTIK_CUSTOMER_IME_STATE", str(self.directory / "keyboard.json"))
        artifact = self.root / "artifacts" / job["id"] / aid
        artifact.mkdir(parents=True, exist_ok=True)
        env.insert("TAKTIK_ARTIFACT_DIR", str(artifact))
        self.p.setProcessEnvironment(env)
        self.p.started.connect(self._started)
        # QProcess buffers pipes asynchronously. Parsing is polled at a bounded
        # cadence:50 simultaneous readyRead callbacks must not monopolize Qt.
        self.p.finished.connect(self._finished)
        self.p.errorOccurred.connect(self._error)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)
        config = self.root / "configs" / f"{aid}.json"
        temp = config.with_suffix(".tmp")
        temp.write_text(job["snapshot"], encoding="utf-8")
        temp.replace(config)
        (self.directory / "snapshot.json").write_text(job["snapshot"], encoding="utf-8")
        exe, args = command or engine_command()
        bridge = (
            "tiktok_publish_bridge" if job["kind"] == "publish" else "tiktok_bridge"
        )
        self.command = exe, [*args, bridge, str(config)]

    def start(self):
        console.emit(f"Bắt đầu {self.job['kind']}", self.job["serial"], self.job["id"])
        self.timer.start()
        self.p.start(*self.command)

    def _started(self):
        pid = int(self.p.processId())
        try:
            self.guard = JobGuard(pid)
            self.started.emit(pid, process_identity(pid) or "unknown")
            self.gate_path.touch()
        except Exception as exc:
            self.start_error = f"Không thể bảo vệ tiến trình Windows: {exc}"
            self.p.kill()

    def _error(self, error):
        if error == QProcess.FailedToStart:
            self.start_error = "Không khởi chạy được engine: " + self.p.errorString()
            self._finished(-1)

    def _stdout(self):
        if self.finished or self.output_overflow:
            return
        self.p.setReadChannel(QProcess.StandardOutput)
        if self._pipe_overflow():
            return
        data = bytes(self.p.read(16 * 1024))
        self._write_log(self.stdout, data)
        self._observe(self.decoder.feed(data))

    def _write_log(self, log, data):
        if not data or self.io_error:
            return
        try:
            log.write(data)
        except OSError:
            self.io_error = True
            self.stop()

    def _observe(self, events):
        for event in events:
            self.tracker.observe(event)
            console.event(event, self.job["serial"], self.job["id"])
        if events:
            self.events.emit(events)

    def _stderr(self):
        if self.finished or self.output_overflow:
            return
        self.p.setReadChannel(QProcess.StandardError)
        if self._pipe_overflow():
            return
        data = bytes(self.p.read(16 * 1024))
        self._write_log(self.stderr, data)
        self.console_stderr.feed(data)

    def _pipe_overflow(self):
        if self.p.bytesAvailable() <= self.max_buffered:
            return False
        self.output_overflow = True
        self.stop()
        self.p.closeReadChannel(QProcess.StandardOutput)
        self.p.closeReadChannel(QProcess.StandardError)
        if self.guard:
            self.guard.terminate()
        self.p.kill()
        return True

    def stop(self):
        if not self.stopped:
            console.emit(
                "Yêu cầu dừng tác vụ", self.job["serial"], self.job["id"], "WARN"
            )
            self.stopped = True
            self.stop_time = time.monotonic()
            try:
                self.stop_path.touch()
            except OSError:
                # A full/read-only disk must not make cancellation impossible.
                self.io_error = True
                if self.guard:
                    self.guard.terminate()
                self.p.kill()

    def _tick(self):
        if not self.finished:
            self._stdout()
            self._stderr()
        if self.exited and not self.finished:
            # Drain bounded chunks over event-loop turns before finalizing. The
            # final business result may be behind a large diagnostic burst.
            remaining = 0
            if not self.output_overflow:
                for channel in (QProcess.StandardOutput, QProcess.StandardError):
                    self.p.setReadChannel(channel)
                    remaining += self.p.bytesAvailable()
            if remaining:
                return
            self._observe(self.decoder.feed(b"", final=True))
            self.console_stderr.feed(b"", final=True)
            self.finished = True
            if self.guard:
                self.guard.terminate()
        if self.finished:
            if self.guard and not self.guard.empty():
                return
            self._complete()
            return
        # A ceiling includes connecting / blocking RPCs. Do not retry after it.
        runtime_limit = (
            self.tracker.expected_duration_minutes * 60 + 300
            if self.tracker.expected_duration_minutes
            else 6 * 3600
        )
        if time.monotonic() - self.start_time > runtime_limit:
            self.stop()
        if self.stopped and time.monotonic() - self.stop_time > 13:
            if self.guard:
                self.guard.terminate()
            self.p.kill()

    def _finished(self, code, *_):
        if self.exited:
            return
        self.exit_code = code
        self.exited = True
        if self.guard:
            self.guard.terminate()  # descendants cannot act while logs drain
        self._tick()

    def _complete(self):
        if not self.timer.isActive():
            return
        self.timer.stop()
        if self.guard:
            self.guard.close()
        for log in (self.stdout, self.stderr):
            try:
                log.close()
            except OSError:
                self.io_error = True
        state, message = self.tracker.finish(self.exit_code, stopped=self.stopped)
        if self.start_error:
            state, message = "failed", self.start_error
        elif self.output_overflow:
            state, message = (
                "needs_review",
                "Worker gửi dữ liệu vượt giới hạn; đã dừng để bảo vệ ứng dụng. Kiểm tra điện thoại trước khi tạo mới.",
            )
        elif self.io_error:
            state, message = (
                "needs_review",
                "Không ghi được nhật ký hoặc yêu cầu dừng. Worker đã dừng; kiểm tra dung lượng và quyền ghi trước khi chạy mới.",
            )
        result = {
            "state": state,
            "message": message,
            "exit_code": self.exit_code,
            "stats": self.tracker.stats,
            "stopped": self.stopped,
            "evidence": "engine_reported",
            "log_dir": str(self.directory),
        }
        console.emit(
            f"{state}: {message}",
            self.job["serial"],
            self.job["id"],
            "INFO" if state == "succeeded" else "ERROR",
        )
        self.done.emit(state, message, result)
