import subprocess
from types import SimpleNamespace

import pytest

from taktik.core.social_media.tiktok.manager import TikTokManager
from taktik.core.social_media.tiktok.services.runtime.package_resolver import (
    resolve_tiktok_package,
)
from taktik.core.social_media.tiktok.services.runtime.session import (
    package_session,
    selected_package,
)
from taktik.core.shared.device.app_inspection import is_platform_foreground

FULL = "com.ss.android.ugc.trill"
LITE = "com.ss.android.ugc.tiktok.lite"


def test_resolver_never_substitutes_lite_for_missing_explicit_full_package():
    calls = []

    def run(args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(
            args, 0, f"package:{FULL}.clone\npackage:{LITE}\n", ""
        )

    with package_session(FULL), pytest.raises(RuntimeError, match="not installed"):
        resolve_tiktok_package("phone", run=run)
    assert len(calls) == 1 and calls[0][-1] == FULL
    assert selected_package() is None


def test_manager_pins_explicit_package_for_restart_launch_and_stop(monkeypatch):
    with package_session(FULL):
        manager = TikTokManager("phone")
    calls = []
    manager.device_manager = SimpleNamespace(
        device_id="phone",
        is_app_installed=lambda p: p in (LITE, FULL),
        stop_app=lambda p: calls.append(("stop", p)),
        launch_app=lambda p, a: calls.append(("launch", p)) or True,
        device=SimpleNamespace(
            app_start=lambda p, a, **kw: calls.append(("restart", p))
        ),
    )
    monkeypatch.setattr("time.sleep", lambda _: None)
    assert manager.launch() and manager.restart() and manager.stop()
    assert calls and all(p == FULL for _, p in calls)
    manager.device_manager.is_app_installed = lambda p: False
    assert (
        manager.package_name == FULL
    )  # cached identity cannot drift during the session


def test_manager_missing_selection_refuses_instead_of_picking_installed_lite():
    manager = TikTokManager("phone", package_name=FULL)
    manager.device_manager.is_app_installed = lambda p: p == LITE
    with pytest.raises(RuntimeError, match="not installed"):
        manager.launch()


def test_foreground_guard_requires_selected_variant_and_context_restores():
    device = SimpleNamespace(app_current=lambda: {"package": LITE})
    assert is_platform_foreground(device, "tiktok")
    with package_session(FULL):
        assert not is_platform_foreground(device, "tiktok")
        with package_session(LITE):
            assert is_platform_foreground(device, "tiktok")
        assert selected_package() == FULL
    assert selected_package() is None


def test_connection_reads_selected_build_instead_of_lite_build(monkeypatch):
    from taktik.core.compat.selectors import setup

    reads, patches = [], []

    def version(serial, package, platform):
        reads.append((serial, package, platform))
        return "47.6.3" if platform == "tiktok" else None

    monkeypatch.setattr(
        "taktik.core.shared.device.app_inspection.get_installed_app_version", version
    )
    monkeypatch.setattr(
        setup,
        "apply_version_overrides",
        lambda app, v, **kw: patches.append((app, v, kw)) or 1,
    )
    with package_session(FULL):
        assert setup.apply_overrides_for_device("phone")["tiktok"] == 1
    assert [p for _, p, app in reads if app == "tiktok"] == [FULL]
    assert patches == [("tiktok", "47.6.3", {"package_name": FULL})]


def test_dispatcher_binds_and_cleans_up_only_requested_package(monkeypatch):
    from bridges.tiktok.automation import dispatcher
    from taktik.core.social_media.tiktok.services.runtime import app_control

    calls = []
    monkeypatch.setattr(dispatcher, "reset_network_if_enabled", lambda *a: True)

    def dispatch(config):
        assert selected_package() == FULL
        return False, "for_you"

    monkeypatch.setattr(dispatcher, "dispatch_tiktok_workflow", dispatch)
    monkeypatch.setattr(
        app_control, "force_stop_app_package", lambda d, p: calls.append((d, p))
    )
    assert (
        dispatcher.TikTokDispatcherBridge(
            {"deviceId": "phone", "packageName": FULL}
        ).run()
        == 1
    )
    assert calls == [("phone", FULL)]
    assert selected_package() is None
