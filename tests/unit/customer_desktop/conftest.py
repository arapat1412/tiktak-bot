import pytest
from PySide6.QtWidgets import QApplication
from types import SimpleNamespace


@pytest.fixture(autouse=True)
def licensed_test_services(request, monkeypatch):
    # Explicit test fixture only. Production service and engine always verify keys.
    if request.node.path.name in ("test_licensing.py", "test_license_enforcement.py"):
        return
    from customer_desktop import services
    from customer_desktop.licensing import LicenseStatus

    fake = SimpleNamespace(
        check=lambda: LicenseStatus(True, "Fixture license", 4102444800, "Test"),
        machine_id="FIXTURE",
    )
    monkeypatch.setattr(services, "LicenseManager", lambda root: fake)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])
