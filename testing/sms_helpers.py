"""Build test consumers with explicit adapters and fixture-only settings."""

from dataclasses import fields

from rdmo_sensorsearch import backend_assembly
from rdmo_sensorsearch.backends.sms.backend import SMSBackend
from rdmo_sensorsearch.backends.sms.membership import SMSConfigurationMembershipResolver
from rdmo_sensorsearch.backends.sms.settings import SMSConfigurationSettings, SMSDeviceSettings
from rdmo_sensorsearch.contracts import BackendFailure, BackendSuccess
from rdmo_sensorsearch.handlers.sms_configuration import SensorManagementSystemConfigurationHandler
from rdmo_sensorsearch.handlers.sms_device import SensorManagementSystemDeviceHandler
from testing.transport_helpers import raising_fetch


def make_sms_device_handler(**kwargs):
    names = {field.name for field in fields(SMSDeviceSettings)}
    settings = SMSDeviceSettings(**{name: kwargs.pop(name) for name in names if name in kwargs})
    handler = SensorManagementSystemDeviceHandler(
        backend=SMSBackend(fetch=raising_fetch(backend_assembly.fetch_json), device_settings=settings),
        id_prefix=kwargs.pop("id_prefix", "sms"),
        attribute_mapping=kwargs.pop("attribute_mapping", {}),
    )
    for name, value in kwargs.items():
        setattr(handler, name, value)
    return handler


def make_sms_configuration_handler(**kwargs):
    kwargs.setdefault("base_url", "https://sms.example/api")
    names = {field.name for field in fields(SMSConfigurationSettings)}
    values = {name: kwargs.pop(name) for name in names if name in kwargs}
    path = values.get("configuration_self_link_path", "data.links.self")
    settings = SMSConfigurationSettings(**values, self_link_fallback_enabled=path in kwargs.get("attribute_mapping", {}))
    handler = SensorManagementSystemConfigurationHandler(
        backend=SMSBackend(fetch=raising_fetch(backend_assembly.fetch_json), configuration_settings=settings),
        id_prefix=kwargs.pop("id_prefix", "smscfg"),
        attribute_mapping=kwargs.pop("attribute_mapping", {}),
    )
    for name, value in kwargs.items():
        setattr(handler, name, value)
    return handler


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
