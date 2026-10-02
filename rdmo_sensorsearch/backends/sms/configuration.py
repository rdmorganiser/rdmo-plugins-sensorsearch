from functools import partial
from urllib.parse import urljoin, urlsplit

import jmespath
from jmespath.exceptions import JMESPathError

from rdmo_sensorsearch.backends.sms.jsonapi import fetch_paginated_jsonapi_collection
from rdmo_sensorsearch.backends.sms.membership import SMSConfigurationMembershipResolver
from rdmo_sensorsearch.backends.sms.mounting import select_static_location_action
from rdmo_sensorsearch.backends.sms.settings import SMSConfigurationSettings
from rdmo_sensorsearch.backends.sms.transport import JSONFetcher, request_json
from rdmo_sensorsearch.contracts import (
    BackendFailure,
    BackendResult,
    BackendSuccess,
    ConfigurationMembership,
    ConfigurationMetadata,
    ConfigurationPeriod,
    StaticLocation,
)


class SMSConfigurationAPI:
    def __init__(self, settings: SMSConfigurationSettings, fetch: JSONFetcher):
        self.settings = settings
        self.fetch = fetch

    def get_configuration(self, configuration_id: str, *, auth_token: str | None = None) -> BackendResult[ConfigurationMetadata]:
        settings = self.settings
        response = request_json(
            self.fetch, settings.configuration_url.format(base_url=settings.base_url, id=configuration_id), auth_token
        )
        if isinstance(response, BackendFailure):
            return response
        payload = response.value
        if not isinstance(payload, dict):
            return BackendFailure((f"Unexpected SMS configuration payload for ID {configuration_id}: {type(payload).__name__}",))
        if not isinstance(payload.get("data"), dict):
            return BackendFailure((f"SMS configuration request for ID {configuration_id} returned no configuration data.",))
        link = payload["data"].get("links", {}).get("self")
        if (not isinstance(link, str) or not link) and settings.self_link_fallback_enabled:
            try:
                link = jmespath.search(settings.configuration_self_link_path, payload)
            except JMESPathError:
                link = None
        api_link = frontend_link = None
        if isinstance(link, str) and link:
            origin = urlsplit(settings.base_url)
            api_link = urljoin(f"{origin.scheme}://{origin.netloc}", link)
            frontend_link = api_link.replace(settings.backend_link_marker, "/", 1)
            suffix = settings.frontend_link_suffix
            if suffix and not frontend_link.endswith(suffix):
                frontend_link = f"{frontend_link.rstrip('/')}{suffix}"
        return BackendSuccess(ConfigurationMetadata(payload, api_link, frontend_link, configuration_id))

    def get_configuration_members(
        self, configuration: ConfigurationMetadata, *, period: ConfigurationPeriod | None = None, auth_token: str | None = None
    ) -> BackendResult[ConfigurationMembership]:
        settings = self.settings
        identifier = configuration.identifier or configuration.document["data"].get("id")
        devices = self._collection(
            settings.device_mount_actions_url, identifier, settings.device_mount_action_page_size, auth_token
        )
        if isinstance(devices, BackendFailure):
            return devices
        platforms = self._collection(
            settings.platform_mount_actions_url, identifier, settings.platform_mount_action_page_size, auth_token
        )
        if isinstance(platforms, BackendFailure):
            return platforms
        locations = self._locations(identifier, auth_token)
        if isinstance(locations, BackendFailure):
            return locations
        resolver = SMSConfigurationMembershipResolver(
            fetch_device=partial(self._device, auth_token=auth_token),
            fetch_mount_action=partial(self._mount_action, auth_token=auth_token),
            static_location_end_tolerance_seconds=settings.static_location_end_tolerance_seconds,
            incomplete_mount_chain_policy=settings.incomplete_mount_chain_policy,
        )
        members = resolver.resolve(
            configuration_data=configuration.document,
            mount_action_data=devices.value,
            platform_mount_action_data=platforms.value,
            static_location_action_data=locations.value,
            configuration_period=period,
        )
        if isinstance(members, BackendFailure):
            return members
        return BackendSuccess(ConfigurationMembership(members.value, self._static_location(locations.value)))

    def get_static_location(
        self, configuration_id: str, *, auth_token: str | None = None
    ) -> BackendResult[StaticLocation | None]:
        locations = self._locations(configuration_id, auth_token)
        if isinstance(locations, BackendFailure):
            return locations
        return BackendSuccess(self._static_location(locations.value))

    def _locations(self, identifier: str, auth_token: str | None) -> BackendResult[dict]:
        settings = self.settings
        response = self._collection(
            settings.static_location_actions_url, identifier, settings.static_location_action_page_size, auth_token
        )
        if isinstance(response, BackendFailure):
            return BackendFailure(
                tuple(f"SMS static location request for configuration {identifier} failed: {error}" for error in response.errors)
            )
        return response

    @staticmethod
    def _static_location(document: dict) -> StaticLocation | None:
        action = select_static_location_action(document.get("data", []))
        if action is None:
            return None
        attributes = action.get("attributes", {})
        latitude, longitude = attributes.get("y"), attributes.get("x")
        return StaticLocation(latitude, longitude) if latitude is not None and longitude is not None else None

    def _collection(self, template: str, identifier: str, page_size: int, auth_token: str | None) -> BackendResult[dict]:
        settings = self.settings
        origin = urlsplit(settings.base_url)
        return fetch_paginated_jsonapi_collection(
            url_template=template,
            base_url=settings.base_url,
            object_id=identifier,
            page_size=page_size,
            max_pages=settings.max_collection_pages,
            fetch_page=lambda url: request_json(self.fetch, url, auth_token),
            error_label="SMS",
            next_link_base_url=f"{origin.scheme}://{origin.netloc}",
        )

    def _mount_action(self, action_id: str, auth_token: str | None) -> BackendResult[dict | None]:
        settings = self.settings
        response = request_json(
            self.fetch, settings.device_mount_action_url.format(base_url=settings.base_url, id=action_id), auth_token
        )
        if isinstance(response, BackendFailure):
            return BackendFailure(
                tuple(f"SMS mount action request for action {action_id} failed: {error}" for error in response.errors)
            )
        payload = response.value
        if not isinstance(payload, dict):
            return BackendFailure((f"Unexpected SMS mount action payload for action {action_id}: {type(payload).__name__}",))
        action = payload.get("data")
        return BackendSuccess(action if isinstance(action, dict) else None)

    def _device(self, device_id: str, auth_token: str | None) -> BackendResult[dict | None]:
        settings = self.settings
        response = request_json(self.fetch, settings.device_url.format(base_url=settings.base_url, id=device_id), auth_token)
        if isinstance(response, BackendFailure):
            return BackendFailure(
                tuple(f"SMS device request for mounted device {device_id} failed: {error}" for error in response.errors)
            )
        payload = response.value
        if not isinstance(payload, dict):
            return BackendFailure((f"Unexpected SMS device payload for mounted device {device_id}: {type(payload).__name__}",))
        device = payload.get("data")
        if not isinstance(device, dict):
            return BackendFailure((f"Unexpected SMS device data for mounted device {device_id}: {type(device).__name__}",))
        return BackendSuccess(device)
