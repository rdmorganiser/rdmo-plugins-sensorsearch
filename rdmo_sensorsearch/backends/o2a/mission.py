"""O2A mission metadata, search and membership mechanics."""

from urllib.parse import quote, urlsplit

from rdmo_sensorsearch.config_models.backend_settings import O2ABackendSettings, O2AMissionQuerySettings
from rdmo_sensorsearch.contracts import (
    BackendFailure,
    BackendResult,
    BackendSuccess,
    ConfigurationMember,
    ConfigurationMembership,
    ConfigurationMetadata,
    ConfigurationPeriod,
    MountLocation,
    SearchRecord,
)
from rdmo_sensorsearch.transport import JSONFetcher, request_json


class O2AMissionAPI:
    def __init__(
        self,
        base_url: str,
        settings: O2ABackendSettings,
        fetch: JSONFetcher,
        search_settings: O2AMissionQuerySettings | None = None,
    ):
        self.base_url = settings.api_url.format(base_url=base_url)
        self.search_url = settings.mission_search_url.format(base_url=base_url)
        self.query_url = settings.mission_query_url
        self.settings = settings.mission
        self.search_settings = search_settings
        self.fetch = fetch

    def get_configuration(self, identifier: str) -> BackendResult[ConfigurationMetadata]:
        response = request_json(self.fetch, self.settings.mission_url.format(base_url=self.base_url, id=identifier), None)
        if isinstance(response, BackendFailure):
            return response
        data = response.value
        if not isinstance(data, dict):
            return BackendFailure((f"Unexpected O2A mission payload for ID {identifier}",))
        if not data:
            return BackendFailure((f"O2A mission request for ID {identifier} returned no mission data.",))
        origin = urlsplit(self.base_url)
        values = {"base_url": self.base_url, "base_url_origin": f"{origin.scheme}://{origin.netloc}", "id": identifier}
        return BackendSuccess(
            ConfigurationMetadata(
                data,
                self.settings.api_link_template.format(**values),
                self.settings.frontend_link_template.format(**values),
                identifier,
            )
        )

    def get_configuration_members(
        self,
        configuration: ConfigurationMetadata,
        *,
        period: ConfigurationPeriod | None = None,
        require_configuration_period: bool = False,
    ) -> BackendResult[ConfigurationMembership]:
        if period is not None or require_configuration_period:
            return BackendFailure(("O2A Registry does not support historical mission-membership filtering.",))
        identifier = configuration.identifier
        response = self._fetch_mission_items(identifier)
        if isinstance(response, BackendFailure):
            return response
        members = []
        errors = []
        for mission_item in response.value:
            item_id = mission_item.get("itemId")
            if item_id is None:
                continue
            item = request_json(self.fetch, self.settings.item_url.format(base_url=self.base_url, id=item_id), None)
            if isinstance(item, BackendFailure):
                errors.extend(f"O2A item request for mission item {item_id} failed: {error}" for error in item.errors)
                continue
            data = item.value
            if not isinstance(data, dict):
                errors.append(f"Unexpected O2A item payload for mission item {item_id}: {type(data).__name__}")
                continue
            if not data:
                errors.append(f"O2A item request for mission item {item_id} returned no item data.")
                continue
            attrs = {
                "mission_item_id": mission_item.get("id", ""),
                "mission_item_uuid": mission_item.get("@uuid", ""),
                "item_id": data.get("id", item_id),
                "item_uuid": data.get("@uuid", ""),
                "code": data.get("code", ""),
                "short_name": data.get("shortName", ""),
                "long_name": data.get("longName", ""),
                "name": data.get("longName") or data.get("shortName") or data.get("code") or "",
                "serial_number": data.get("serialNumber", ""),
                "model": data.get("model", ""),
                "manufacturer": data.get("manufacturer", ""),
            }
            members.append(
                ConfigurationMember(
                    str(item_id),
                    attrs,
                    configuration.document.get("startDate"),
                    configuration.document.get("endDate"),
                    MountLocation(),
                )
            )
        return BackendFailure(tuple(errors)) if errors else BackendSuccess(ConfigurationMembership(tuple(members)))

    def _fetch_mission_items(self, identifier: str) -> BackendResult[tuple[dict, ...]]:
        records = []
        seen_pages = set()
        settings = self.settings
        for page in range(settings.max_collection_pages):
            url = settings.mission_items_url.format(
                base_url=self.base_url,
                id=identifier,
                offset=page * settings.mission_item_page_size,
                page_size=settings.mission_item_page_size,
            )
            response = request_json(self.fetch, url, None)
            if isinstance(response, BackendFailure):
                return response
            payload = response.value
            if not isinstance(payload, (dict, list)):
                return BackendFailure((f"Unexpected O2A mission items payload: {type(payload).__name__}",))
            items = payload.get("records", []) if isinstance(payload, dict) else payload
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                return BackendFailure(("Malformed O2A mission items records.",))
            signature = tuple(str(item.get("@uuid") or item.get("id") or item.get("itemId")) for item in items)
            if items and signature in seen_pages:
                return BackendFailure(("O2A mission item pagination returned the same page more than once.",))
            seen_pages.add(signature)
            records.extend(items)
            if len(items) < settings.mission_item_page_size:
                return BackendSuccess(tuple(records))
        return BackendFailure((f"O2A mission item pagination exceeded {settings.max_collection_pages} pages.",))

    def search_configurations(self, query: str, limit: int) -> BackendResult[tuple[SearchRecord, ...]]:
        query = query.replace("\\", "\\\\").replace('"', '\\"').strip()
        if not query:
            return BackendSuccess(())
        settings = self.search_settings
        if settings is None:
            raise ValueError("O2A mission search settings are not configured.")
        where = settings.where_template.format(query=query)
        url = self.query_url.format(
            base_url=self.search_url,
            where=quote(where, safe='=*"'),
            sorts=quote(str(settings.sorts)),
            offset=settings.offset,
            hits=limit,
            query=quote(query),
        )
        response = request_json(self.fetch, url, None)
        if isinstance(response, BackendFailure):
            return response
        payload = response.value
        if not isinstance(payload, dict) or not isinstance(payload.get("records", []), list):
            return BackendFailure(("Unexpected O2A mission search payload.",))
        records = []
        for mission in payload.get("records", [])[:limit]:
            if not isinstance(mission, dict):
                return BackendFailure(("Malformed O2A mission search record.",))
            if mission.get("id") is None:
                continue
            records.append(
                SearchRecord(
                    str(mission["id"]),
                    {
                        "name": mission.get("name", ""),
                        "description": mission.get("description") or "",
                        "start_date": mission.get("startDate") or "",
                        "end_date": mission.get("endDate") or "",
                        "uuid": mission.get("@uuid") or "",
                    },
                )
            )
        return BackendSuccess(tuple(records))
