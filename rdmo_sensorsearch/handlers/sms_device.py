import logging
from urllib.parse import urljoin, urlsplit

from rdmo.projects.models import Value

from rdmo_sensorsearch.client import fetch_json
from rdmo_sensorsearch.handlers.base import (
    BackendRecordHandler,
    HandlerExecutionContext,
    HandlerResult,
    MergedTextScalar,
)
from rdmo_sensorsearch.handlers.jsonapi import fetch_paginated_jsonapi_collection
from rdmo_sensorsearch.handlers.parser import evaluate_jmespath_mapping
from rdmo_sensorsearch.handlers.sms_mounting import resolve_mount_location, select_latest_device_mount_period
from rdmo_sensorsearch.services.device_detail_profile import DEFAULT_DEVICE_DETAIL_SETTINGS
from rdmo_sensorsearch.services.device_details import parse_external_id
from rdmo_sensorsearch.services.refresh import RefreshNotice

logger = logging.getLogger(__name__)

DEVICE_COLLECTION_ATTRIBUTE_URI = "https://rdmo-sandbox.gfz-potsdam.de/terms/domain/moses/instruments/id"
DEVICE_LINK_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/device-link"
INSTRUMENT_START_ATTRIBUTE_URI = DEFAULT_DEVICE_DETAIL_SETTINGS.instrument_start_attribute_uri
INSTRUMENT_END_ATTRIBUTE_URI = DEFAULT_DEVICE_DETAIL_SETTINGS.instrument_end_attribute_uri
INSTRUMENT_LOCATION_AMSL_ATTRIBUTE_URI = DEFAULT_DEVICE_DETAIL_SETTINGS.instrument_location_amsl_attribute_uri
SURFACE_OFFSET_Z_ATTRIBUTE_URI = DEFAULT_DEVICE_DETAIL_SETTINGS.surface_offset_z_attribute_uri
SITE_NAME_ATTRIBUTE_URI = DEFAULT_DEVICE_DETAIL_SETTINGS.site_name_attribute_uri
OWNER_ORGANIZATIONS_PATH = "sms_owner_organizations"


def extract_owner_organizations(
    payload: dict,
    external_id: str = "",
) -> tuple[tuple[str, ...], tuple[RefreshNotice, ...]]:
    """Join Owner roles to included contacts, independently of array order."""
    contacts = {(item.get("type"), item.get("id")): item for item in payload.get("included", []) if item.get("type") == "contact"}
    names = []
    notices = []
    for role in payload["data"]:
        if role.get("type") != "device_contact_role" or role.get("attributes", {}).get("role_name") != "Owner":
            continue
        relationship = role.get("relationships", {}).get("contact")
        reference = relationship.get("data") if isinstance(relationship, dict) else None
        contact = None
        if isinstance(reference, dict) and reference.get("type") == "contact" and isinstance(reference.get("id"), str):
            contact = contacts.get(("contact", reference["id"]))
        if contact is None:
            notices.append(RefreshNotice("owner_contact_unresolved", external_id, (("role_id", str(role.get("id", ""))),)))
            continue
        organization = contact.get("attributes", {}).get("organization")
        if isinstance(organization, str) and organization.strip():
            name = organization.strip()
            if name not in names:
                names.append(name)
    return tuple(names), tuple(notices)


