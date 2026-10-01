"""Assemble SMS consumers with injected adapters in regression fixtures."""

from rdmo_sensorsearch.backend_assembly import sms_constructor_kwargs
from rdmo_sensorsearch.backends.sms.membership import SMSConfigurationMembershipResolver
from rdmo_sensorsearch.contracts import BackendFailure, BackendSuccess
from rdmo_sensorsearch.handlers.sms_configuration import SensorManagementSystemConfigurationHandler
from rdmo_sensorsearch.handlers.sms_device import SensorManagementSystemDeviceHandler


def make_sms_device_handler(**kwargs):
    return SensorManagementSystemDeviceHandler(**sms_constructor_kwargs("SensorManagementSystemDeviceHandler", kwargs))


def make_sms_configuration_handler(**kwargs):
    kwargs.setdefault("base_url", "https://sms.example/api")
    return SensorManagementSystemConfigurationHandler(
        **sms_constructor_kwargs("SensorManagementSystemConfigurationHandler", kwargs)
    )


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
