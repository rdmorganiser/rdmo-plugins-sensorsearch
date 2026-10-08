from urllib.parse import quote

from rdmo_sensorsearch.backends.sms.configuration import SMSConfigurationAPI
from rdmo_sensorsearch.backends.sms.device import SMSDeviceAPI
from rdmo_sensorsearch.config_models.backend_settings import SMSBackendSettings
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
        self, *, base_url: str, settings: SMSBackendSettings, fetch: JSONFetcher, self_link_fallback_enabled: bool = False
    ):
        self.base_url = base_url
        self.settings = settings
        self._fetch = fetch
        self._device = SMSDeviceAPI(base_url, settings, fetch)
        self._configuration = SMSConfigurationAPI(
            base_url, settings, fetch, self_link_fallback_enabled=self_link_fallback_enabled
        )

    def get_device(self, device_id: str, *, auth_token: str | None = None) -> BackendResult[DeviceMetadata]:
        return self._device.get_device(device_id, auth_token=auth_token)

    def search_devices(self, query: str, *, limit: int, auth_token: str | None = None) -> BackendResult[tuple[SearchRecord, ...]]:
        return self._search("device", query, limit, auth_token)

    def search_configurations(
        self, query: str, *, limit: int, auth_token: str | None = None
    ) -> BackendResult[tuple[SearchRecord, ...]]:
        return self._search("configuration", query, limit, auth_token)

    def _search(self, resource: str, query: str, limit: int, auth_token: str | None) -> BackendResult[tuple[SearchRecord, ...]]:
        resource_url = getattr(self.settings, f"{resource}_search_url").format(base_url=self.base_url)
        query_url = getattr(self.settings, f"{resource}_query_url")
        url = query_url.format(base_url=resource_url, query=quote(query), page_size=limit)
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
        return self._device.get_mount_location(
            device_id, configuration_id, period=period, best_effort=best_effort, auth_token=auth_token
        )

    def get_configuration(self, configuration_id: str, *, auth_token: str | None = None) -> BackendResult[ConfigurationMetadata]:
        return self._configuration.get_configuration(configuration_id, auth_token=auth_token)

    def get_configuration_members(
        self,
        configuration: ConfigurationMetadata,
        *,
        period: ConfigurationPeriod | None = None,
        require_configuration_period: bool = False,
        auth_token: str | None = None,
    ) -> BackendResult[ConfigurationMembership]:
        return self._configuration.get_configuration_members(
            configuration, period=period, require_configuration_period=require_configuration_period, auth_token=auth_token
        )

    def get_static_location(
        self, configuration_id: str, *, auth_token: str | None = None
    ) -> BackendResult[StaticLocation | None]:
        return self._configuration.get_static_location(configuration_id, auth_token=auth_token)
