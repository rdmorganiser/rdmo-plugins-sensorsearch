import logging
from datetime import datetime
from urllib.parse import urljoin, urlsplit

from rdmo.projects.models import Value

from rdmo_sensorsearch.client import fetch_json
from rdmo_sensorsearch.handlers.base import CollectionAssignment, GenericSearchHandler, HandlerResult
from rdmo_sensorsearch.handlers.parser import map_jamespath_to_attribute_uri

logger = logging.getLogger(__name__)


class SensorManagementSystemConfigurationsHandler(GenericSearchHandler):
    """
    Resolves one SMS configuration and materializes its mounted devices.
    """

    configuration_url = "{base_url}/configurations/{id}"
    device_url = "{base_url}/devices/{id}"
    device_mount_action_url = "{base_url}/device-mount-actions/{id}"
    device_mount_actions_url = (
        "{base_url}/device-mount-actions?filter[configuration_id]={id}&include=device&page[size]={page_size}"
    )
    mounted_sensor_max_hits = 100
    configuration_self_link_path = "data.links.self"
    configuration_start_date_path = "data.attributes.start_date"
    configuration_end_date_path = "data.attributes.end_date"
    frontend_link_suffix = None  # redirects to "/basic"
    backend_link_marker = "/backend/api/v1/"

    def handle(self, id_: str, instance=None) -> dict | HandlerResult:
        configuration_data = fetch_json(self.configuration_url.format(base_url=self.base_url, id=id_))
        logger.debug("Fetched SMS configuration payload for ID %s: %s", id_, configuration_data)
        if "errors" in configuration_data:
            logger.debug("Errors in configuration data returned for ID %s: %s", id_, configuration_data["errors"])
            return configuration_data

        mount_action_data = fetch_json(
            self.device_mount_actions_url.format(
                base_url=self.base_url,
                id=id_,
                page_size=self.mounted_sensor_max_hits,
            )
        )
        if "errors" in mount_action_data:
            logger.debug("Errors in device mount action data returned for ID %s: %s", id_, mount_action_data["errors"])
            return mount_action_data

        mapped_values = map_jamespath_to_attribute_uri(self.attribute_mapping, configuration_data)
        self._set_configuration_links(mapped_values, configuration_data)
        self._normalize_configuration_datetimes(mapped_values)

        result = HandlerResult(
            mapped_values=mapped_values,
            collections=[],
        )

        if getattr(self, "member_sensors_attribute_uri", None):
            cfg_period = self._get_cfg_period(instance)
            result.collections.append(
                CollectionAssignment(
                    attribute_uri=self.member_sensors_attribute_uri,
                    values=self._build_member_sensor_values(
                        configuration_data=configuration_data,
                        mount_action_data=mount_action_data,
                        cfg_period=cfg_period,
                    ),
                )
            )

        return result

    def _set_configuration_links(self, mapped_values: dict[str, str | None], configuration_data: dict) -> None:
        raw_self_link = self._get_configuration_self_link(configuration_data)
        if not raw_self_link:
            return

        api_link = self._to_absolute_link(raw_self_link)

        api_attribute_uri = getattr(self, "api_link_attribute_uri", None)
        if api_attribute_uri:
            mapped_values[api_attribute_uri] = api_link

        frontend_attribute_uri = getattr(self, "frontend_link_attribute_uri", None)
        if frontend_attribute_uri:
            mapped_values[frontend_attribute_uri] = self._to_frontend_link(api_link)

    def _get_configuration_self_link(self, configuration_data: dict) -> str | None:
        for source_path, attribute_uri in self.attribute_mapping.items():
            if source_path != self.configuration_self_link_path:
                continue
            value = map_jamespath_to_attribute_uri({source_path: attribute_uri}, configuration_data).get(attribute_uri)
            if isinstance(value, str) and value:
                return value
        return None

    def _to_absolute_link(self, value: str) -> str:
        return urljoin(self._base_origin(), value)

    def _to_frontend_link(self, api_link: str) -> str:
        if self.backend_link_marker in api_link:
            frontend_link = api_link.replace(self.backend_link_marker, "/", 1)
        else:
            frontend_link = api_link

        if not self.frontend_link_suffix:
            return frontend_link

        if frontend_link.endswith(self.frontend_link_suffix):
            return frontend_link
        return f"{frontend_link.rstrip('/')}{self.frontend_link_suffix}"

    def _base_origin(self) -> str:
        parsed = urlsplit(self.base_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _normalize_configuration_datetimes(self, mapped_values: dict[str, str | None]) -> None:
        datetime_paths = {
            self.configuration_start_date_path,
            self.configuration_end_date_path,
        }

        for source_path, attribute_uri in self.attribute_mapping.items():
            if source_path not in datetime_paths:
                continue

            value = mapped_values.get(attribute_uri)
            if not isinstance(value, str) or not value:
                continue

            parsed_value = self._parse_datetime(value)
            if parsed_value is None:
                continue

            mapped_values[attribute_uri] = parsed_value.strftime("%Y-%m-%d %H:%M")

    def _build_member_sensor_values(
        self,
        configuration_data: dict,
        mount_action_data: dict,
        cfg_period: tuple[datetime, datetime] | None = None,
    ) -> list[dict[str, str]]:
        included_devices = {
            item["id"]: item
            for item in mount_action_data.get("included", [])
            if item.get("type") == "device"
        }

        sensor_id_prefix = getattr(self, "sensor_id_prefix", self.id_prefix)
        member_sensor_values = []

        mount_actions = self._get_mount_actions(configuration_data, mount_action_data)

        for mount_action in mount_actions:
            if cfg_period is not None and not self._is_mount_action_in_period(mount_action, cfg_period):
                continue

            device_ref = mount_action.get("relationships", {}).get("device", {}).get("data")
            if not device_ref:
                continue

            device = included_devices.get(device_ref["id"])
            if device is None:
                device = self._fetch_device(device_ref["id"])
                if device is None:
                    logger.warning("Mounted device %s could not be resolved", device_ref["id"])
                    continue

            member_sensor_values.append(
                {
                    "text": self._format_sensor_text(device.get("attributes", {})),
                    "external_id": f"{sensor_id_prefix}:{device['id']}",
                }
            )

        return member_sensor_values

    def _format_sensor_text(self, attrs: dict) -> str:
        name = attrs.get("long_name") or attrs.get("short_name", "")
        serial = f" (s/n: {attrs['serial_number']})" if attrs.get("serial_number") else ""
        return f"{name}{serial}"

    def _get_mount_actions(self, configuration_data: dict, mount_action_data: dict) -> list[dict]:
        mount_actions = mount_action_data.get("data", [])
        if mount_actions:
            return mount_actions

        relationship_actions = (
            configuration_data.get("data", {})
            .get("relationships", {})
            .get("device_mount_actions", {})
            .get("data", [])
        )

        resolved_mount_actions = []
        for action_ref in relationship_actions:
            action_id = action_ref.get("id")
            if not action_id:
                continue

            action_data = fetch_json(self.device_mount_action_url.format(base_url=self.base_url, id=action_id))
            if "errors" in action_data:
                logger.warning("Could not fetch mount action %s: %s", action_id, action_data["errors"])
                continue

            action = action_data.get("data")
            if action:
                resolved_mount_actions.append(action)

        return resolved_mount_actions

    def _fetch_device(self, device_id: str) -> dict | None:
        device_data = fetch_json(self.device_url.format(base_url=self.base_url, id=device_id))
        if "errors" in device_data:
            logger.warning("Could not fetch device %s: %s", device_id, device_data["errors"])
            return None
        return device_data.get("data")

    def _get_cfg_period(self, instance) -> tuple[datetime, datetime] | None:
        if instance is None:
            return None

        cfg_start_uri = getattr(self, "cfg_start_uri", None)
        cfg_end_uri = getattr(self, "cfg_end_uri", None)
        if not cfg_start_uri or not cfg_end_uri:
            return None

        cfg_start = self._get_project_value(instance, cfg_start_uri)
        cfg_end = self._get_project_value(instance, cfg_end_uri)
        if cfg_start is None or cfg_end is None:
            return None

        start_dt = self._parse_datetime(cfg_start)
        end_dt = self._parse_datetime(cfg_end)
        if start_dt is None or end_dt is None:
            logger.warning(
                "Skipping configuration period filter because start or end date could not be parsed: %s, %s",
                cfg_start,
                cfg_end,
            )
            return None

        return start_dt, end_dt

    def _get_project_value(self, instance, attribute_uri: str) -> str | None:
        query_variants = [
            {"project": instance.project, "attribute__uri": attribute_uri, "set_prefix": instance.set_prefix, "set_index": instance.set_index},
            {"project": instance.project, "attribute__uri": attribute_uri, "set_prefix": instance.set_prefix},
            {"project": instance.project, "attribute__uri": attribute_uri, "set_index": instance.set_index},
            {"project": instance.project, "attribute__uri": attribute_uri},
        ]

        for filters in query_variants:
            queryset = Value.objects.filter(**filters).order_by("-id")
            value = queryset.first()
            if value is None:
                continue

            if value.text:
                return value.text
            if value.value:
                return value.value

        return None

    def _is_mount_action_in_period(
        self,
        mount_action: dict,
        cfg_period: tuple[datetime, datetime],
    ) -> bool:
        attrs = mount_action.get("attributes", {})
        begin_date = attrs.get("begin_date")
        if not begin_date:
            return False

        mount_start = self._parse_datetime(begin_date)
        if mount_start is None:
            return False

        end_date = attrs.get("end_date")
        if end_date:
            mount_end = self._parse_datetime(end_date)
            if mount_end is None:
                return False
        else:
            mount_end = datetime.max.replace(tzinfo=mount_start.tzinfo)

        cfg_start, cfg_end = cfg_period
        return mount_start <= cfg_end and mount_end >= cfg_start

    def _parse_datetime(self, value: str) -> datetime | None:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
