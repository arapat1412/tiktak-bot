import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from customer_desktop.licensing import LicenseManager, LicenseStatus, LicenseError
from customer_desktop.paths import prepare_paths
from customer_desktop.services import DesktopService
from customer_desktop.domain import natural_browse_options, build_browse


def test_unlicensed_service_cannot_submit_or_launch_queued_job(app, tmp_path):
    service = DesktopService(prepare_paths(tmp_path), prepare=False)
    service.timer.stop()
    service.background = Mock()
    service.store.discover(
        [dict(serial="fake", connection="online", package="fixture")]
    )
    spec = dict(
        serial="fake",
        kind="browse",
        payload=build_browse("fake", natural_browse_options()),
    )
    with pytest.raises(LicenseError):
        service.submit([spec])
    job_id = service.store.enqueue([spec], "fixture")[0]
    service.store.state(job_id, "validating", "Fixture validation")
    service._launch(service.store.job(job_id))
    assert not service.runners
    assert service.store.job(job_id)["state"] == "queued"
    assert "kích hoạt" in service.admission_reason
    service.store.close()


def test_expiry_stops_existing_work_and_preserves_queue(app, tmp_path):
    state = [LicenseStatus(True, "OK", 4102444800)]
    fake = SimpleNamespace(machine_id="fixture", check=lambda: state[0])
    service = DesktopService(
        prepare_paths(tmp_path), prepare=False, license_manager=fake
    )
    service.timer.stop()
    service.background = Mock()
    service.store.discover(
        [dict(serial="fake", connection="online", package="fixture")]
    )
    spec = dict(
        serial="fake",
        kind="browse",
        payload=build_browse("fake", natural_browse_options()),
    )
    active, queued = service.store.enqueue([spec, spec], "fixture")
    runner = SimpleNamespace(job=dict(serial="fake"), stop=Mock())
    service.runners[active] = runner
    state[0] = LicenseStatus(False, "License đã hết hạn.")
    service.tick()
    runner.stop.assert_called_once()
    assert service.store.job(active)["state"] == "stopping"
    assert service.store.job(queued)["state"] == "queued"
    service.runners.clear()
    service.store.close()


def test_real_engine_refuses_unlicensed_before_gate_or_keyboard(tmp_path):
    env = {
        **os.environ,
        "TAKTIK_CUSTOMER_DATA": str(tmp_path),
        "PYTHONIOENCODING": "utf-8",
        "TAKTIK_CUSTOMER_GATE": str(tmp_path / "never-unlock"),
        "TAKTIK_CUSTOMER_IME_STATE": str(tmp_path / "keyboard.json"),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "customer_desktop.engine_worker",
            "tiktok_bridge",
            str(tmp_path / "missing.json"),
        ],
        env=env,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 3
    event = json.loads(result.stdout.decode("utf-8"))
    assert event["error_code"] == "CUSTOMER_LICENSE_INVALID"
    assert not (tmp_path / "keyboard.json").exists()
    assert not (tmp_path / "engine").exists()
