"""Resolve installed TikTok package variants for standalone workflows."""

from __future__ import annotations

import subprocess
from typing import Callable

from taktik.core.clone.packages.package_map import get_original_package, preferred_tiktok_packages


DEFAULT_TIKTOK_PACKAGE = get_original_package("tiktok")
KNOWN_TIKTOK_PACKAGES = list(preferred_tiktok_packages())
RunFn = Callable[..., subprocess.CompletedProcess]


def resolve_tiktok_package(
    device_id: str,
    default: str = DEFAULT_TIKTOK_PACKAGE,
    *,
    run: RunFn = subprocess.run,
) -> str:
    """Return the first known TikTok package installed on the device."""
    from .session import selected_package

    selected = selected_package()
    if selected:
        result = run(
            ["adb", "-s", device_id, "shell", "pm", "list", "packages", selected],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode or f"package:{selected}" not in result.stdout.splitlines():
            raise RuntimeError(f"Selected TikTok package is not installed: {selected}")
        return selected
    for package_name in dict.fromkeys(KNOWN_TIKTOK_PACKAGES):
        try:
            result = run(
                ["adb", "-s", device_id, "shell", "pm", "list", "packages", package_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and f"package:{package_name}" in result.stdout.splitlines():
                return package_name
        except Exception:
            continue

    return default