class SensorManagementSystemDeviceHandler(BackendRecordHandler):
    """
    Synchronizes device information from a Sensor Management System (SMS).

    This handler fetches device information, including properties, from the
    SMS API.
    """

    # id_prefix = "sms"
    materialize_device_details = True
    supports_mount_period_lookup = True
    supports_mount_location_lookup = True

    # URL templates with placeholders
    device_url = "{base_url}/devices/{id}?include=device_properties"
    contact_url = "{base_url}/devices/{id}/device-contact-roles?include=contact&page[size]={page_size}&page[number]={page_number}"
    configuration_device_mount_actions_url = (
        "{base_url}/device-mount-actions?filter[configuration_id]={id}"
        "&page[size]=10000&include=parent_platform,parent_device,configuration"
    )
    configuration_platform_mount_actions_url = "{base_url}/platform-mount-actions?filter[configuration_id]={id}&page[size]=10000"
    configuration_static_location_actions_url = (
        "{base_url}/static-location-actions?filter[configuration_id]={id}&page[size]=10000"
    )
    backend_link_marker = "/backend/api/v1/"
    uses_auth_token = True

    def handle(
        self,
        backend_id: str,
        instance=None,
        auth_token: str | None = None,
        context: HandlerExecutionContext | None = None,
    ) -> dict | HandlerResult:
        """
        Synchronizes one SMS device with its RDMO value.

        Args:
            backend_id (str): The ID of the device to get information for.

        Returns:
            dict: A dictionary containing the mapped values from the SMS API
                  response.
        """

        data = fetch_json(self.device_url.format(base_url=self.base_url, id=backend_id), auth_token=auth_token)

        if isinstance(data, dict) and "errors" in data:
            logger.debug("Errors in data returned for ID %s, %s", backend_id, ", ".join(data["errors"]))
            return data
        if not isinstance(data, dict):
            return {"errors": [f"Unexpected SMS device payload for device {backend_id}: {type(data).__name__}"]}
        if not isinstance(data.get("data"), dict):
            return {"errors": [f"SMS device request for device {backend_id} returned no device data."]}

        # contacts can not be included in the first request with the include parameter
        contact_data = fetch_paginated_jsonapi_collection(
            url_template=self.contact_url,
            base_url=self.base_url,
            object_id=backend_id,
            page_size=100,
            max_pages=100,
            fetch_page=lambda url: self._fetch_contact_page(url, backend_id, auth_token),
            error_label="SMS contact roles",
            next_link_base_url=self.contact_url.format(
                base_url=self.base_url,
                id=backend_id,
                page_size=100,
                page_number=1,
            ),
        )
        if "errors" in contact_data:
            return contact_data

        # add the included contact data to the data
        data["included"] = [*data.get("included", []), *contact_data.get("included", [])]
        external_id = f"{self._id_prefix}:{backend_id}" if self._id_prefix else backend_id
        owner_names, owner_notices = extract_owner_organizations(contact_data, external_id)
        data[OWNER_ORGANIZATIONS_PATH] = list(owner_names)

        if not data:
            logger.debug("Empty data returned for ID %s", backend_id)

        mapped_values = evaluate_jmespath_mapping(self.attribute_mapping, data)
        owner_attribute_uri = self.attribute_mapping.get(OWNER_ORGANIZATIONS_PATH)
        if owner_attribute_uri:
            mapped_values[owner_attribute_uri] = MergedTextScalar(owner_names)
        detail_settings = (context.device_detail_settings if context is not None else None) or DEFAULT_DEVICE_DETAIL_SETTINGS
        self._set_frontend_device_link(
            mapped_values,
            data,
            getattr(self, "device_link_attribute_uri", detail_settings.device_link_attribute_uri),
        )
        notices = list(owner_notices)
        mount_metadata_errors = self._set_mount_metadata(
            mapped_values,
            backend_id,
            instance,
            auth_token=auth_token,
            notice_sink=notices,
            detail_settings=detail_settings,
        )
        if mount_metadata_errors:
            return {"errors": mount_metadata_errors}
        return HandlerResult(mapped_values=mapped_values, notices=tuple(notices))

    def _fetch_contact_page(self, url: str, backend_id: str, auth_token: str | None) -> dict:
        # Follow pagination only on the configured backend, including when a token is used.
        if urlsplit(url)[:2] != urlsplit(self.base_url)[:2]:
            return {"errors": ["SMS contact pagination points to a different backend."]}
        payload = fetch_json(url, auth_token=auth_token)
        if isinstance(payload, dict) and "errors" in payload:
            return payload
        if not isinstance(payload, dict):
            return {"errors": [f"Unexpected SMS contact payload for device {backend_id}: {type(payload).__name__}"]}
        for key in ("data", "included"):
            records = payload.get(key, [] if key == "included" else None)
            if not isinstance(records, list) or any(
                not isinstance(record, dict)
                or not isinstance(record.get("type"), str)
                or not isinstance(record.get("id"), str)
                or not isinstance(record.get("attributes", {}), dict)
                or not isinstance(record.get("relationships", {}), dict)
                for record in records
            ):
                return {"errors": [f"Malformed SMS contact {key} for device {backend_id}."]}
        return payload

    def _set_frontend_device_link(self, mapped_values: dict, device_data: dict, device_link_attribute_uri: str) -> None:
        raw_self_link = device_data.get("data", {}).get("links", {}).get("self")
        if not isinstance(raw_self_link, str) or not raw_self_link:
            return

        api_link = urljoin(self._base_origin(), raw_self_link)
        if device_link_attribute_uri:
            mapped_values[device_link_attribute_uri] = self._to_frontend_link(api_link)

    def _to_frontend_link(self, api_link: str) -> str:
        backend_link_marker = getattr(self, "backend_link_marker", "/backend/api/v1/")
        if backend_link_marker in api_link:
            return api_link.replace(backend_link_marker, "/", 1)
        return api_link

    def _base_origin(self) -> str:
        parsed = urlsplit(self.base_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _set_mount_metadata(
        self,
        mapped_values: dict,
        device_id: str,
        instance=None,
        auth_token: str | None = None,
        notice_sink: list[RefreshNotice] | None = None,
        detail_settings=DEFAULT_DEVICE_DETAIL_SETTINGS,
    ) -> list[str]:
        configuration_external_id = self._resolve_configuration_external_id(instance)
        if not configuration_external_id:
            return []

        configuration_id = parse_external_id(configuration_external_id)[1]
        if not configuration_id:
            return []

        mount_actions, errors = self._fetch_device_mount_actions(device_id, auth_token=auth_token)
        if errors:
            return errors
        if not mount_actions:
            return []

        mount_period = select_latest_device_mount_period(
            mount_actions,
            configuration_id,
            device_id,
        )
        if mount_period is None:
            return []

        start_value, end_value = mount_period.formatted()
        mapped_values[detail_settings.instrument_start_attribute_uri] = start_value
        mapped_values[detail_settings.instrument_end_attribute_uri] = end_value or ""

        configuration_device_actions, errors = self._fetch_configuration_actions(
            self.configuration_device_mount_actions_url,
            configuration_id,
            "device mount",
            auth_token=auth_token,
        )
        if errors:
            return errors
        platform_actions, errors = self._fetch_configuration_actions(
            self.configuration_platform_mount_actions_url,
            configuration_id,
            "platform mount",
            auth_token=auth_token,
        )
        if errors:
            return errors
        static_location_actions, errors = self._fetch_configuration_actions(
            self.configuration_static_location_actions_url,
            configuration_id,
            "static location",
            auth_token=auth_token,
        )
        if errors:
            return errors

        location = resolve_mount_location(
            mount_period.action,
            configuration_device_actions or mount_actions,
            platform_actions,
            static_location_actions,
            static_location_end_tolerance_seconds=getattr(self, "static_location_end_tolerance_seconds", 0),
            incomplete_mount_chain_policy=getattr(self, "incomplete_mount_chain_policy", "strict"),
        )
        if notice_sink is not None:
            notice_sink.extend(location.notices)
        mapped_values[detail_settings.instrument_location_amsl_attribute_uri] = (
            location.station_height_amsl if location.station_height_amsl is not None else ""
        )
        mapped_values[detail_settings.surface_offset_z_attribute_uri] = (
            location.vertical_surface_offset if location.vertical_surface_offset is not None else ""
        )
        mapped_values[detail_settings.site_name_attribute_uri] = location.site_name if location.site_name is not None else ""
        return []

    def _resolve_configuration_external_id(self, instance) -> str | None:
        if instance is None or instance.project is None:
            return None

        root_value = (
            Value.objects.filter(
                project=instance.project,
                snapshot=None,
                attribute__uri=getattr(self, "device_collection_attribute_uri", DEVICE_COLLECTION_ATTRIBUTE_URI),
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

    def _fetch_configuration_actions(
        self,
        url_template: str,
        configuration_id: str,
        action_label: str,
        auth_token: str | None = None,
    ) -> tuple[list[dict], list[str]]:
        url = url_template.format(base_url=self.base_url, id=configuration_id)
        payload = fetch_json(url, auth_token=auth_token)
        if isinstance(payload, dict) and "errors" in payload:
            return [], [
                f"SMS {action_label} request for configuration {configuration_id} failed: {error}" for error in payload["errors"]
            ]
        if not isinstance(payload, dict):
            return [], [f"Unexpected SMS {action_label} payload for configuration {configuration_id}: {type(payload).__name__}"]
        data = payload.get("data", [])
        if not isinstance(data, list):
            return [], [f"Unexpected SMS {action_label} data for configuration {configuration_id}: {type(data).__name__}"]
        return data, []
