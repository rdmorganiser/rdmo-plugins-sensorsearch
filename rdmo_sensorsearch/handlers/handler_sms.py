import logging
from datetime import datetime
from datetime import timezone as dt_timezone
from urllib.parse import urljoin, urlsplit

from rdmo.projects.models import Value

from rdmo_sensorsearch.client import fetch_json
from rdmo_sensorsearch.handlers.base import GenericSearchHandler
from rdmo_sensorsearch.handlers.parser import map_jamespath_to_attribute_uri

logger = logging.getLogger(__name__)

DEVICE_COLLECTION_ATTRIBUTE_URI = "https://rdmo-sandbox.gfz-potsdam.de/terms/domain/moses/instruments/id"
DEVICE_LINK_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/device-link"
INSTRUMENT_START_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/instrument-start-datetime"
INSTRUMENT_END_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/instrument-end-datetime"


class SensorManagementSystemHandler(GenericSearchHandler):
    """
    Handles the Sensor Management System (SMS) to gather sensor information.

    This handler fetches device information, including properties, from the
    SMS API.
    """

    # id_prefix = "sms"
    sync_device_detail_blocks = True
    supports_mount_action_period_lookup = True

    # URL templates with placeholders
    device_url = "{base_url}/devices/{id}?include=device_properties"
    contact_url = "{base_url}/devices/{id}/device-contact-roles?include=contact"
    backend_link_marker = "/backend/api/v1/"
    device_link_attribute_uri = DEVICE_LINK_ATTRIBUTE_URI
    uses_auth_token = True

    def handle(self, id_: str, instance=None, auth_token: str | None = None) -> dict:
        """
        Handles post_save for a specific device ID in the SMS.

        Args:
            id_ (str): The ID of the device to get information for.

        Returns:
            dict: A dictionary containing the mapped values from the SMS API
                  response.
        """

        data = fetch_json(self.device_url.format(base_url=self.base_url, id=id_), auth_token=auth_token)

        if isinstance(data, dict) and "errors" in data:
            logger.debug("Errors in data returned for ID %s, %s", id_, ", ".join(data["errors"]))
            return data
        if not isinstance(data, dict):
            return {"errors": [f"Unexpected SMS device payload for device {id_}: {type(data).__name__}"]}
        if not isinstance(data.get("data"), dict):
            return {"errors": [f"SMS device request for device {id_} returned no device data."]}

        # contacts can not be included in the first request with the include parameter
        contact_data = fetch_json(self.contact_url.format(base_url=self.base_url, id=id_), auth_token=auth_token)
        if isinstance(contact_data, dict) and "errors" in contact_data:
            return contact_data
        if not isinstance(contact_data, dict):
            return {"errors": [f"Unexpected SMS contact payload for device {id_}: {type(contact_data).__name__}"]}

        # add the included contact data to the data
        data["included"] = [*data.get("included", []), *contact_data.get("included", [])]

        if not data:
            logger.debug("Empty data returned for ID %s", id_)

        mapped_data = map_jamespath_to_attribute_uri(self.attribute_mapping, data)
        self._set_frontend_device_link(mapped_data, data)
        mount_period_errors = self._set_mount_period(mapped_data, id_, instance, auth_token=auth_token)
        if mount_period_errors:
            return {"errors": mount_period_errors}
        return mapped_data

    def _set_frontend_device_link(self, mapped_data: dict, device_data: dict) -> None:
        raw_self_link = device_data.get("data", {}).get("links", {}).get("self")
        if not isinstance(raw_self_link, str) or not raw_self_link:
            return

        api_link = urljoin(self._base_origin(), raw_self_link)
        device_link_attribute_uri = getattr(self, "device_link_attribute_uri", DEVICE_LINK_ATTRIBUTE_URI)
        if device_link_attribute_uri:
            mapped_data[device_link_attribute_uri] = self._to_frontend_link(api_link)

    def _to_frontend_link(self, api_link: str) -> str:
        backend_link_marker = getattr(self, "backend_link_marker", "/backend/api/v1/")
        if backend_link_marker in api_link:
            return api_link.replace(backend_link_marker, "/", 1)
        return api_link

    def _base_origin(self) -> str:
        parsed = urlsplit(self.base_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _set_mount_period(
        self,
        mapped_data: dict,
        device_id: str,
        instance=None,
        auth_token: str | None = None,
    ) -> list[str]:
        configuration_external_id = self._resolve_configuration_external_id(instance)
        if not configuration_external_id:
            return []

        configuration_id = self._parse_external_id(configuration_external_id)[1]
        if not configuration_id:
            return []

        mount_actions, errors = self._fetch_device_mount_actions(device_id, auth_token=auth_token)
        if errors:
            return errors
        if not mount_actions:
            return []

        matching_actions = []
        for item in mount_actions:
            relationships = item.get("relationships", {})
            config_ref = relationships.get("configuration", {}).get("data", {})
            if config_ref.get("id") != configuration_id:
                continue

            action_device_ref = relationships.get("device", {}).get("data", {})
            if action_device_ref.get("id") != device_id:
                continue

            attrs = item.get("attributes", {})
            begin_date = self._parse_timepoint(attrs.get("begin_date"))
            if begin_date is None:
                continue
            end_date = self._parse_timepoint(attrs.get("end_date"))
            matching_actions.append((begin_date, end_date))

        if not matching_actions:
            return []

        latest_start, latest_end = max(matching_actions, key=lambda item: item[0])
        mapped_data[INSTRUMENT_START_ATTRIBUTE_URI] = self._format_timepoint(latest_start)
        mapped_data[INSTRUMENT_END_ATTRIBUTE_URI] = self._format_timepoint(latest_end) or ""
        return []

    def _resolve_configuration_external_id(self, instance) -> str | None:
        if instance is None or instance.project is None:
            return None

        root_value = (
            Value.objects.filter(
                project=instance.project,
                snapshot=None,
                attribute__uri=DEVICE_COLLECTION_ATTRIBUTE_URI,
                set_prefix=instance.set_prefix or "",
                set_index=instance.set_index,
                set_collection=True,
            )
            .exclude(external_id__isnull=True)
            .exclude(external_id__exact="")
            .order_by("-id")
            .first()
        )
        if root_value is None or not isinstance(root_value.external_id, str):
            return None
        if "||" not in root_value.external_id:
            return None
        configuration_external_id, _ = root_value.external_id.split("||", 1)
        return configuration_external_id or None

    def _fetch_device_mount_actions(
        self,
        device_id: str,
        auth_token: str | None = None,
    ) -> tuple[list[dict], list[str]]:
        url = getattr(
            self,
            "device_mount_actions_url",
            "{base_url}/devices/{id}/device-mount-actions"
            "?page[size]=10000&include=begin_contact,end_contact,parent_platform,parent_device,configuration",
        ).format(base_url=self.base_url, id=device_id)
        action_data = fetch_json(url, auth_token=auth_token)
        if isinstance(action_data, dict) and "errors" in action_data:
            return [], [f"SMS mount action request for device {device_id} failed: {error}" for error in action_data["errors"]]
        if not isinstance(action_data, dict):
            return [], [f"Unexpected SMS mount action payload for device {device_id}: {type(action_data).__name__}"]
        data = action_data.get("data", [])
        if not isinstance(data, list):
            return [], [f"Unexpected SMS mount action data for device {device_id}: {type(data).__name__}"]
        return data, []

    def _parse_external_id(self, external_id: str) -> tuple[str | None, str | None]:
        if ":" not in external_id:
            return None, external_id or None
        prefix, value = external_id.split(":", 1)
        return prefix or None, value or None

    def _parse_timepoint(self, value) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _format_timepoint(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt_timezone.utc)
        return value.astimezone(dt_timezone.utc).strftime("%Y-%m-%d %H:%M")
