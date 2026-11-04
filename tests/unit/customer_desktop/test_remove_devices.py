from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from customer_desktop.paths import prepare_paths
from customer_desktop.services import DesktopService
from customer_desktop.storage import ACTIVE, Store
from customer_desktop.ui import MainWindow


def populate(store):
    store.discover([dict(serial=s, model="Máy " + s, connection="offline") for s in ("a", "b")])
    store.save_device("b", "Máy cũ", "Nhóm cũ", "tai_khoan_cu", True)


def make_store(tmp_path):
    store = Store(prepare_paths(tmp_path))
    populate(store)
    return store


def historical_job(store):
    jid = store.enqueue([dict(serial="b",kind="browse",payload={"maxVideos":1})],"old")[0]
    aid = store.attempt(store.job(jid),store.root / "logs/old","attempt")
    store.events(aid,[{"type":"status","status":"completed"}],0)
    store.end_attempt(aid,{"state":"succeeded"})
    store.state(jid,"succeeded")
    return jid


def test_removal_persists_without_deleting_history_and_reconnect_restores_labels(tmp_path):
    store = make_store(tmp_path)
    historical_job(store)
    before = {table:store.rows(f"SELECT * FROM {table}")
              for table in ("devices","jobs","job_attempts","job_events")}
    assert store.remove_devices(["b","b"]) == 1
    assert [d["serial"] for d in store.devices()] == ["a"]
    assert all(store.rows(f"SELECT * FROM {table}") == rows for table,rows in before.items())
    assert not store.db.execute("PRAGMA foreign_key_check").fetchall()
    store.close()
    store = Store(tmp_path)
    try:
        for inventory in ([],[dict(serial="b",connection="offline")]):
            store.discover(inventory)
            assert all(d["serial"] != "b" for d in store.devices())
        store.discover([dict(serial="b",connection="online",model="New metadata")])
        restored = next(d for d in store.devices() if d["serial"] == "b")
        assert (restored["name"],restored["group_name"],restored["account"],restored["hold"]) == (
            "Máy cũ","Nhóm cũ","tai_khoan_cu",1
        )
        assert store.rows("SELECT * FROM jobs") == before["jobs"]
        assert store.setting("forgotten_devices") == []
    finally:
        store.close()


def test_unauthorized_reconnect_is_visible_for_authorization(tmp_path):
    store = make_store(tmp_path)
    try:
        store.remove_devices(["b"])
        store.discover([dict(serial="b",connection="unauthorized")])
        assert next(d for d in store.devices() if d["serial"] == "b")["connection"] == "unauthorized"
    finally:
        store.close()


@pytest.mark.parametrize("state", ["queued","scheduled","overdue",*ACTIVE])
def test_pending_or_active_job_blocks_removal(tmp_path,state):
    store = make_store(tmp_path)
    try:
        jid = store.enqueue([dict(serial="b",kind="browse",payload={})],"pending")[0]
        store.state(jid,state)
        with pytest.raises(ValueError,match="tác vụ hoặc lịch"):
            store.remove_devices(["b"])
        assert len(store.devices()) == 2 and not store.setting("forgotten_devices",[])
    finally:
        store.close()


def test_unfinished_attempt_blocks_even_if_job_is_terminal(tmp_path):
    store = make_store(tmp_path)
    try:
        jid = store.enqueue([dict(serial="b",kind="browse",payload={})],"pending")[0]
        store.attempt(store.job(jid),store.root / "logs/unfinished","unfinished")
        store.state(jid,"needs_review")
        with pytest.raises(ValueError,match="chưa được thu dọn"):
            store.remove_devices(["b"])
    finally:
        store.close()


@pytest.mark.parametrize("bad", ["online","unauthorized","missing"])
def test_mixed_batch_validation_removes_nothing(tmp_path,bad):
    store = make_store(tmp_path)
    try:
        serial = "absent" if bad == "missing" else "a"
        if bad != "missing":
            store.discover([dict(serial="a",connection=bad)])
        with pytest.raises(ValueError):
            store.remove_devices(["b",serial])
        assert len(store.devices()) == 2 and not store.setting("forgotten_devices",[])
    finally:
        store.close()


