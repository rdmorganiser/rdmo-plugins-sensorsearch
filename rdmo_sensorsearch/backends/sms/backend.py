from urllib.parse import quote

from rdmo_sensorsearch.backends.sms.configuration import SMSConfigurationAPI
from rdmo_sensorsearch.backends.sms.device import SMSDeviceAPI
from rdmo_sensorsearch.backends.sms.settings import SMSConfigurationSettings, SMSDeviceSettings, SMSSearchSettings
from rdmo_sensorsearch.contracts import (
    BackendFailure,
    BackendResult,
    BackendSuccess,
    ConfigurationMembership,
    ConfigurationMetadata,
    ConfigurationPeriod,
    DeviceMetadata,
    MountLocation,
    MountPeriod,
    SearchRecord,
    StaticLocation,
)
from rdmo_sensorsearch.transport import JSONFetcher, request_json


class SMSBackend:
    """SMS capabilities; transport and endpoint configuration are injected."""

    def __init__(
        self,
        *,
        fetch: JSONFetcher,
        device_settings: SMSDeviceSettings | None = None,
        search_settings: SMSSearchSettings | None = None,
        configuration_settings: SMSConfigurationSettings | None = None,
    ):
        self._fetch = fetch
        self._device = SMSDeviceAPI(device_settings, fetch) if device_settings is not None else None
        self._search_settings = search_settings
        self._configuration = SMSConfigurationAPI(configuration_settings, fetch) if configuration_settings is not None else None

    def get_device(self, device_id: str, *, auth_token: str | None = None) -> BackendResult[DeviceMetadata]:
        if self._device is None:
            raise ValueError("Device metadata endpoints are not configured.")
        return self._device.get_device(device_id, auth_token=auth_token)

    def search_devices(self, query: str, *, limit: int, auth_token: str | None = None) -> BackendResult[tuple[SearchRecord, ...]]:
        return self._search(query, limit, auth_token)

    def search_configurations(
        self, query: str, *, limit: int, auth_token: str | None = None
    ) -> BackendResult[tuple[SearchRecord, ...]]:
        return self._search(query, limit, auth_token)

    def _search(self, query: str, limit: int, auth_token: str | None) -> BackendResult[tuple[SearchRecord, ...]]:
        settings = self._search_settings
        if settings is None:
            raise ValueError("Search endpoints are not configured.")
        url = settings.query_url.format(base_url=settings.base_url, query=quote(query), page_size=limit)
        response = request_json(self._fetch, url, auth_token)
        if isinstance(response, BackendFailure):
            return response
        payload = response.value
        if not isinstance(payload, dict) or not isinstance(payload.get("data", []), list):
            return BackendFailure(("Unexpected SMS search payload.",))
        records = payload.get("data", [])[:limit]
        if any(
            not isinstance(record, dict) or "id" not in record or not isinstance(record.get("attributes"), dict)
            for record in records
        ):
            return BackendFailure(("Malformed SMS search data.",))
        return BackendSuccess(tuple(SearchRecord(record["id"], record["attributes"]) for record in records))

    def get_mount_period(
        self, device_id: str, configuration_id: str, *, serial_number: str | None = None, auth_token: str | None = None
    ) -> BackendResult[MountPeriod | None]:
        if self._device is None:
            raise ValueError("Device metadata endpoints are not configured.")
        return self._device.get_mount_period(device_id, configuration_id, serial_number=serial_number, auth_token=auth_token)

    def get_mount_location(
        self,
        device_id: str,
        configuration_id: str,
        *,
        period: MountPeriod | None = None,
        best_effort: bool = False,
        auth_token: str | None = None,
    ) -> BackendResult[MountLocation | None]:
        if self._device is None:
            raise ValueError("Device metadata endpoints are not configured.")
        return self._device.get_mount_location(
            device_id, configuration_id, period=period, best_effort=best_effort, auth_token=auth_token
        )

    def get_configuration(self, configuration_id: str, *, auth_token: str | None = None) -> BackendResult[ConfigurationMetadata]:
        if self._configuration is None:
            raise ValueError("Configuration metadata endpoints are not configured.")
        return self._configuration.get_configuration(configuration_id, auth_token=auth_token)

    def get_configuration_members(
        self,
        configuration: ConfigurationMetadata,
        *,
        period: ConfigurationPeriod | None = None,
        require_configuration_period: bool = False,
        auth_token: str | None = None,
    ) -> BackendResult[ConfigurationMembership]:
        if self._configuration is None:
            raise ValueError("Configuration metadata endpoints are not configured.")
        return self._configuration.get_configuration_members(
            configuration, period=period, require_configuration_period=require_configuration_period, auth_token=auth_token
        )

    def get_static_location(
        self, configuration_id: str, *, auth_token: str | None = None
    ) -> BackendResult[StaticLocation | None]:
        if self._configuration is None:
            raise ValueError("Configuration metadata endpoints are not configured.")
        return self._configuration.get_static_location(configuration_id, auth_token=auth_token)
