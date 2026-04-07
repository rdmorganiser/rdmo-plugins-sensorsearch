import logging

from rdmo_sensorsearch.client import fetch_json
from rdmo_sensorsearch.handlers.base import CollectionAssignment, GenericSearchHandler, HandlerResult
from rdmo_sensorsearch.handlers.parser import map_jamespath_to_attribute_uri

logger = logging.getLogger(__name__)


class SensorManagementSystemConfigurationsHandler(GenericSearchHandler):
    """
    Resolves one SMS configuration and materializes its mounted devices.
    """

    configuration_url = "{base_url}/configurations/{id}"
    device_mount_actions_url = (
        "{base_url}/device-mount-actions?filter[configuration_id]={id}&include=device&page[size]={page_size}"
    )
    mounted_sensor_max_hits = 100

    def handle(self, id_: str) -> dict | HandlerResult:
        configuration_data = fetch_json(self.configuration_url.format(base_url=self.base_url, id=id_))
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

        result = HandlerResult(
            mapped_values=map_jamespath_to_attribute_uri(self.attribute_mapping, configuration_data),
            collections=[],
        )

        if getattr(self, "member_sensors_attribute_uri", None):
            result.collections.append(
                CollectionAssignment(
                    attribute_uri=self.member_sensors_attribute_uri,
                    values=self._build_member_sensor_values(mount_action_data),
                )
            )

        return result

    def _build_member_sensor_values(self, mount_action_data: dict) -> list[dict[str, str]]:
        included_devices = {
            item["id"]: item
            for item in mount_action_data.get("included", [])
            if item.get("type") == "device"
        }

        sensor_id_prefix = getattr(self, "sensor_id_prefix", self.id_prefix)
        member_sensor_values = []

        for mount_action in mount_action_data.get("data", []):
            device_ref = mount_action.get("relationships", {}).get("device", {}).get("data")
            if not device_ref:
                continue

            device = included_devices.get(device_ref["id"])
            if device is None:
                logger.warning("Mounted device %s not found in included data", device_ref["id"])
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
