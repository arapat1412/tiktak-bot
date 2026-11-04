import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from customer_desktop.licensing import (
    LicenseManager,
    LicenseError,
    verify_token,
    PRODUCT,
    machine_id,
)
from customer_desktop.windows_secrets import dpapi

MACHINE = "TK-12345678-12345678-12345678-12345678"


def test_atomic_write_retries_windows_sharing_denial(tmp_path, monkeypatch):
    from customer_desktop import licensing

    path = tmp_path / "clock.bin"
    path.write_bytes(b"old")
    replace = os.replace
    calls = []

    def busy_then_replace(source, target):
        calls.append(target)
        if len(calls) < 3:
            error = PermissionError("busy")
            error.winerror = 5
            raise error
        replace(source, target)

    monkeypatch.setattr(licensing.os, "replace", busy_then_replace)
    monkeypatch.setattr(licensing.time, "sleep", lambda seconds: None)
    licensing.atomic_write(path, b"new")
    assert path.read_bytes() == b"new"
    assert len(calls) == 3
    assert list(tmp_path.iterdir()) == [path]


def test_atomic_write_permanent_denial_preserves_record(tmp_path, monkeypatch):
    from customer_desktop import licensing

    path = tmp_path / "clock.bin"
    path.write_bytes(b"old")
    calls = []

    def deny(*args):
        calls.append(1)
        error = PermissionError("denied")
        error.winerror = 5
        raise error

    monkeypatch.setattr(licensing.os, "replace", deny)
    monkeypatch.setattr(licensing.time, "sleep", lambda seconds: None)
    with pytest.raises(PermissionError):
        licensing.atomic_write(path, b"new")
    assert len(calls) == 8
    assert path.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [path]


def test_parallel_engines_validate_shared_clock_without_losing_high_water(licensed):
    key, clock, manager = licensed
    manager.activate(signed(key))
    script = """
import sys
from customer_desktop.licensing import LicenseManager
manager = LicenseManager(sys.argv[1], machine=sys.argv[2], public_key=sys.argv[3],
                         clock=lambda: float(sys.argv[4]), monotonic=lambda: 0)
for _ in range(4):
    manager.last_write = None
    status = manager.check()
    if not status.valid:
        raise RuntimeError(status.message)
"""
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(manager.root),
                MACHINE,
                manager.public_key,
                str(clock.wall + offset),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for offset in range(12)
    ]
    results = [(process, process.communicate(timeout=30)) for process in processes]
    for process, (stdout, stderr) in results:
        assert process.returncode == 0, (stdout, stderr)
    assert manager._read_guard() == int(clock.wall) + 11


def signed(key, machine=MACHINE, now=2000000000, days=30, **updates):
    claims = dict(
        version=1,
        product=PRODUCT,
        machine_id=machine,
        issued_at=now,
        expires_at=now + days * 86400,
        license_id="fixture",
        customer="Khách 한글",
    )
    claims.update(updates)
    raw = json.dumps(claims, ensure_ascii=False).encode()
    encode = lambda data: base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    return "TK1." + encode(raw) + "." + encode(key.sign(raw))


@pytest.fixture
def licensed(tmp_path):
    key = Ed25519PrivateKey.generate()
    clock = SimpleNamespace(wall=2000000000.0, mono=100.0)
    manager = LicenseManager(
        tmp_path,
        machine=MACHINE,
        public_key=key.public_key().public_bytes_raw().hex(),
        clock=lambda: clock.wall,
        monotonic=lambda: clock.mono,
    )
    return key, clock, manager


def test_machine_id_is_stable_and_app_scoped():
    first = machine_id()
    assert first == machine_id()
    assert first.startswith("TK-") and len(first) == 38


def test_valid_key_persists_and_survives_restart(licensed):
    key, clock, manager = licensed
    assert not manager.check().valid
    token = signed(key)
    result = manager.activate(token)
    assert result.valid and result.customer == "Khách 한글"
    assert result.expires_at == int(clock.wall) + 30 * 86400
    assert manager.check().valid
    restarted = LicenseManager(
        manager.root,
        machine=MACHINE,
        public_key=manager.public_key,
        clock=lambda: clock.wall,
        monotonic=lambda: clock.mono,
    )
    assert restarted.check().valid
    assert b"last_seen" not in manager.guard_path.read_bytes()


