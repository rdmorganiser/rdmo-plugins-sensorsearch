"""O2A capabilities with injected transport and typed endpoint settings."""

from rdmo_sensorsearch.backends.o2a.item import O2AItemAPI
from rdmo_sensorsearch.backends.o2a.mission import O2AMissionAPI
from rdmo_sensorsearch.config_models.backend_settings import O2ABackendSettings, O2AMissionQuerySettings
from rdmo_sensorsearch.contracts import (
    BackendResult,
    ConfigurationMembership,
    ConfigurationMetadata,
    ConfigurationPeriod,
    DeviceMetadata,
    SearchRecord,
)
from rdmo_sensorsearch.transport import JSONFetcher


class O2ABackend:
    def __init__(
        self,
        *,
        base_url: str,
        settings: O2ABackendSettings,
        fetch: JSONFetcher,
        mission_query_settings: O2AMissionQuerySettings | None = None,
    ):
        self.base_url = base_url
        self.settings = settings
        self._item = O2AItemAPI(base_url, settings, fetch)
        self._mission = O2AMissionAPI(base_url, settings, fetch, mission_query_settings)

    def get_device(self, device_id: str, *, auth_token: str | None = None) -> BackendResult[DeviceMetadata]:
        return self._item.get_device(device_id)

    def search_devices(self, query: str, *, limit: int, auth_token: str | None = None) -> BackendResult[tuple[SearchRecord, ...]]:
        return self._item.search_devices(query, limit)

    def get_configuration(self, configuration_id: str, *, auth_token: str | None = None) -> BackendResult[ConfigurationMetadata]:
        return self._mission.get_configuration(configuration_id)

    def get_configuration_members(
        self,
        configuration: ConfigurationMetadata,
        *,
        period: ConfigurationPeriod | None = None,
        require_configuration_period: bool = False,
        auth_token: str | None = None,
    ) -> BackendResult[ConfigurationMembership]:
        return self._mission.get_configuration_members(
            configuration, period=period, require_configuration_period=require_configuration_period
        )

    def search_configurations(
        self, query: str, *, limit: int, auth_token: str | None = None
    ) -> BackendResult[tuple[SearchRecord, ...]]:
        return self._mission.search_configurations(query, limit)
