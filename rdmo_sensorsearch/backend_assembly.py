"""Composition root translating deployment settings into SMS capabilities."""

from dataclasses import fields

from rdmo_sensorsearch.backends.sms.backend import SMSBackend
from rdmo_sensorsearch.backends.sms.settings import SMSDeviceSettings, SMSSearchSettings
from rdmo_sensorsearch.client import fetch_json

SMS_DEVICE_SEARCH_URL = "{base_url}?q={query}"
SMS_CONFIGURATION_SEARCH_URL = (
    "{base_url}?page[size]={page_size}&page[number]=1&include=created_by.contact"
    "&filter=[]&q={query}&sort=label&hide_archived=false"
)


def sms_constructor_kwargs(class_name: str, settings: dict) -> dict:
    """Leave catalog/option settings with consumers; inject SMS endpoint settings."""
    result = dict(settings)
    if class_name == "SensorManagementSystemDeviceHandler":
        names = {field.name for field in fields(SMSDeviceSettings)}
        values = {key: value for key, value in result.items() if key in names}
        result["backend"] = SMSBackend(fetch=fetch_json, device_settings=SMSDeviceSettings(**values))
        for name in {"device_url", "contact_url", "backend_link_marker"}:
            result.pop(name, None)
    elif class_name in {"SensorManagementSystemDeviceProvider", "SensorManagementSystemConfigurationProvider"}:
        default_url = (
            SMS_DEVICE_SEARCH_URL if class_name == "SensorManagementSystemDeviceProvider" else SMS_CONFIGURATION_SEARCH_URL
        )
        query_url = result.pop("query_url", default_url)
        result["backend"] = SMSBackend(fetch=fetch_json, search_settings=SMSSearchSettings(result["base_url"], query_url))
    return result
