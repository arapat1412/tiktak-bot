"""Customer data lives in data/ beside the app unless explicitly overridden."""

import os
import sys
from pathlib import Path

DIRECTORIES = (
    "engine",
    "configs",
    "logs",
    "artifacts",
    "media",
    "backups",
    "exports",
)
ENGINE_EXECUTABLE = "customer_engine.exe"


def data_root():
    override = os.environ.get("TAKTIK_CUSTOMER_DATA")
    if override:
        return Path(override).resolve()
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        # The bundled engine lives in <app>/engine/; its data is the app's own.
        if executable.name.lower() == ENGINE_EXECUTABLE:
            return executable.parent.parent / "data"
        return executable.parent / "data"
    return Path(__file__).resolve().parents[1] / "data"


def prepare_paths(root=None):
    root = Path(root or data_root()).resolve()
    for name in DIRECTORIES:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root
