import subprocess
import sys

from testing.paths import REPOSITORY_ROOT


def test_remote_backends_import_without_host_application_initialization():
    script = """
import sys
sys.path.insert(0, sys.argv[1])
from rdmo_sensorsearch.backends.sms.backend import SMSBackend
from rdmo_sensorsearch.backends.o2a.backend import O2ABackend
from rdmo_sensorsearch.backends.gipp.backend import GIPPBackend
from rdmo_sensorsearch.config_models.backend_settings import SMSBackendSettings, O2ABackendSettings, GIPPBackendSettings
from rdmo_sensorsearch.contracts import BackendSuccess
from rdmo_sensorsearch.transport import TransportError
backend = SMSBackend(fetch=lambda *args, **kwargs: {"data": []},
                     base_url="https://sms.example/api", settings=SMSBackendSettings())
assert backend.get_mount_period("1", "2") == BackendSuccess(None)
O2ABackend(base_url="https://o2a.example", settings=O2ABackendSettings(), fetch=lambda *args, **kwargs: {})
GIPPBackend(base_url="https://gipp.example", settings=GIPPBackendSettings(), fetch=lambda *args, **kwargs: {})
assert not any(name.split(".", 1)[0] in {"django", "rdmo"} for name in sys.modules)
"""
    subprocess.run([sys.executable, "-I", "-c", script, str(REPOSITORY_ROOT)], check=True, capture_output=True, text=True)
