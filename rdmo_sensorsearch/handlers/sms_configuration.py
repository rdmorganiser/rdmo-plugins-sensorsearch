import logging
from datetime import datetime
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
from rdmo_sensorsearch.handlers.parser import evaluate_jmespath_mapping, parse_datetime
from rdmo_sensorsearch.handlers.sms_mounting import resolve_mount_location
from rdmo_sensorsearch.naming import configuration_short_label
from rdmo_sensorsearch.signals.device_detail_sync import (
    SelectedDevice,
    reconcile_device_details_from_selected_devices,
)

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
                        height_amsl=value.get("height_amsl"),
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

        action = self._select_best_static_location_action(location_actions_data.get("data", []))
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
        data: list[dict] = []
        included: dict[tuple[str | None, str | None], dict] = {}
        seen_pages: set[tuple[tuple[str | None, str | None], ...]] = set()
        page_number = 1
        pages_fetched = 0
        next_url = url_template.format(
            base_url=self.base_url,
            id=object_id,
            page_size=page_size,
            page_number=page_number,
        )

        while next_url and pages_fetched < self.max_collection_pages:
            pages_fetched += 1
            payload = fetch_json(next_url, auth_token=auth_token)
            if isinstance(payload, dict) and "errors" in payload:
                return payload
            if not isinstance(payload, dict):
                return {"errors": [f"Unexpected SMS collection payload: {type(payload).__name__}"]}

            page_data = payload.get("data", [])
            if not isinstance(page_data, list):
                return {"errors": [f"Unexpected SMS collection data: {type(page_data).__name__}"]}

            signature = tuple((item.get("type"), item.get("id")) for item in page_data)
            if page_data and signature in seen_pages:
                return {"errors": ["SMS collection pagination returned the same page more than once."]}
            seen_pages.add(signature)
            data.extend(page_data)

            page_included = payload.get("included", [])
            if not isinstance(page_included, list):
                return {"errors": [f"Unexpected SMS included data: {type(page_included).__name__}"]}
            for item in page_included:
                included[(item.get("type"), item.get("id"))] = item

            links = payload.get("links", {})
            raw_next = links.get("next") if isinstance(links, dict) else None
            if isinstance(raw_next, dict):
                raw_next = raw_next.get("href")
            if isinstance(raw_next, str) and raw_next:
                next_url = urljoin(self.base_url_origin, raw_next)
            elif len(page_data) >= page_size:
                page_number = pages_fetched + 1
                next_url = url_template.format(
                    base_url=self.base_url,
                    id=object_id,
                    page_size=page_size,
                    page_number=page_number,
                )
            else:
                next_url = None

        if next_url:
            return {"errors": [f"SMS collection pagination exceeded {self.max_collection_pages} pages."]}
        return {"data": data, "included": list(included.values())}

    def _select_best_static_location_action(self, actions: list[dict]) -> dict | None:
        if not actions:
            return None

        def parse_begin_timestamp(action: dict) -> float:
            begin_raw = action.get("attributes", {}).get("begin_date")
            parsed = parse_datetime(begin_raw) if begin_raw else None
            if parsed is None:
                return float("-inf")
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt_timezone.utc)
            return parsed.timestamp()

        active_actions = [action for action in actions if not action.get("attributes", {}).get("end_date")]
        if active_actions:
            return max(active_actions, key=parse_begin_timestamp)
        return max(actions, key=parse_begin_timestamp)

    def _build_selected_device_values(
        self,
        configuration_data: dict,
        mount_action_data: dict,
        platform_mount_action_data: dict | None = None,
        static_location_action_data: dict | None = None,
        configuration_period: ConfigurationPeriod | None = None,
        auth_token: str | None = None,
    ) -> tuple[list[dict[str, object]], list[str]]:
        included_devices = {item["id"]: item for item in mount_action_data.get("included", []) if item.get("type") == "device"}

        device_id_prefix = getattr(self, "device_id_prefix", self.id_prefix)
        selected_device_values = []

        mount_actions, errors = self._get_mount_actions(
            configuration_data,
            mount_action_data,
            auth_token=auth_token,
        )
        if errors:
            return [], errors

        platform_mount_actions = (
            platform_mount_action_data.get("data", []) if isinstance(platform_mount_action_data, dict) else []
        )
        static_location_actions = (
            static_location_action_data.get("data", []) if isinstance(static_location_action_data, dict) else []
        )

        selected_mount_actions = self._select_member_mount_actions(mount_actions, configuration_period)
        reference_time = configuration_period.end if configuration_period is not None else None
        for mount_action in selected_mount_actions:
            device_ref = mount_action.get("relationships", {}).get("device", {}).get("data")
            if not device_ref:
                continue

            device = included_devices.get(device_ref["id"])
            if device is None:
                device, device_errors = self._fetch_device(device_ref["id"], auth_token=auth_token)
                if device_errors:
                    errors.extend(device_errors)
                    continue

            attrs = mount_action.get("attributes", {})
            mount_location = resolve_mount_location(
                mount_action,
                mount_actions,
                platform_mount_actions,
                static_location_actions,
                reference_time=reference_time,
            )
            selected_device_values.append(
                {
                    "text": self._format_device_text(
                        configuration_id=configuration_data.get("data", {}).get("id"),
                        device_id=device["id"],
                        attrs=device.get("attributes", {}),
                    ),
                    "external_id": f"{device_id_prefix}:{device['id']}",
                    "instrument_start": self._format_mount_timepoint(attrs.get("begin_date")),
                    "instrument_end": self._format_mount_timepoint(attrs.get("end_date")),
                    "height_amsl": mount_location.height_amsl,
                    "vertical_surface_offset": mount_location.vertical_surface_offset,
                    "site_name": mount_location.site_name,
                }
            )

        return selected_device_values, errors

    def _format_device_text(
        self,
        configuration_id: str | None,
        device_id: str,
        attrs: dict,
    ) -> str:
        name = attrs.get("long_name") or attrs.get("short_name", "")
        serial = f" (s/n: {attrs['serial_number']})" if attrs.get("serial_number") else ""
        device_text_prefix = getattr(self, "device_text_prefix", "SMS Sensor")
        configuration_label = configuration_short_label(f"{self.id_prefix}:{configuration_id}") if configuration_id else None
        configuration_prefix = f"{configuration_label} " if configuration_label else ""
        return f"{configuration_prefix}{device_text_prefix}({device_id}): {name}{serial}"

    def _format_mount_timepoint(self, value) -> str | None:
        parsed = parse_datetime(value) if value else None
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_timezone.utc)
        return parsed.astimezone(dt_timezone.utc).strftime("%Y-%m-%d %H:%M")

    def _get_mount_actions(
        self,
        configuration_data: dict,
        mount_action_data: dict,
        auth_token: str | None = None,
    ) -> tuple[list[dict], list[str]]:
        mount_actions = mount_action_data.get("data", [])
        if mount_actions:
            return mount_actions, []

        relationship_actions = (
            configuration_data.get("data", {}).get("relationships", {}).get("device_mount_actions", {}).get("data", [])
        )

        resolved_mount_actions = []
        errors = []
        for action_ref in relationship_actions:
            action_id = action_ref.get("id")
            if not action_id:
                continue

            action_data = fetch_json(
                self.device_mount_action_url.format(base_url=self.base_url, id=action_id),
                auth_token=auth_token,
            )
            if isinstance(action_data, dict) and "errors" in action_data:
                errors.extend(
                    f"SMS mount action request for action {action_id} failed: {error}" for error in action_data["errors"]
                )
                continue
            if not isinstance(action_data, dict):
                errors.append(f"Unexpected SMS mount action payload for action {action_id}: {type(action_data).__name__}")
                continue

            action = action_data.get("data")
            if action:
                resolved_mount_actions.append(action)

        return resolved_mount_actions, errors

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

    def _parse_configuration_timepoint(self, value: str | None) -> datetime | None:
        if value is None:
            return None
        parsed = parse_datetime(value)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=dt_timezone.utc)
        return parsed.astimezone(dt_timezone.utc)

    def _select_member_mount_actions(
        self,
        mount_actions: list[dict],
        configuration_period: ConfigurationPeriod | None,
    ) -> list[dict]:
        selected_by_device: dict[str, dict] = {}
        for mount_action in mount_actions:
            if configuration_period is not None and not self._is_mount_action_in_period(mount_action, configuration_period):
                continue

            device_ref = mount_action.get("relationships", {}).get("device", {}).get("data")
            if not isinstance(device_ref, dict) or not isinstance(device_ref.get("id"), str):
                continue
            device_id = device_ref["id"]
            selected = selected_by_device.get(device_id)
            if selected is None or self._mount_action_begin_sort_key(mount_action) > self._mount_action_begin_sort_key(selected):
                selected_by_device[device_id] = mount_action
        return list(selected_by_device.values())

    def _mount_action_begin_sort_key(self, mount_action: dict) -> float:
        parsed = self._parse_configuration_timepoint(mount_action.get("attributes", {}).get("begin_date"))
        return parsed.timestamp() if parsed is not None else float("-inf")

    def _is_mount_action_in_period(
        self,
        mount_action: dict,
        configuration_period: ConfigurationPeriod,
    ) -> bool:
        attrs = mount_action.get("attributes", {})
        begin_date = attrs.get("begin_date")
        if not begin_date:
            return False

        mount_start = self._parse_configuration_timepoint(begin_date)
        if mount_start is None:
            return False

        end_date = attrs.get("end_date")
        if end_date:
            mount_end = self._parse_configuration_timepoint(end_date)
            if mount_end is None:
                return False
        else:
            mount_end = None

        if configuration_period.end is not None and mount_start > configuration_period.end:
            return False
        return mount_end is None or mount_end > configuration_period.start
