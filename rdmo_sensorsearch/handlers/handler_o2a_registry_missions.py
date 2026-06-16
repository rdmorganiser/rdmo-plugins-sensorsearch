import logging
from collections import defaultdict
from datetime import timezone as dt_timezone
from functools import partial
from urllib.parse import urlsplit

from django.utils import timezone as django_timezone

from rdmo_sensorsearch.client import fetch_json
from rdmo_sensorsearch.handlers.base import CollectionAssignment, GenericSearchHandler, HandlerResult
from rdmo_sensorsearch.handlers.parser import map_jamespath_to_attribute_uri, parse_datetime
from rdmo_sensorsearch.signals.device_set_sync import (
    SelectedDevice,
    sync_device_detail_blocks_from_payload,
)

logger = logging.getLogger(__name__)


class O2ARegistryMissionsHandler(GenericSearchHandler):
    """
    Resolves one O2A Registry mission and materializes its associated items.
    """

    id_prefix = "o2amission"
    base_url = "https://registry.o2a-data.de/rest/v2"

    mission_url = "{base_url}/missions/{id}"
    mission_items_url = "{base_url}/missions/{id}/items?offset=0&hits={page_size}"
    item_url = "{base_url}/items/{id}"
    mission_item_max_hits = 100

    item_id_prefix = "o2aregistry"
    item_text_prefix = "O2A Item"
    item_text_template = "{prefix}({item_id}) Mission({mission_id}): {name}{serial}"

    mission_start_date_path = "startDate"
    mission_end_date_path = "endDate"
    date_mapping_paths = ["startDate", "endDate"]
    datetime_output_format = "%Y-%m-%d %H:%M"

    api_link_template = "{base_url}/missions/{id}"
    frontend_link_template = "{base_url_origin}/missions/{id}"

    def handle(self, id_: str, instance=None) -> dict | HandlerResult:
        mission_data = fetch_json(self.mission_url.format(base_url=self.base_url, id=id_))
        if isinstance(mission_data, dict) and "errors" in mission_data:
            logger.debug("Errors in O2A mission data returned for ID %s: %s", id_, mission_data["errors"])
            return mission_data
        if not isinstance(mission_data, dict):
            logger.warning("Unexpected O2A mission payload for ID %s: %s", id_, type(mission_data).__name__)
            return {"errors": [f"Unexpected O2A mission payload for ID {id_}"]}

        mission_items_data = fetch_json(
            self.mission_items_url.format(
                base_url=self.base_url,
                id=id_,
                page_size=self.mission_item_max_hits,
            )
        )
        if isinstance(mission_items_data, dict) and "errors" in mission_items_data:
            logger.debug(
                "Errors in O2A mission items data returned for ID %s: %s",
                id_,
                mission_items_data["errors"],
            )
            return mission_items_data

        mapped_values = map_jamespath_to_attribute_uri(self.attribute_mapping, mission_data)
        self._set_mission_links(mapped_values, id_)
        self._normalize_datetimes(mapped_values)

        result = HandlerResult(mapped_values=mapped_values, collections=[])
        member_sensors_attribute_uri = getattr(self, "member_sensors_attribute_uri", None)
        if not member_sensors_attribute_uri:
            return result

        mission_period = (
            self._format_timepoint(mission_data.get(self.mission_start_date_path)),
            self._format_timepoint(mission_data.get(self.mission_end_date_path)),
        )
        member_sensor_values = self._build_member_sensor_values(
            mission_id=id_,
            mission_data=mission_data,
            mission_items_data=mission_items_data,
            mission_period=mission_period,
        )
        result.collections.append(
            CollectionAssignment(
                attribute_uri=member_sensors_attribute_uri,
                values=member_sensor_values,
            )
        )

        device_collection_attribute_uri = getattr(self, "device_collection_attribute_uri", None)
        if instance is not None and device_collection_attribute_uri:
            selected_devices = [
                SelectedDevice(
                    text=value["text"],
                    external_id=value["external_id"],
                    instrument_start=value.get("instrument_start"),
                    instrument_end=value.get("instrument_end"),
                )
                for value in member_sensor_values
                if value.get("external_id")
            ]
            result.post_actions.append(
                partial(
                    sync_device_detail_blocks_from_payload,
                    project=instance.project,
                    catalog=instance.project.catalog,
                    scope_prefix=instance.set_prefix,
                    source_set_index=instance.set_index,
                    selected_devices=selected_devices,
                    selected_devices_attribute_uri=member_sensors_attribute_uri,
                    device_collection_attribute_uri=device_collection_attribute_uri,
                    configuration_search_attribute_uri=instance.attribute.uri,
                    configuration_external_id=instance.external_id,
                )
            )

        return result

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

    @property
    def base_url_origin(self) -> str:
        parsed = urlsplit(self.base_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _normalize_datetimes(self, mapped_values: dict[str, str | None]) -> None:
        datetime_paths = set(getattr(self, "date_mapping_paths", []))
        for source_path, attribute_uri in self.attribute_mapping.items():
            if source_path not in datetime_paths:
                continue

            value = mapped_values.get(attribute_uri)
            formatted = self._format_timepoint(value)
            if formatted is not None:
                mapped_values[attribute_uri] = formatted

    def _build_member_sensor_values(
        self,
        mission_id: str,
        mission_data: dict,
        mission_items_data: dict,
        mission_period: tuple[str | None, str | None],
    ) -> list[dict[str, str]]:
        values = []
        for mission_item in self._mission_items(mission_items_data):
            item_id = mission_item.get("itemId")
            if item_id is None:
                continue

            item_data = self._fetch_item(str(item_id))
            if item_data is None:
                logger.warning("O2A mission item %s could not be resolved", item_id)
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

        return values

    def _mission_items(self, mission_items_data: dict | list) -> list[dict]:
        if isinstance(mission_items_data, dict):
            records = mission_items_data.get("records", [])
            return records if isinstance(records, list) else []
        return mission_items_data if isinstance(mission_items_data, list) else []

    def _fetch_item(self, item_id: str) -> dict | None:
        item_data = fetch_json(self.item_url.format(base_url=self.base_url, id=item_id))
        if isinstance(item_data, dict) and "errors" in item_data:
            logger.warning("Could not fetch O2A item %s: %s", item_id, item_data["errors"])
            return None
        return item_data if isinstance(item_data, dict) else None

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
        if django_timezone.is_aware(parsed):
            utc_value = parsed.astimezone(dt_timezone.utc)
        else:
            utc_value = django_timezone.make_aware(parsed, dt_timezone.utc)
        return utc_value.strftime(self.datetime_output_format)
