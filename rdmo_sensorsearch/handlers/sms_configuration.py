import logging
from datetime import timezone as dt_timezone
from functools import partial
from urllib.parse import urljoin

from django.utils import timezone as django_timezone

from rdmo_sensorsearch.client import fetch_json
from rdmo_sensorsearch.handlers.base import (
    BackendRecordHandler,
    CollectionAssignment,
    HandlerExecutionContext,
    HandlerResult,
)
from rdmo_sensorsearch.handlers.configuration_period import (
    ConfigurationPeriod,
    catalog_has_date_range_trigger,
    read_configuration_period,
)
from rdmo_sensorsearch.handlers.jsonapi import fetch_paginated_jsonapi_collection
from rdmo_sensorsearch.handlers.parser import evaluate_jmespath_mapping, parse_datetime
from rdmo_sensorsearch.handlers.sms_configuration_membership import SMSConfigurationMembershipResolver
from rdmo_sensorsearch.handlers.sms_mounting import select_static_location_action
from rdmo_sensorsearch.services.device_details import SelectedDevice
from rdmo_sensorsearch.workflows.device_details import reconcile_device_details_from_selected_devices

logger = logging.getLogger(__name__)


class SensorManagementSystemConfigurationHandler(BackendRecordHandler):
    """
    Resolves one SMS configuration and materializes its mounted devices.
    """

    configuration_url = "{base_url}/configurations/{id}"
    device_url = "{base_url}/devices/{id}"
    device_mount_action_url = "{base_url}/device-mount-actions/{id}"
    device_mount_actions_url = (
        "{base_url}/device-mount-actions?filter[configuration_id]={id}&include=device"
        "&page[size]={page_size}&page[number]={page_number}"
    )
    platform_mount_actions_url = (
        "{base_url}/platform-mount-actions?filter[configuration_id]={id}&page[size]={page_size}&page[number]={page_number}"
    )
    mounting_action_timepoints_url = "{base_url}/configurations/{id}/mounting-action-timepoints"
    static_location_actions_url = (
        "{base_url}/static-location-actions?filter[configuration_id]={id}&page[size]={page_size}&page[number]={page_number}"
    )
    device_mount_action_page_size = 100
    platform_mount_action_page_size = 100
    static_location_action_page_size = 100
    max_collection_pages = 1000
    configuration_self_link_path = "data.links.self"
    configuration_start_date_path = "data.attributes.start_date"
    configuration_end_date_path = "data.attributes.end_date"
    frontend_link_suffix = None  # redirects to "/basic"
    backend_link_marker = "/backend/api/v1/"
    uses_auth_token = True

    def handle(
        self,
        backend_id: str,
        instance=None,
        auth_token: str | None = None,
        context: HandlerExecutionContext | None = None,
    ) -> dict | HandlerResult:
        configuration_data = fetch_json(
            self.configuration_url.format(base_url=self.base_url, id=backend_id),
            auth_token=auth_token,
        )
        logger.debug(
            "Fetched SMS configuration payload for ID %s with top-level keys: %s",
            backend_id,
            sorted(configuration_data.keys()) if isinstance(configuration_data, dict) else type(configuration_data),
        )
        if isinstance(configuration_data, dict) and "errors" in configuration_data:
            logger.debug("Errors in configuration data returned for ID %s: %s", backend_id, configuration_data["errors"])
            return configuration_data
        if not isinstance(configuration_data, dict):
            return {"errors": [f"Unexpected SMS configuration payload for ID {backend_id}: {type(configuration_data).__name__}"]}
        if not isinstance(configuration_data.get("data"), dict):
            return {"errors": [f"SMS configuration request for ID {backend_id} returned no configuration data."]}

        selected_devices_attribute_uri = getattr(self, "selected_devices_attribute_uri", None)
        preserve_existing_collections = bool(context and context.preserve_existing_collections)
        require_configuration_period = bool(context and context.require_configuration_period)
        period_start_attribute_uri = getattr(self, "period_start_attribute_uri", None)
        period_end_attribute_uri = getattr(self, "period_end_attribute_uri", None)
        use_configuration_period = require_configuration_period or (
            instance is not None and catalog_has_date_range_trigger(instance)
        )
        period_inputs_are_configured = instance is not None and bool(period_start_attribute_uri and period_end_attribute_uri)

        configuration_period = None
        period_error = None
        if use_configuration_period and not period_inputs_are_configured:
            period_error = "The configuration or mission date-range inputs are not configured for this catalog."
        elif use_configuration_period:
            configuration_period, period_error = read_configuration_period(
                instance,
                period_start_attribute_uri,
                period_end_attribute_uri,
            )
        if require_configuration_period and period_error:
            return {"errors": [period_error]}

        defer_member_collection = bool(
            selected_devices_attribute_uri and not preserve_existing_collections and use_configuration_period and period_error
        )
        if defer_member_collection:
            logger.info(
                "Deferring SMS device assignments for configuration %s until its date range is applied: %s",
                backend_id,
                period_error,
            )

        mount_action_data = None
        platform_mount_action_data = None
        if selected_devices_attribute_uri and not preserve_existing_collections and not defer_member_collection:
            mount_action_data = self._fetch_jsonapi_collection(
                self.device_mount_actions_url,
                backend_id,
                self.device_mount_action_page_size,
                auth_token=auth_token,
            )
            if "errors" in mount_action_data:
                logger.debug(
                    "Errors in device mount action data returned for ID %s: %s",
                    backend_id,
                    mount_action_data["errors"],
                )
                return mount_action_data

            platform_mount_action_data = self._fetch_jsonapi_collection(
                self.platform_mount_actions_url,
                backend_id,
                self.platform_mount_action_page_size,
                auth_token=auth_token,
            )
            if "errors" in platform_mount_action_data:
                logger.debug(
                    "Errors in platform mount action data returned for ID %s: %s",
                    backend_id,
                    platform_mount_action_data["errors"],
                )
                return platform_mount_action_data

        needs_configuration_location = any(
            getattr(self, attribute_name, None)
            for attribute_name in (
                "location_attribute_uri",
                "latitude_attribute_uri",
                "longitude_attribute_uri",
            )
        )
        location_actions_data = None
        if needs_configuration_location or mount_action_data is not None:
            location_actions_data = self._fetch_jsonapi_collection(
                self.static_location_actions_url,
                backend_id,
                self.static_location_action_page_size,
                auth_token=auth_token,
            )
            if "errors" in location_actions_data:
                return {
                    "errors": [
                        f"SMS static location request for configuration {backend_id} failed: {error}"
                        for error in location_actions_data["errors"]
                    ]
                }

        mapped_values = evaluate_jmespath_mapping(self.attribute_mapping, configuration_data)
        if period_start_attribute_uri:
            mapped_values.pop(period_start_attribute_uri, None)
        if period_end_attribute_uri:
            mapped_values.pop(period_end_attribute_uri, None)
        self._set_configuration_links(mapped_values, configuration_data)
        self._normalize_configuration_datetimes(mapped_values)
        location_errors = self._set_configuration_location(
            mapped_values,
            backend_id,
            auth_token=auth_token,
            location_actions_data=location_actions_data,
        )
        if location_errors:
            return {"errors": location_errors}

        collections = []
        post_actions = []

        if defer_member_collection:
            collections.append(
                CollectionAssignment(
                    attribute_uri=selected_devices_attribute_uri,
                    page_uri=self.selected_devices_page_uri,
                    values=(),
                )
            )

        if selected_devices_attribute_uri and mount_action_data is not None:
            selected_device_values, member_errors = self._build_selected_device_values(
                configuration_data=configuration_data,
                mount_action_data=mount_action_data,
                platform_mount_action_data=platform_mount_action_data,
                static_location_action_data=location_actions_data,
                configuration_period=configuration_period,
                auth_token=auth_token,
            )
            if member_errors:
                return {"errors": member_errors}
            collections.append(
                CollectionAssignment(
                    attribute_uri=selected_devices_attribute_uri,
                    page_uri=self.selected_devices_page_uri,
                    values=tuple(selected_device_values),
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
                        station_height_amsl=value.get("station_height_amsl"),
                        vertical_surface_offset=value.get("vertical_surface_offset"),
                        site_name=value.get("site_name"),
                        mount_location_resolved=True,
                    )
                    for value in selected_device_values
                    if value.get("external_id")
                ]
                post_actions.append(
                    partial(
                        reconcile_device_details_from_selected_devices,
                        project=instance.project,
                        catalog=instance.project.catalog,
                        scope_prefix=instance.set_prefix,
                        source_set_index=instance.set_index,
                        selected_devices=selected_devices,
                        selected_devices_attribute_uri=selected_devices_attribute_uri,
                        device_collection_attribute_uri=device_collection_attribute_uri,
                        configuration_search_attribute_uri=instance.attribute.uri,
                        configuration_external_id=instance.external_id,
                        auth_token=auth_token,
                        force_refresh=True,
                    )
                )

        return HandlerResult(
            mapped_values=mapped_values,
            collections=tuple(collections),
            post_actions=tuple(post_actions),
        )

    def _set_configuration_links(self, mapped_values: dict[str, str | None], configuration_data: dict) -> None:
        raw_self_link = self._get_configuration_self_link(configuration_data)
        if not raw_self_link:
            return

        api_link = urljoin(self.base_url_origin, raw_self_link)

        api_attribute_uri = getattr(self, "api_link_attribute_uri", None)
        if api_attribute_uri:
            mapped_values[api_attribute_uri] = api_link

        frontend_attribute_uri = getattr(self, "frontend_link_attribute_uri", None)
        if frontend_attribute_uri:
            mapped_values[frontend_attribute_uri] = self._to_frontend_link(api_link)

    def _get_configuration_self_link(self, configuration_data: dict) -> str | None:
        direct_self_link = configuration_data.get("data", {}).get("links", {}).get("self")
        if isinstance(direct_self_link, str) and direct_self_link:
            return direct_self_link

        for source_path, attribute_uri in self.attribute_mapping.items():
            if source_path != self.configuration_self_link_path:
                continue
            value = evaluate_jmespath_mapping({source_path: attribute_uri}, configuration_data).get(attribute_uri)
            if isinstance(value, str) and value:
                return value
        return None

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

            parsed_value = parse_datetime(value)
            if parsed_value is None:
                continue

            if django_timezone.is_aware(parsed_value):
                utc_value = parsed_value.astimezone(dt_timezone.utc)
            else:
                utc_value = django_timezone.make_aware(parsed_value, dt_timezone.utc)

            mapped_values[attribute_uri] = utc_value.strftime("%Y-%m-%d %H:%M")

    def _set_configuration_location(
        self,
        mapped_values: dict[str, str | None],
        configuration_id: str,
        auth_token: str | None = None,
        location_actions_data: dict | None = None,
    ) -> list[str]:
        location_attribute_uri = getattr(self, "location_attribute_uri", None)
        latitude_attribute_uri = getattr(self, "latitude_attribute_uri", None)
        longitude_attribute_uri = getattr(self, "longitude_attribute_uri", None)
        if not any((location_attribute_uri, latitude_attribute_uri, longitude_attribute_uri)):
            return []

        if location_actions_data is None:
            location_actions_data = self._fetch_jsonapi_collection(
                self.static_location_actions_url,
                configuration_id,
                self.static_location_action_page_size,
                auth_token=auth_token,
            )
        if "errors" in location_actions_data:
            return [
                f"SMS static location request for configuration {configuration_id} failed: {error}"
                for error in location_actions_data["errors"]
            ]

        action = select_static_location_action(location_actions_data.get("data", []))
        if action is None:
            return []

        attrs = action.get("attributes", {})
        lat = attrs.get("y")
        lon = attrs.get("x")
        if lat is None or lon is None:
            return []

        if latitude_attribute_uri:
            mapped_values[latitude_attribute_uri] = lat

        if longitude_attribute_uri:
            mapped_values[longitude_attribute_uri] = lon

        if location_attribute_uri:
            mapped_values[location_attribute_uri] = f"({lat},{lon})"
        return []

    def _fetch_jsonapi_collection(
        self,
        url_template: str,
        object_id: str,
        page_size: int,
        auth_token: str | None = None,
    ) -> dict:
        return fetch_paginated_jsonapi_collection(
            url_template=url_template,
            base_url=self.base_url,
            object_id=object_id,
            page_size=page_size,
            max_pages=self.max_collection_pages,
            fetch_page=lambda url: fetch_json(url, auth_token=auth_token),
            error_label="SMS",
            next_link_base_url=self.base_url_origin,
        )

    def _build_selected_device_values(
        self,
        configuration_data: dict,
        mount_action_data: dict,
        platform_mount_action_data: dict | None = None,
        static_location_action_data: dict | None = None,
        configuration_period: ConfigurationPeriod | None = None,
        auth_token: str | None = None,
    ) -> tuple[list[dict[str, object]], list[str]]:
        resolver = SMSConfigurationMembershipResolver(
            configuration_id_prefix=self.id_prefix,
            device_id_prefix=getattr(self, "device_id_prefix", self.id_prefix),
            device_text_prefix=getattr(self, "device_text_prefix", "SMS Sensor"),
            fetch_device=partial(self._fetch_device, auth_token=auth_token),
            fetch_mount_action=partial(self._fetch_mount_action, auth_token=auth_token),
        )
        members, errors = resolver.resolve(
            configuration_data=configuration_data,
            mount_action_data=mount_action_data,
            platform_mount_action_data=platform_mount_action_data,
            static_location_action_data=static_location_action_data,
            configuration_period=configuration_period,
        )
        return [member.as_collection_value() for member in members], list(errors)

    def _fetch_mount_action(
        self,
        action_id: str,
        auth_token: str | None = None,
    ) -> tuple[dict | None, list[str]]:
        action_data = fetch_json(
            self.device_mount_action_url.format(base_url=self.base_url, id=action_id),
            auth_token=auth_token,
        )
        if isinstance(action_data, dict) and "errors" in action_data:
            return None, [f"SMS mount action request for action {action_id} failed: {error}" for error in action_data["errors"]]
        if not isinstance(action_data, dict):
            return None, [f"Unexpected SMS mount action payload for action {action_id}: {type(action_data).__name__}"]
        action = action_data.get("data")
        return (action, []) if isinstance(action, dict) else (None, [])

    def _fetch_device(
        self,
        device_id: str,
        auth_token: str | None = None,
    ) -> tuple[dict | None, list[str]]:
        device_data = fetch_json(self.device_url.format(base_url=self.base_url, id=device_id), auth_token=auth_token)
        if isinstance(device_data, dict) and "errors" in device_data:
            return None, [f"SMS device request for mounted device {device_id} failed: {error}" for error in device_data["errors"]]
        if not isinstance(device_data, dict):
            return None, [f"Unexpected SMS device payload for mounted device {device_id}: {type(device_data).__name__}"]
        device = device_data.get("data")
        if not isinstance(device, dict):
            return None, [f"Unexpected SMS device data for mounted device {device_id}: {type(device).__name__}"]
        return device, []
