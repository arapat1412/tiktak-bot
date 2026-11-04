from types import SimpleNamespace
from unittest.mock import Mock
from PySide6.QtWidgets import QApplication, QDialog
from customer_desktop.licensing import LicenseStatus, LicenseError
from customer_desktop.license_dialog import LicenseDialog


def test_dialog_copies_machine_and_refuses_bad_key(app):
    fake = SimpleNamespace(
        machine_id="TK-fixture",
        check=lambda: LicenseStatus(False, "Chưa kích hoạt"),
        activate=Mock(side_effect=LicenseError("Sai mã máy")),
    )
    dialog = LicenseDialog(fake)
    dialog.copy_button.click()
    assert QApplication.clipboard().text() == "TK-fixture"
    dialog.key_input.setPlainText("invalid")
    dialog.activate_button.click()
    assert dialog.result() != QDialog.Accepted
    assert "Sai mã máy" in dialog.status.text()
    dialog.reject()


def test_dialog_accepts_renewal_without_device_actions(app):
    fake = SimpleNamespace(
        machine_id="TK-fixture",
        check=lambda: LicenseStatus(True, "Đang hoạt động", 2000000000),
        activate=Mock(return_value=LicenseStatus(True, "OK", 2100000000)),
    )
    dialog = LicenseDialog(fake)
    assert "UTC+7" in dialog.status.text()
    dialog.key_input.setPlainText("TK1.fixture.key")
    dialog.activate_button.click()
    assert dialog.result() == QDialog.Accepted
    fake.activate.assert_called_once_with("TK1.fixture.key")