def test_empty_and_already_removed_selection_rejected(tmp_path):
    store = make_store(tmp_path)
    try:
        with pytest.raises(ValueError):
            store.remove_devices([])
        store.remove_devices(["b"])
        with pytest.raises(ValueError):
            store.remove_devices(["b"])
    finally:
        store.close()


def make_service(tmp_path):
    service = DesktopService(prepare_paths(tmp_path),prepare=False)
    service.timer.stop()
    service.refresh_devices = lambda: None
    service.store.set_setting("onboarded",True)
    populate(service.store)
    return service


@pytest.mark.parametrize("busy",["closing","submitting","keyboard","runner","recovery","validating"])
def test_service_reservations_block_offline_removal(app,tmp_path,busy):
    service = make_service(tmp_path)
    try:
        if busy in ("closing","submitting"):
            setattr(service,busy,True)
        elif busy == "keyboard":
            service.keyboard_installing.add("b")
        elif busy == "runner":
            service.runners["job"] = SimpleNamespace(job={"serial":"b"})
        elif busy == "recovery":
            service.recovery.append({"serial":"b"})
        else:
            jid = historical_job(service.store)
            service.validating.add(jid)
        with pytest.raises(ValueError):
            service.remove_devices(["b"])
        assert len(service.store.devices()) == 2
    finally:
        service.runners.clear()
        service.store.close()


def test_service_clears_route_and_notifies_only_after_success(app,tmp_path):
    service = make_service(tmp_path)
    seen = []
    service.changed.connect(lambda:seen.append(True))
    service.device_ports = {"a":5037,"b":5038}
    try:
        assert service.remove_devices(["b"]) == 1
        assert seen == [True] and service.device_ports == {"a":5037}
        with pytest.raises(ValueError):
            service.remove_devices(["b"])
        assert seen == [True]
    finally:
        service.store.close()


def make_window(service):
    window = MainWindow(service)
    window.refresh_timer.stop()
    row = next(r for r in range(window.device_table.rowCount())
               if window.device_table.item(r,0).data(Qt.UserRole) == "b")
    window.device_table.item(row,0).setCheckState(Qt.Checked)
    return window


def cleanup(window,service):
    window.allow_close = True
    window.close()
    service.store.close()


def test_ui_enablement_tracks_connection_and_pending_tasks(app,tmp_path):
    service = make_service(tmp_path)
    window = make_window(service)
    try:
        assert window.remove_device_button.isEnabled()
        service.store.discover([dict(serial="b",connection="online")])
        window.update_selection()
        assert not window.remove_device_button.isEnabled()
        service.store.discover([])
        jid = service.store.enqueue([dict(serial="b",kind="browse",payload={})],"pending")[0]
        window.update_selection()
        assert not window.remove_device_button.isEnabled()
        service.store.state(jid,"cancelled")
        window.update_selection()
        assert window.remove_device_button.isEnabled()
    finally:
        cleanup(window,service)


@pytest.mark.parametrize("confirmed",[False,True])
def test_ui_confirmation_defaults_to_no_and_preserves_history(app,tmp_path,monkeypatch,confirmed):
    service = make_service(tmp_path)
    jid = historical_job(service.store)
    window = make_window(service)
    questions = []
    def ask(*args):
        questions.append(args)
        return QMessageBox.Yes if confirmed else QMessageBox.No
    monkeypatch.setattr(QMessageBox,"question",ask)
    try:
        window.remove_devices()
        assert questions[0][-1] == QMessageBox.No
        assert "Máy cũ (b)" in questions[0][2] and "Lịch sử" in questions[0][2]
        assert service.store.job(jid)["state"] == "succeeded"
        assert len(service.store.devices()) == (1 if confirmed else 2)
        assert window.device_table.rowCount() == (1 if confirmed else 2)
    finally:
        cleanup(window,service)


def test_ui_rechecks_after_confirmation_if_phone_reconnects(app,tmp_path,monkeypatch):
    service = make_service(tmp_path)
    window = make_window(service)
    errors = []
    def ask(*args):
        service.store.discover([dict(serial="b",connection="online")])
        return QMessageBox.Yes
    monkeypatch.setattr(QMessageBox,"question",ask)
    monkeypatch.setattr("customer_desktop.ui.error",lambda parent,message:errors.append(message))
    try:
        window.remove_devices()
        assert errors and len(service.store.devices()) == 2
    finally:
        cleanup(window,service)
