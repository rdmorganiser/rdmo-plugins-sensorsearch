import logging

from rdmo_sensorsearch.config_models.backend_settings import GIPPBackendSettings
from rdmo_sensorsearch.contracts import BackendFailure, BackendResult, BackendSuccess, DeviceMetadata, SearchRecord
from rdmo_sensorsearch.transport import JSONFetcher, request_json

logger = logging.getLogger(__name__)


class GIPPBackend:
    """GIPP search and metadata with injected transport; no configuration capabilities."""

    def __init__(self, *, base_url: str, settings: GIPPBackendSettings, fetch: JSONFetcher):
        self.base_url = base_url
        self.settings = settings
        self.fetch = fetch

    def get_device(self, device_id: str, *, auth_token: str | None = None) -> BackendResult[DeviceMetadata]:
        root = self.settings.metadata_url.format(base_url=self.base_url)
        response = request_json(self.fetch, self.settings.json_url.format(base_url=root, id=device_id), None)
        if isinstance(response, BackendFailure):
            return response
        data = response.value
        if not isinstance(data, dict):
            return BackendFailure((f"Unexpected GIPP payload for instrument {device_id}: {type(data).__name__}",))
        if not data:
            return BackendFailure((f"GIPP request for instrument {device_id} returned no instrument data.",))
        return BackendSuccess(DeviceMetadata(data))

    def search_devices(self, query: str, *, limit: int, auth_token: str | None = None) -> BackendResult[tuple[SearchRecord, ...]]:
        if not query:
            return BackendSuccess(())
        response = request_json(self.fetch, self.settings.instruments_url.format(base_url=self.base_url), None)
        if isinstance(response, BackendFailure):
            return response
        instruments = response.value
        if not isinstance(instruments, list):
            return BackendFailure(("Unexpected GIPP instruments payload.",))
        records = []
        for instrument in instruments:
            data = instrument.get("Instrument") if isinstance(instrument, dict) else None
            if not isinstance(data, dict) or "id" not in data or "code" not in data:
                logger.debug("Skipping malformed GIPP instrument entry")
                continue
            if any(query.lower() in str(value).lower() for value in data.values()):
                records.append(SearchRecord(str(data["id"]), data))
                if len(records) >= limit:
                    break
        return BackendSuccess(tuple(records))
