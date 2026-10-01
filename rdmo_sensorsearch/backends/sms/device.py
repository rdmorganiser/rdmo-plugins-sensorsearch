from urllib.parse import urljoin, urlsplit

from rdmo_sensorsearch.backends.sms.jsonapi import fetch_paginated_jsonapi_collection
from rdmo_sensorsearch.backends.sms.mounting import (
    resolve_mount_location,
    select_latest_device_mount_action,
    select_latest_device_mount_period,
)
from rdmo_sensorsearch.backends.sms.settings import SMSDeviceSettings
from rdmo_sensorsearch.backends.sms.transport import JSONFetcher, request_json
from rdmo_sensorsearch.contracts import (
    BackendFailure,
    BackendResult,
    BackendSuccess,
    DeviceMetadata,
    MountLocation,
    MountPeriod,
    RefreshNotice,
)

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


class SMSDeviceAPI:
    def __init__(self, settings: SMSDeviceSettings, fetch: JSONFetcher):
        self.settings = settings
        self.fetch = fetch

    def get_device(self, device_id: str, *, auth_token: str | None = None) -> BackendResult[DeviceMetadata]:
        settings = self.settings
        response = request_json(self.fetch, settings.device_url.format(base_url=settings.base_url, id=device_id), auth_token)
        if isinstance(response, BackendFailure):
            return response
        data = response.value
        if not isinstance(data, dict):
            return BackendFailure((f"Unexpected SMS device payload for device {device_id}: {type(data).__name__}",))
        if not isinstance(data.get("data"), dict):
            return BackendFailure((f"SMS device request for device {device_id} returned no device data.",))
        contacts = fetch_paginated_jsonapi_collection(
            url_template=settings.contact_url,
            base_url=settings.base_url,
            object_id=device_id,
            page_size=100,
            max_pages=100,
            fetch_page=lambda url: self._contact_page(url, device_id, auth_token),
            error_label="SMS contact roles",
            next_link_base_url=settings.contact_url.format(
                base_url=settings.base_url, id=device_id, page_size=100, page_number=1
            ),
        )
        if isinstance(contacts, BackendFailure):
            return contacts
        data["included"] = [*data.get("included", []), *contacts.value.get("included", [])]
        names, notices = extract_owner_organizations(contacts.value)
        data[OWNER_ORGANIZATIONS_PATH] = list(names)
        link = data["data"].get("links", {}).get("self")
        frontend_link = None
        if isinstance(link, str) and link:
            parsed = urlsplit(settings.base_url)
            api_link = urljoin(f"{parsed.scheme}://{parsed.netloc}", link)
            frontend_link = api_link.replace(settings.backend_link_marker, "/", 1)
        return BackendSuccess(DeviceMetadata(data, names, frontend_link), notices)

    def _contact_page(self, url: str, device_id: str, auth_token: str | None) -> BackendResult[dict]:
        if urlsplit(url)[:2] != urlsplit(self.settings.base_url)[:2]:
            return BackendFailure(("SMS contact pagination points to a different backend.",))
        response = request_json(self.fetch, url, auth_token)
        if isinstance(response, BackendFailure):
            return response
        payload = response.value
        if not isinstance(payload, dict):
            return BackendFailure((f"Unexpected SMS contact payload for device {device_id}: {type(payload).__name__}",))
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
                return BackendFailure((f"Malformed SMS contact {key} for device {device_id}.",))
        return BackendSuccess(payload)

    def get_mount_period(
        self, device_id: str, configuration_id: str, *, serial_number: str | None = None, auth_token: str | None = None
    ) -> BackendResult[MountPeriod | None]:
        settings = self.settings
        actions = self._actions(settings.device_mount_actions_url, device_id, "device", "mount action", auth_token)
        if isinstance(actions, BackendFailure):
            return actions
        period = select_latest_device_mount_period(actions.value, configuration_id, device_id, serial_number=serial_number)
        if period is None:
            return BackendSuccess(None)
        start, end = period.formatted()
        return BackendSuccess(MountPeriod(start, end, period.action, tuple(actions.value)))

    def get_mount_location(
        self, device_id: str, configuration_id: str, *, period: MountPeriod | None = None, auth_token: str | None = None
    ) -> BackendResult[MountLocation | None]:
        settings = self.settings
        devices = self._actions(
            settings.configuration_device_mount_actions_url, configuration_id, "configuration", "device mount", auth_token
        )
        if isinstance(devices, BackendFailure):
            return devices
        action = (
            period.action if period is not None else select_latest_device_mount_action(devices.value, configuration_id, device_id)
        )
        if action is None:
            return BackendSuccess(None)
        platforms = self._actions(
            settings.configuration_platform_mount_actions_url, configuration_id, "configuration", "platform mount", auth_token
        )
        if isinstance(platforms, BackendFailure):
            return platforms
        locations = self._actions(
            settings.configuration_static_location_actions_url, configuration_id, "configuration", "static location", auth_token
        )
        if isinstance(locations, BackendFailure):
            return locations
        location = resolve_mount_location(
            action,
            devices.value or (list(period.device_actions) if period is not None else []),
            platforms.value,
            locations.value,
            static_location_end_tolerance_seconds=settings.static_location_end_tolerance_seconds,
            incomplete_mount_chain_policy=settings.incomplete_mount_chain_policy,
        )
        return BackendSuccess(
            MountLocation(location.station_height_amsl, location.vertical_surface_offset, location.site_name), location.notices
        )

    def _actions(
        self, template: str, identifier: str, entity: str, label: str, auth_token: str | None
    ) -> BackendResult[list[dict]]:
        response = request_json(self.fetch, template.format(base_url=self.settings.base_url, id=identifier), auth_token)
        if isinstance(response, BackendFailure):
            return BackendFailure(
                tuple(f"SMS {label} request for {entity} {identifier} failed: {error}" for error in response.errors)
            )
        payload = response.value
        if not isinstance(payload, dict):
            return BackendFailure((f"Unexpected SMS {label} payload for {entity} {identifier}: {type(payload).__name__}",))
        data = payload.get("data", [])
        if not isinstance(data, list):
            return BackendFailure((f"Unexpected SMS {label} data for {entity} {identifier}: {type(data).__name__}",))
        return BackendSuccess(data)