@pytest.mark.parametrize("change", ["signature", "machine", "days", "public"])
def test_tampering_wrong_machine_and_other_issuer_refused(licensed, change):
    key, clock, manager = licensed
    token = signed(key)
    if change == "signature":
        prefix, body, signature = token.split(".")
        token = (
            prefix
            + "."
            + body
            + "."
            + ("A" if signature[0] != "A" else "B")
            + signature[1:]
        )
    elif change == "days":
        prefix, body, signature = token.split(".")
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        payload["expires_at"] += 86400
        body = (
            base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        )
        token = prefix + "." + body + "." + signature
    elif change == "machine":
        token = signed(key, machine="TK-AAAAAAAA-AAAAAAAA-AAAAAAAA-AAAAAAAA")
    else:
        token = signed(Ed25519PrivateKey.generate())
    with pytest.raises(LicenseError):
        manager.activate(token)
    assert not manager.key_path.exists()


def test_exact_expiry_and_clock_rollback_refused(licensed):
    key, clock, manager = licensed
    manager.activate(signed(key, days=1))
    clock.wall += 86400
    clock.mono += 86400
    assert not manager.check().valid
    assert "hết hạn" in manager.check().message
    clock.wall = 1999999400
    restarted = LicenseManager(
        manager.root,
        machine=MACHINE,
        public_key=manager.public_key,
        clock=lambda: clock.wall,
        monotonic=lambda: 0,
    )
    assert not restarted.check().valid
    assert "đồng hồ" in restarted.check().message
    with pytest.raises(LicenseError):
        restarted.activate(signed(key))


def test_frozen_wall_clock_cannot_extend_process_validity(licensed):
    key, clock, manager = licensed
    manager.activate(signed(key, days=1))
    clock.mono += 86401
    assert not manager.check().valid


def test_corrupt_guard_fails_closed_and_preserves_key(licensed):
    key, clock, manager = licensed
    token = signed(key)
    manager.activate(token)
    manager.guard_path.write_bytes(b"corrupt")
    assert not manager.check().valid
    assert manager.key_path.read_text() == token


def test_persistent_write_denial_still_blocks_license_with_guidance(
    licensed, monkeypatch
):
    key, clock, manager = licensed
    token = signed(key)
    manager.activate(token)
    manager.last_write = None

    def deny(*args):
        raise PermissionError("denied")

    monkeypatch.setattr("customer_desktop.licensing.atomic_write", deny)
    status = manager.check()
    assert not status.valid
    assert "OneDrive" in status.message and "data" in status.message
    assert manager.key_path.read_text() == token


@pytest.mark.parametrize("token", ["", "TK1.a.a", "random", "x" * 17000, "TK1.###.###"])
def test_malformed_key_refused(licensed, token):
    key, clock, manager = licensed
    with pytest.raises(LicenseError):
        manager.activate(token)


def test_future_key_and_invalid_signed_claims_refused(licensed):
    key, clock, manager = licensed
    with pytest.raises(LicenseError, match="đồng hồ|Đồng hồ"):
        manager.activate(signed(key, now=int(clock.wall) + 601))
    for updates in (
        dict(version=2),
        dict(product="OTHER"),
        dict(expires_at="3000000000"),
        dict(customer=[]),
    ):
        with pytest.raises(LicenseError):
            manager.activate(signed(key, **updates))


def test_admin_issuer_is_standalone_and_key_is_never_overwritten(tmp_path):
    source = Path(__file__).resolve().parents[3] / "admin" / "cap_license.py"
    spec = importlib.util.spec_from_file_location("fixture_issuer", source)
    issuer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(issuer)
    path = tmp_path / "issuer.dpapi"
    public = issuer.initialize(path)
    before = path.read_bytes()
    assert issuer.initialize(path) == public
    assert path.read_bytes() == before
    token, claims = issuer.issue(MACHINE, 7, "Khách 한글", path, now=2000000000)
    assert (
        verify_token(token, MACHINE, 2000000000, public)["expires_at"]
        == 2000000000 + 7 * 86400
    )
    assert b"PRIVATE KEY" not in before and len(dpapi(before, decrypt=True)) == 32
    with pytest.raises(ValueError):
        issuer.issue("bad", 7, path=path)
    with pytest.raises(ValueError):
        issuer.issue(MACHINE, 0, path=path)
