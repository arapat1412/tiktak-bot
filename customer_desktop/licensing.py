"""Offline signed Windows-install licenses. No signing secret exists in the client."""

import base64
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from customer_desktop.license_public_key import PUBLIC_KEY_HEX
from customer_desktop.windows_secrets import dpapi

PRODUCT = "TIKTOK_KOREAN_DESKTOP"
MACHINE_PATTERN = r"TK-(?:[A-F0-9]{8}-){3}[A-F0-9]{8}"


class LicenseError(ValueError):
    pass


@dataclass(frozen=True)
class LicenseStatus:
    valid: bool
    message: str
    expires_at: int = None
    customer: str = ""


def format_expiry(epoch):
    return datetime.fromtimestamp(epoch, timezone(timedelta(hours=7))).strftime(
        "%d/%m/%Y %H:%M (UTC+7)"
    )


def machine_id():
    if os.name != "nt":
        raise LicenseError("Bản quyền cần mã máy Windows.")
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            identity = str(
                uuid.UUID(winreg.QueryValueEx(key, "MachineGuid")[0].strip("{}"))
            )
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise LicenseError(
            "Không đọc được mã máy Windows; kiểm tra quyền đọc hệ thống."
        ) from exc
    digest = (
        hashlib.sha256((PRODUCT + ":" + identity).encode("ascii"))
        .hexdigest()[:32]
        .upper()
    )
    return "TK-" + "-".join(digest[index : index + 8] for index in range(0, 32, 8))


def verify_token(token, machine, now=None, public_key=None):
    """Verify signature before using any supplied claims."""
    try:
        if not isinstance(token, str) or len(token) > 16384:
            raise ValueError()
        prefix, encoded, signature = "".join(token.split()).split(".")
        if prefix != "TK1" or not encoded or not signature:
            raise ValueError()

        def decode(value):
            return base64.b64decode(
                value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
            )

        raw = decode(encoded)
        Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(public_key or PUBLIC_KEY_HEX)
        ).verify(decode(signature), raw)
        payload = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("version") != 1
            or payload.get("product") != PRODUCT
        ):
            raise ValueError()
        for name in ("issued_at", "expires_at"):
            if type(payload.get(name)) is not int:
                raise ValueError()
        if not 0 < payload["expires_at"] - payload["issued_at"] <= 3650 * 86400:
            raise ValueError()
        if (
            not isinstance(payload.get("customer"), str)
            or len(payload["customer"]) > 200
        ):
            raise ValueError()
        if not isinstance(payload.get("license_id"), str) or not payload["license_id"]:
            raise ValueError()
    except (
        ValueError,
        TypeError,
        UnicodeError,
        InvalidSignature,
        OverflowError,
        RecursionError,
    ) as exc:
        raise LicenseError("Key không hợp lệ hoặc đã bị thay đổi.") from exc
    if payload.get("machine_id") != machine:
        raise LicenseError("Key này không dành cho máy tính hiện tại.")
    now = time.time() if now is None else now
    if payload["issued_at"] > now + 300:
        raise LicenseError(
            "Đồng hồ máy đang chậm hơn thời điểm cấp key. Hãy chỉnh đúng ngày giờ."
        )
    if now >= payload["expires_at"]:
        raise LicenseError("License đã hết hạn. Hãy liên hệ để gia hạn.")
    return payload


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                break
            except OSError as exc:
                if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 7:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def license_lock(root):
    """Serialize the clock read/check/write across GUI and engine processes."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / "license-clock.lock").open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + 5
            while True:
                stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise LicenseError(
                            "Đang bận cập nhật license. Hãy thử lại sau."
                        )
                    time.sleep(0.05)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class LicenseManager:
    def __init__(self, root, machine=None, public_key=None, clock=None, monotonic=None):
        self.root = Path(root)
        self.machine_id = machine or machine_id()
        self.public_key = public_key or PUBLIC_KEY_HEX
        self.clock = clock or time.time
        self.monotonic = monotonic or time.monotonic
        self.wall_start = self.clock()
        self.mono_start = self.monotonic()
        self.last_write = None
        self.high_water = 0
        self.key_path = self.root / "license.key"
        self.guard_path = self.root / "license-clock.bin"

    def _read_guard(self):
        if not self.guard_path.exists():
            return 0
        if self.guard_path.stat().st_size > 16384:
            raise LicenseError("Dữ liệu kiểm tra thời gian license không hợp lệ.")
        data = json.loads(
            dpapi(self.guard_path.read_bytes(), decrypt=True).decode("utf-8")
        )
        if (
            not isinstance(data, dict)
            or data.get("machine_id") != self.machine_id
            or type(data.get("last_seen")) is not int
            or data["last_seen"] < 0
        ):
            raise LicenseError("Dữ liệu kiểm tra thời gian license không hợp lệ.")
        return data["last_seen"]

    def _now(self):
        self.high_water = max(self.high_water, self._read_guard())
        wall = self.clock()
        elapsed_wall = self.wall_start + max(0, self.monotonic() - self.mono_start)
        if wall + 300 < max(self.high_water, elapsed_wall):
            raise LicenseError(
                "Phát hiện đồng hồ bị lùi. Hãy đồng bộ ngày giờ Windows để dùng license."
            )
        return max(wall, elapsed_wall, self.high_water)

    def _validate(self, token):
        with license_lock(self.root):
            return self._validate_locked(token)

    def _validate_locked(self, token):
        now = self._now()
        payload = verify_token(token, self.machine_id, now, self.public_key)
        # Shared high-water record detects basic rollback across application restarts.
        if self.last_write is None or self.monotonic() - self.last_write >= 60:
            high_water = max(int(now), self._read_guard())
            raw = json.dumps(
                dict(machine_id=self.machine_id, last_seen=high_water)
            ).encode("utf-8")
            atomic_write(self.guard_path, dpapi(raw))
            self.high_water = high_water
            self.last_write = self.monotonic()
        return LicenseStatus(
            True, "License đang hoạt động.", payload["expires_at"], payload["customer"]
        )

    def check(self):
        try:
            if not self.key_path.exists():
                return LicenseStatus(False, "Chưa kích hoạt license trên máy tính này.")
            if self.key_path.stat().st_size > 16384:
                raise LicenseError("File license không hợp lệ.")
            return self._validate(self.key_path.read_text(encoding="utf-8"))
        except PermissionError:
            return LicenseStatus(
                False,
                "Không ghi/đọc được dữ liệu license. Hãy đóng app, chuyển toàn bộ "
                "thư mục sang nơi có quyền ghi ngoài OneDrive (ví dụ D:\\TikTokKorean), "
                "giữ nguyên thư mục data rồi mở lại.",
            )
        except (LicenseError, OSError, ValueError, UnicodeError, RecursionError) as exc:
            return LicenseStatus(False, str(exc))

    def activate(self, token):
        status = self._validate(token)
        atomic_write(self.key_path, "".join(token.split()).encode("utf-8"))
        return status
