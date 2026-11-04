"""TikTok publish bridge runtime class.

The publication is `run_tiktok_publish` (core), the launcher the Agent handler
`tiktok.standalone.upload_post` (and so the CLI) calls too: read the request, patch the selectors
of a cloned TikTok, upload the video or write the text post. This bridge opens its own connection
and injects what is specific to the desktop: the stdout IPC and a screenshot plus a UI dump per
phase under `debug_ui`.
"""

from __future__ import annotations

import signal
import os
from datetime import datetime, timezone
from pathlib import Path

from taktik.core.shared.device.connection import ConnectionService
from bridges.common.signal_handler import setup_signal_handlers
from bridges.tiktok.common.ipc import _ipc, send_error, send_log, send_status


class TikTokPublishBridge:
    """Bridge for TikTok post upload."""

    def __init__(self, config: dict):
        self.config = config
        self.device_id = config.get("deviceId")
        self._connection = None
        self._artifact_dir = None

        setup_signal_handlers(ipc=_ipc)
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

    def _shutdown(self, signum, frame):
        send_status("stopping", "Received shutdown signal")

    def _capture_phase(self, device, phase: str) -> None:
        """Save a before/after screenshot + UI XML dump so a publish run can be reviewed
        from disk, like the Cartography Lab action-test artifacts. Best-effort, never fatal."""
        # Cancellation must not be swallowed as a diagnostic capture failure.
        # KeyboardInterrupt is handled by the shared bridge entrypoint.
        from taktik.core.shared.diagnostics import run_halt
        if run_halt.arret_demande():
            raise KeyboardInterrupt("Publication stopped before phase " + phase)
        if os.environ.get("TAKTIK_CUSTOMER_EVENTS") == "1":
            # Android may expose the TikTok tree BEHIND a heads-up notification.
            # Tapping those bounds could hit Reply/Like in the foreign overlay.
            try:
                dump = device.dump_hierarchy()
                if not dump:
                    raise ValueError("empty UI hierarchy")
            except Exception:
                send_error("The TikTok screen cannot be read safely; publication stopped")
                raise KeyboardInterrupt("Unreadable TikTok screen") from None
            if ('com.android.systemui:id/heads_up' in dump or
                    ('package="com.android.systemui"' in dump and 'resource-id="android:id/title"' in dump)):
                send_error("A system notification obscures TikTok; dismiss it manually before starting a new run")
                raise KeyboardInterrupt("TikTok is obscured by a system notification")
        try:
            if self._artifact_dir is None:
                bot_root = Path(__file__).resolve().parents[3]
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                safe = "".join(c for c in (self.device_id or "device") if c.isalnum() or c in "._-")
                override = os.environ.get("TAKTIK_ARTIFACT_DIR")
                self._artifact_dir = (Path(override) if override else
                                      bot_root / "debug_ui" / "cartography" / safe / "tiktok" / "publish-runs" / stamp)
                self._artifact_dir.mkdir(parents=True, exist_ok=True)
            png = self._artifact_dir / f"{phase}.png"
            xml = self._artifact_dir / f"{phase}.xml"
            # `device` here is the raw uiautomator2 Device (not the DeviceFacade), so use its
            # native methods: screenshot(filename) saves a PNG, dump_hierarchy() returns the XML.
            device.screenshot(str(png))
            dump = device.dump_hierarchy()
            if dump:
                xml.write_text(dump, encoding="utf-8")
            send_log("info", f"[artifact] {phase}: {png}")
        except Exception as e:
            send_log("warning", f"Artifact capture ({phase}) failed: {e}")

    def run(self) -> int:
        from taktik.core.social_media.tiktok.services.runtime.session import package_session

        with package_session(self.config.get("packageName")):
            return self._run()

    def _run(self) -> int:
        from taktik.core.social_media.tiktok.workflows.publish.agent_handler import run_tiktok_publish
        from taktik.core.social_media.tiktok.workflows.publish.payload import (
            PublishRequestError,
            publish_request_from_payload,
        )

        if not self.device_id:
            send_error("deviceId is required")
            return 1
        try:
            # Read before connecting: nothing to publish means the phone is not touched.
            publish_request_from_payload(self.config)
        except PublishRequestError as e:
            send_error(str(e))
            return 1

        if self.config.get("packageName"):
            from taktik.core.social_media.tiktok.services.runtime.package_resolver import resolve_tiktok_package
            try:
                resolve_tiktok_package(self.device_id)
            except Exception as exc:
                send_error(str(exc))
                return 1

        send_status("connecting", f"Connecting to device {self.device_id}...")
        self._connection = ConnectionService(self.device_id)
        if not self._connection.connect():
            send_error(f"Failed to connect to device {self.device_id}")
            return 1

        device = self._connection.device
        if not device:
            send_error("Device object unavailable after connection")
            return 1

        if os.environ.get("TAKTIK_CUSTOMER_EVENTS") == "1" and self.config.get("botUsername"):
            # The customer has also confirmed the account in the GUI. When the
            # engine can read it, a positive mismatch must block the publication.
            from taktik.core.social_media.tiktok.workflows.common.startup import patch_clone_selectors
            from taktik.core.social_media.tiktok.services.runtime.package_resolver import resolve_tiktok_package
            from taktik.core.social_media.tiktok.services.runtime.app_control import TIKTOK_SPLASH_ACTIVITY
            from taktik.core.social_media.tiktok.services.profile.profile_actions import ProfileActions
            package_name = self.config.get("packageName") or resolve_tiktok_package(self.device_id)
            patch_clone_selectors(package_name, _ipc)
            device.app_start(package_name, TIKTOK_SPLASH_ACTIVITY)
            self._capture_phase(device, "00_account_check")
            send_status("verifying_account", "Checking the current TikTok account")
            try:
                profile = ProfileActions(device).fetch_own_profile()
                actual = getattr(profile, "username", None)
            except Exception:
                actual = None
            expected = str(self.config["botUsername"]).strip().lstrip("@").casefold()
            if actual and str(actual).strip().lstrip("@").casefold() != expected:
                send_error("The current TikTok account differs from the expected account; nothing published")
                return 1
            _ipc.send("account_check", verified=bool(actual), username=actual)
            if not actual:
                send_log("warning", "Account unreadable: relying on the customer's explicit Xiaowei account check")

        result = run_tiktok_publish(
            self.config,
            device=device,
            device_id=self.device_id,
            notifier=_ipc,
            step_hook=lambda phase: self._capture_phase(device, phase),
        )
        return 0 if result.get("success") else 1


__all__ = ["TikTokPublishBridge"]
