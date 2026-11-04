import json
from unittest.mock import Mock

import pytest

from customer_desktop.app_choice import TikTokAppChoice
from customer_desktop.domain import build_browse
from customer_desktop.paths import prepare_paths
from customer_desktop.services import DesktopService
from customer_desktop.ui import BrowseDialog, PublishDialog

LITE = "com.ss.android.ugc.tiktok.lite"
TRILL = "com.ss.android.ugc.trill"
FULL = "com.zhiliaoapp.musically"


def service_at(tmp_path):
    service = DesktopService(prepare_paths(tmp_path), prepare=False)
    service.timer.stop()
    service.store.discover(
        [
            dict(
                serial=s,
                model=s,
                name=s,
                connection="online",
                package=LITE,
                applications=[
                    dict(package=LITE, version="47.5.3"),
                    dict(package=full, version="47.6.3"),
                ],
            )
            for s, full in (("a", TRILL), ("b", FULL))
        ]
    )
    return service


@pytest.mark.parametrize("dialog_class", [BrowseDialog, PublishDialog])
@pytest.mark.parametrize(
    "mode,expected", [("lite", [LITE, LITE]), ("standard", [TRILL, FULL])]
)
def test_task_forms_resolve_actual_package_per_phone_without_changing_rows_or_device_settings(
    app, tmp_path, dialog_class, mode, expected
):
    s = service_at(tmp_path)
    s.store.select_tiktok_app("a", TRILL)
    before = s.store.devices()
    d = dialog_class(s, before, None)
    if dialog_class is PublishDialog:
        d.files = ["fixture.mp4"]
        d.mode.setCurrentIndex(1)
        d.rebuild()
        d.rows.item(0, 2).setText("Nội dung riêng 한글")
        d.rows.item(0, 3).setText("#one #two")
    d.app_choice.mode.setCurrentIndex(d.app_choice.mode.findData(mode))
    d.send = Mock()
    d.submit()
    specs = d.send.call_args.args[0]
    assert [x["payload"]["packageName"] for x in specs] == expected
    if dialog_class is PublishDialog:
        assert specs[0]["payload"]["caption"] == "Nội dung riêng 한글"
        assert specs[0]["payload"]["hashtags"] == ["#one", "#two"]
    else:
        assert specs[0]["payload"] == build_browse("a", d.values()) | {
            "packageName": expected[0]
        }
    assert s.store.devices() == before
    d.reject()
    s.store.close()


def test_mixed_batch_can_choose_each_phone_in_the_task_form(app, tmp_path):
    s = service_at(tmp_path)
    choice = TikTokAppChoice(s.store.devices())
    choice.mode.setCurrentIndex(choice.mode.findData(""))
    choice.phones["a"].setCurrentIndex(choice.phones["a"].findData(TRILL))
    choice.phones["b"].setCurrentIndex(choice.phones["b"].findData(LITE))
    assert choice.packages() == {"a": TRILL, "b": LITE}
    s.store.close()


def test_missing_app_blocks_form_and_never_substitutes_other_variant(app, tmp_path):
    s = service_at(tmp_path)
    devices = s.store.devices()
    devices[1]["applications"] = [dict(package=LITE, version="47.5.3")]
    d = BrowseDialog(s, devices, None)
    d.app_choice.mode.setCurrentIndex(d.app_choice.mode.findData("standard"))
    assert not d.create.isEnabled()
    assert "b:" in d.preview.text()
    with pytest.raises(ValueError):
        d.app_choice.packages()
    d.reject()
    s.store.close()


def test_browse_recipe_saves_app_choice_only_on_save_and_restores_it(app, tmp_path):
    s = service_at(tmp_path)
    d = BrowseDialog(s, s.store.devices(), None)
    d.app_choice.mode.setCurrentIndex(d.app_choice.mode.findData("standard"))
    assert s.store.setting(d.RECIPE_KEY) is None
    d.save_recipe()
    assert s.store.setting(d.RECIPE_KEY)["tiktokApp"]["mode"] == "standard"
    d.reject()
    reopened = BrowseDialog(s, s.store.devices(), None)
    assert reopened.app_choice.packages() == {"a": TRILL, "b": FULL}
    reopened.reset_recipe()
    assert reopened.app_choice.mode.currentData() == "lite"
    reopened.reject()
    s.store.close()


def test_explicit_form_package_wins_over_old_preference_and_snapshot_is_immutable(
    app, tmp_path
):
    s = service_at(tmp_path)
    s.store.select_tiktok_app("a", TRILL)
    s.background = lambda fn, done, failed=None: done(fn())
    s.submit([dict(serial="a", kind="browse", payload=dict(packageName=LITE))])
    job = s.store.jobs()[0]
    assert json.loads(job["snapshot"])["packageName"] == LITE
    s.store.select_tiktok_app("a", LITE)
    assert s.store.jobs()[0]["snapshot"] == job["snapshot"]
    s.store.close()


def test_publish_only_validates_phones_receiving_rows(app, tmp_path):
    s = service_at(tmp_path)
    devices = s.store.devices()
    devices[1]["applications"] = [dict(package=LITE, version="47.5.3")]
    d = PublishDialog(s, devices, None)
    d.files = ["fixture.mp4"]
    d.rebuild()  # one file allocated only to a
    d.app_choice.mode.setCurrentIndex(d.app_choice.mode.findData("standard"))
    assert d.create.isEnabled()
    d.send = Mock()
    d.submit()
    assert d.send.call_args.args[0][0]["payload"]["packageName"] == TRILL
    d.mode.setCurrentIndex(1)  # both phones now receive a row
    assert not d.create.isEnabled()
    d.reject()
    s.store.close()
