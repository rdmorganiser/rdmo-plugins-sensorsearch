"""Assemble SMS consumers with injected adapters in regression fixtures."""

from rdmo_sensorsearch.backend_assembly import sms_constructor_kwargs
from rdmo_sensorsearch.handlers.sms_device import SensorManagementSystemDeviceHandler


def make_sms_device_handler(**kwargs):
    return SensorManagementSystemDeviceHandler(**sms_constructor_kwargs("SensorManagementSystemDeviceHandler", kwargs))
