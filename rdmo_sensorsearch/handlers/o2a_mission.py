import logging
from collections import defaultdict
from datetime import timezone as dt_timezone

from rdmo_sensorsearch.client import fetch_json
from rdmo_sensorsearch.contracts import (
    CollectionAssignment,
    HandlerExecutionContext,
    HandlerFailure,
    HandlerOutcome,
    HandlerResult,
    RefreshDeviceDetails,
    SelectedDevice,
)
from rdmo_sensorsearch.handlers.base import BackendRecordHandler
from rdmo_sensorsearch.handlers.parser import evaluate_jmespath_mapping, parse_datetime
from rdmo_sensorsearch.naming import configuration_short_label

logger = logging.getLogger(__name__)


class O2ARegistryMissionHandler(BackendRecordHandler):
    """
    Resolves one O2A Registry mission and materializes its associated items.
    """

    mission_url = "{base_url}/missions/{id}"
    mission_items_url = "{base_url}/missions/{id}/items?offset={offset}&hits={page_size}"
    item_url = "{base_url}/items/{id}"
    mission_item_page_size = 100
    max_collection_pages = 1000

    item_id_prefix: str
    item_text_prefix = "O2A Item"
    item_text_template = "{configuration} {prefix}({item_id}): {name}{serial}"

    mission_start_date_path = "startDate"
    mission_end_date_path = "endDate"
    date_mapping_paths = ["startDate", "endDate"]
    datetime_output_format = "%Y-%m-%d %H:%M"

    api_link_template = "{base_url}/missions/{id}"
    frontend_link_template = "{base_url_origin}/missions/{id}"

    def handle(
        self,
        backend_id: str,
        *,
        context: HandlerExecutionContext,
        auth_token: str | None = None,
    ) -> HandlerOutcome:
        mission_data = fetch_json(self.mission_url.format(base_url=self.base_url, id=backend_id))
        if isinstance(mission_data, dict) and "errors" in mission_data:
            logger.debug("Errors in O2A mission data returned for ID %s: %s", backend_id, mission_data["errors"])
            return HandlerFailure(tuple(mission_data["errors"]))
        if not isinstance(mission_data, dict):
            logger.warning("Unexpected O2A mission payload for ID %s: %s", backend_id, type(mission_data).__name__)
            return HandlerFailure((f"Unexpected O2A mission payload for ID {backend_id}",))
        if not mission_data:
            return HandlerFailure((f"O2A mission request for ID {backend_id} returned no mission data.",))

        mapped_values = evaluate_jmespath_mapping(self.attribute_mapping, mission_data)
        self._set_mission_links(mapped_values, backend_id)
        self._normalize_datetimes(mapped_values)

        collections = []
        effects = []
        selected_devices_attribute_uri = getattr(self, "selected_devices_attribute_uri", None)
        preserve_existing_collections = bool(context and context.preserve_existing_collections)
        require_configuration_period = bool(context and context.require_configuration_period)
        if not selected_devices_attribute_uri or preserve_existing_collections:
            return HandlerResult(mapped_values=mapped_values)

        if require_configuration_period:
            return HandlerFailure(("O2A Registry does not support historical mission-membership filtering.",))

        mission_items_data = self._fetch_mission_items(backend_id)
        if isinstance(mission_items_data, dict) and "errors" in mission_items_data:
            logger.debug(
                "Errors in O2A mission items data returned for ID %s: %s",
                backend_id,
                mission_items_data["errors"],
            )
            return HandlerFailure(tuple(mission_items_data["errors"]))

        mission_period = (
            self._format_timepoint(mission_data.get(self.mission_start_date_path)),
            self._format_timepoint(mission_data.get(self.mission_end_date_path)),
        )
        selected_device_values, member_errors = self._build_selected_device_values(
            mission_id=backend_id,
            mission_data=mission_data,
            mission_items_data=mission_items_data,
            mission_period=mission_period,
        )
        if member_errors:
            return HandlerFailure(tuple(member_errors))
        collections.append(
            CollectionAssignment(
                attribute_uri=selected_devices_attribute_uri,
                page_uri=self.selected_devices_page_uri,
                values=tuple(selected_device_values),
            )
        )

        device_collection_attribute_uri = getattr(self, "device_collection_attribute_uri", None)
        if device_collection_attribute_uri:
            selected_devices = [
                SelectedDevice(
                    text=value["text"],
                    external_id=value["external_id"],
                    instrument_start=value.get("instrument_start"),
                    instrument_end=value.get("instrument_end"),
                )
                for value in selected_device_values
                if value.get("external_id")
            ]
            effects.append(
                RefreshDeviceDetails(
                    selected_devices=tuple(selected_devices),
                    selected_devices_attribute_uri=selected_devices_attribute_uri,
                    device_collection_attribute_uri=device_collection_attribute_uri,
                )
            )

        return HandlerResult(
            mapped_values=mapped_values,
            collections=tuple(collections),
            effects=tuple(effects),
        )

    def _set_mission_links(self, mapped_values: dict[str, str | None], mission_id: str) -> None:
        values = {
            "base_url": self.base_url,
            "base_url_origin": self.base_url_origin,
            "id": mission_id,
        }

        api_attribute_uri = getattr(self, "api_link_attribute_uri", None)
        if api_attribute_uri:
            mapped_values[api_attribute_uri] = self.api_link_template.format(**values)

        frontend_attribute_uri = getattr(self, "frontend_link_attribute_uri", None)
        if frontend_attribute_uri:
            mapped_values[frontend_attribute_uri] = self.frontend_link_template.format(**values)

    def _normalize_datetimes(self, mapped_values: dict[str, str | None]) -> None:
        datetime_paths = set(getattr(self, "date_mapping_paths", []))
        for source_path, attribute_uri in self.attribute_mapping.items():
            if source_path not in datetime_paths:
                continue

            value = mapped_values.get(attribute_uri)
            formatted = self._format_timepoint(value)
            if formatted is not None:
                mapped_values[attribute_uri] = formatted

    def get_member_device_period(self, mapped_values=None) -> tuple[str | None, str | None]:
        mapped_values = mapped_values or {}
        start_attribute_uri = self.attribute_mapping.get(self.mission_start_date_path)
        end_attribute_uri = self.attribute_mapping.get(self.mission_end_date_path)
        return (
            mapped_values.get(start_attribute_uri) if start_attribute_uri else None,
            mapped_values.get(end_attribute_uri) if end_attribute_uri else None,
        )

    def _build_selected_device_values(
        self,
        mission_id: str,
        mission_data: dict,
        mission_items_data: dict,
        mission_period: tuple[str | None, str | None],
    ) -> tuple[list[dict[str, str]], list[str]]:
        values = []
        errors = []
        for mission_item in self._mission_items(mission_items_data):
            item_id = mission_item.get("itemId")
            if item_id is None:
                continue

            item_data, item_errors = self._fetch_item(str(item_id))
            if item_errors:
                errors.extend(item_errors)
                continue

            values.append(
                {
                    "text": self._format_item_text(
                        mission_id=mission_id,
                        mission_data=mission_data,
                        mission_item=mission_item,
                        item_data=item_data,
                    ),
                    "external_id": f"{self.item_id_prefix}:{item_id}",
                    "instrument_start": mission_period[0],
                    "instrument_end": mission_period[1],
                }
            )

        return values, errors

    def _fetch_mission_items(self, mission_id: str) -> dict:
        records = []
        seen_pages: set[tuple[str, ...]] = set()
        offset = 0

        for _page_number in range(1, self.max_collection_pages + 1):
            payload = fetch_json(
                self.mission_items_url.format(
                    base_url=self.base_url,
                    id=mission_id,
                    offset=offset,
                    page_size=self.mission_item_page_size,
                )
            )
            if isinstance(payload, dict) and "errors" in payload:
                return payload
            if not isinstance(payload, (dict, list)):
                return {"errors": [f"Unexpected O2A mission items payload: {type(payload).__name__}"]}

            page_records = self._mission_items(payload)
            signature = tuple(str(item.get("@uuid") or item.get("id") or item.get("itemId")) for item in page_records)
            if page_records and signature in seen_pages:
                return {"errors": ["O2A mission item pagination returned the same page more than once."]}
            seen_pages.add(signature)
            records.extend(page_records)

            if len(page_records) < self.mission_item_page_size:
                return {"records": records}
            offset += self.mission_item_page_size

        return {"errors": [f"O2A mission item pagination exceeded {self.max_collection_pages} pages."]}

    def _mission_items(self, mission_items_data: dict | list) -> list[dict]:
        if isinstance(mission_items_data, dict):
            records = mission_items_data.get("records", [])
            return records if isinstance(records, list) else []
        return mission_items_data if isinstance(mission_items_data, list) else []

    def _fetch_item(self, item_id: str) -> tuple[dict | None, list[str]]:
        item_data = fetch_json(self.item_url.format(base_url=self.base_url, id=item_id))
        if isinstance(item_data, dict) and "errors" in item_data:
            return None, [f"O2A item request for mission item {item_id} failed: {error}" for error in item_data["errors"]]
        if not isinstance(item_data, dict):
            return None, [f"Unexpected O2A item payload for mission item {item_id}: {type(item_data).__name__}"]
        if not item_data:
            return None, [f"O2A item request for mission item {item_id} returned no item data."]
        return item_data, []

    def _format_item_text(
        self,
        mission_id: str,
        mission_data: dict,
        mission_item: dict,
        item_data: dict,
    ) -> str:
        serial = f" (s/n: {item_data['serialNumber']})" if item_data.get("serialNumber") else ""
        name = item_data.get("longName") or item_data.get("shortName") or item_data.get("code") or ""
        values = defaultdict(
            str,
            {
                "prefix": self.item_text_prefix,
                "configuration": configuration_short_label(f"{self.id_prefix}:{mission_id}") or f"M({mission_id})",
                "mission_id": mission_id,
                "mission_name": mission_data.get("name", ""),
                "mission_uuid": mission_data.get("@uuid", ""),
                "mission_item_id": mission_item.get("id", ""),
                "mission_item_uuid": mission_item.get("@uuid", ""),
                "item_id": item_data.get("id", mission_item.get("itemId", "")),
                "item_uuid": item_data.get("@uuid", ""),
                "code": item_data.get("code", ""),
                "short_name": item_data.get("shortName", ""),
                "long_name": item_data.get("longName", ""),
                "name": name,
                "serial_number": item_data.get("serialNumber", ""),
                "serial": serial,
                "model": item_data.get("model", ""),
                "manufacturer": item_data.get("manufacturer", ""),
            },
        )
        return self.item_text_template.format_map(values)

    def _format_timepoint(self, value) -> str | None:
        parsed = parse_datetime(value) if isinstance(value, str) and value else None
        if parsed is None:
            return None
        if parsed.tzinfo is not None:
            utc_value = parsed.astimezone(dt_timezone.utc)
        else:
            utc_value = parsed.replace(tzinfo=dt_timezone.utc)
        return utc_value.strftime(self.datetime_output_format)
