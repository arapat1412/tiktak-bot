import sys
from pathlib import Path

import pytest

from customer_desktop import paths


def freeze(monkeypatch, executable):
    executable = Path(executable)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    return executable


def test_env_override_wins_over_frozen_layout(monkeypatch, tmp_path):
    target = tmp_path / "Dữ liệu riêng"
    monkeypatch.setenv("TAKTIK_CUSTOMER_DATA", str(target))
    freeze(monkeypatch, tmp_path / "app" / "TikTokKorean.exe")
    assert paths.data_root() == target.resolve()


def test_source_default_is_repository_data_independent_of_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("TAKTIK_CUSTOMER_DATA", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    expected = Path(paths.__file__).resolve().parents[1] / "data"
    assert paths.data_root() == expected
    assert tmp_path not in paths.data_root().parents


def test_frozen_gui_uses_executable_parent_with_spaces_and_unicode(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("TAKTIK_CUSTOMER_DATA", raising=False)
    exe = freeze(monkeypatch, tmp_path / "Ứng dụng TikTok 한글" / "TikTokKorean.exe")
    assert paths.data_root() == exe.parent / "data"


def test_frozen_engine_uses_parent_of_its_engine_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("TAKTIK_CUSTOMER_DATA", raising=False)
    app = tmp_path / "Cài đặt"
    exe = freeze(monkeypatch, app / "engine" / "customer_engine.exe")
    assert paths.data_root() == app / "data"
    assert paths.data_root() != exe.parent / "data"


def test_explicit_root_is_created_with_full_layout(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "TAKTIK_CUSTOMER_DATA", str(tmp_path / "ignored for explicit root")
    )
    root = tmp_path / "dữ liệu thử"
    result = paths.prepare_paths(root)
    assert result == root.resolve()
    for name in paths.DIRECTORIES:
        assert (result / name).is_dir()


def test_prepare_paths_defaults_to_env_override(monkeypatch, tmp_path):
    target = tmp_path / "data từ env"
    monkeypatch.setenv("TAKTIK_CUSTOMER_DATA", str(target))
    assert paths.prepare_paths() == target.resolve()
    assert (target / "configs").is_dir()


def test_permission_failure_propagates_without_fallback(monkeypatch, tmp_path):
    def denied(self, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "mkdir", denied)
    with pytest.raises(PermissionError):
        paths.prepare_paths(tmp_path / "unwritable")
