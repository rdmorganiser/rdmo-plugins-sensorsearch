"""Build fixture consumers using canonical backend configuration."""

from dataclasses import fields

from rdmo_sensorsearch import backend_assembly
from rdmo_sensorsearch.backends.sms.backend import SMSBackend
from rdmo_sensorsearch.backends.sms.membership import SMSConfigurationMembershipResolver
from rdmo_sensorsearch.config_models.backend_settings import SMSBackendSettings, SMSConfigurationEndpoints, SMSDeviceEndpoints
from rdmo_sensorsearch.contracts import BackendFailure, BackendSuccess
from rdmo_sensorsearch.handlers.sms_configuration import SensorManagementSystemConfigurationHandler
from rdmo_sensorsearch.handlers.sms_device import SensorManagementSystemDeviceHandler
from testing.transport_helpers import raising_fetch


def sms_backend_settings(section, **values):
    cls = SMSDeviceEndpoints if section == "device" else SMSConfigurationEndpoints
    names = {field.name for field in fields(cls)}
    endpoints = cls(**{name: values.pop(name) for name in tuple(values) if name in names})
    return SMSBackendSettings(**{section: endpoints}, **values)


def _make_handler(section, kwargs):
    base_url = kwargs.pop("base_url", "https://sms.example/api")
    cls = SMSDeviceEndpoints if section == "device" else SMSConfigurationEndpoints
    names = {field.name for field in fields(cls)} | {field.name for field in fields(SMSBackendSettings)} - {
        "device",
        "configuration",
    }
    settings = sms_backend_settings(section, **{name: kwargs.pop(name) for name in tuple(kwargs) if name in names})
    mapping = kwargs.pop("attribute_mapping", {})
    fallback = section == "configuration" and settings.configuration.configuration_self_link_path in mapping
    backend = SMSBackend(
        base_url=base_url,
        settings=settings,
        fetch=raising_fetch(backend_assembly.fetch_json),
        self_link_fallback_enabled=fallback,
    )
    cls = SensorManagementSystemDeviceHandler if section == "device" else SensorManagementSystemConfigurationHandler
    handler = cls(
        backend=backend, id_prefix=kwargs.pop("id_prefix", "sms" if section == "device" else "smscfg"), attribute_mapping=mapping
    )
    for name, value in kwargs.items():
        setattr(handler, name, value)
    return handler


def make_sms_device_handler(**kwargs):
    return _make_handler("device", kwargs)


def make_sms_configuration_handler(**kwargs):
    return _make_handler("configuration", kwargs)


def resolve_member_values(handler, **kwargs):
    resolver = SMSConfigurationMembershipResolver(
        fetch_device=lambda identifier: BackendSuccess(None),
        fetch_mount_action=lambda identifier: BackendSuccess(None),
    )
    result = resolver.resolve(**kwargs)
    if isinstance(result, BackendFailure):
        return [], list(result.errors)
    identifier = kwargs["configuration_data"]["data"].get("id")
    return [handler._member_value(member, identifier) for member in result.value], []
