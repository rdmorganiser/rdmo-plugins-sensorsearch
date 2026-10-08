import logging
from collections.abc import Mapping
from datetime import timezone as dt_timezone

from rdmo_sensorsearch.contracts import (
    BackendFailure,
    CollectionAssignment,
    ConfigurationMember,
    ConfigurationSource,
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


class SensorManagementSystemConfigurationHandler(BackendRecordHandler):
    """
    Resolves one SMS configuration and materializes its mounted devices.
    """

    configuration_start_date_path = "data.attributes.start_date"
    configuration_end_date_path = "data.attributes.end_date"
    uses_auth_token = True

    def __init__(self, *, backend: ConfigurationSource, id_prefix: str, base_url: str, attribute_mapping: Mapping[str, str]):
        super().__init__(id_prefix=id_prefix, base_url=base_url, attribute_mapping=attribute_mapping)
        self.backend = backend

    def handle(
        self,
        backend_id: str,
        *,
        auth_token: str | None = None,
        context: HandlerExecutionContext,
    ) -> HandlerOutcome:
        response = self.backend.get_configuration(backend_id, auth_token=auth_token)
        if isinstance(response, BackendFailure):
            return HandlerFailure(tuple(response.errors))
        configuration = response.value
        configuration_data = configuration.document

        selected_devices_attribute_uri = getattr(self, "selected_devices_attribute_uri", None)
        preserve_existing_collections = bool(context and context.preserve_existing_collections)
        require_configuration_period = bool(context and context.require_configuration_period)
        membership_filter_enabled = bool(getattr(self, "membership_filter_enabled", False))
        filter_start_attribute_uri = getattr(self, "membership_filter_start_attribute_uri", None)
        filter_end_attribute_uri = getattr(self, "membership_filter_end_attribute_uri", None)

        configuration_period = None
        if require_configuration_period and not membership_filter_enabled:
            return HandlerFailure(("SMS membership filtering is not enabled for this catalog.",))
        if require_configuration_period and (not filter_start_attribute_uri or not filter_end_attribute_uri):
            return HandlerFailure(("The SMS membership filter inputs are not configured for this catalog.",))
        if require_configuration_period:
            configuration_period = context.configuration_period
            if configuration_period is None:
                return HandlerFailure(("A validated configuration period is required for SMS membership filtering.",))

        membership = None
        if selected_devices_attribute_uri and not preserve_existing_collections:
            members = self.backend.get_configuration_members(configuration, period=configuration_period, auth_token=auth_token)
            if isinstance(members, BackendFailure):
                return HandlerFailure(tuple(members.errors))
            membership = members.value
        needs_configuration_location = any(
            getattr(self, name, None) for name in ("location_attribute_uri", "latitude_attribute_uri", "longitude_attribute_uri")
        )
        location = membership.static_location if membership is not None else None
        if needs_configuration_location and membership is None:
            locations = self.backend.get_static_location(backend_id, auth_token=auth_token)
            if isinstance(locations, BackendFailure):
                return HandlerFailure(tuple(locations.errors))
            location = locations.value

        mapped_values = evaluate_jmespath_mapping(self.attribute_mapping, configuration_data)
        if filter_start_attribute_uri:
            mapped_values.pop(filter_start_attribute_uri, None)
        if filter_end_attribute_uri:
            mapped_values.pop(filter_end_attribute_uri, None)
        for name, link in (
            ("api_link_attribute_uri", configuration.api_link),
            ("frontend_link_attribute_uri", configuration.frontend_link),
        ):
            uri = getattr(self, name, None)
            if uri and link:
                mapped_values[uri] = link
        self._normalize_configuration_datetimes(mapped_values)
        if needs_configuration_location and location is not None:
            for name, value in (
                ("latitude_attribute_uri", location.latitude),
                ("longitude_attribute_uri", location.longitude),
                ("location_attribute_uri", f"({location.latitude},{location.longitude})"),
            ):
                uri = getattr(self, name, None)
                if uri:
                    mapped_values[uri] = value

        collections = []
        effects = []

        if membership is not None:
            selected_device_values = [
                self._member_value(member, configuration_data.get("data", {}).get("id")) for member in membership.members
            ]
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
                        station_height_amsl=value.get("station_height_amsl"),
                        vertical_surface_offset=value.get("vertical_surface_offset"),
                        site_name=value.get("site_name"),
                        mount_location_resolved=True,
                        mount_location_notices=tuple(value.get("mount_location_notices", ())),
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

            if parsed_value.tzinfo is not None:
                utc_value = parsed_value.astimezone(dt_timezone.utc)
            else:
                utc_value = parsed_value.replace(tzinfo=dt_timezone.utc)

            mapped_values[attribute_uri] = utc_value.strftime("%Y-%m-%d %H:%M")

    def _member_value(self, member: ConfigurationMember, configuration_id: str | None) -> dict[str, object]:
        attributes = member.attributes
        name = attributes.get("long_name") or attributes.get("short_name", "")
        serial = f" (s/n: {attributes['serial_number']})" if attributes.get("serial_number") else ""
        label = configuration_short_label(f"{self.id_prefix}:{configuration_id}") if configuration_id else None
        prefix = f"{label} " if label else ""
        text_prefix = getattr(self, "device_text_prefix", "SMS Sensor")
        return {
            "text": f"{prefix}{text_prefix}({member.identifier}): {name}{serial}",
            "external_id": f"{getattr(self, 'device_id_prefix', self.id_prefix)}:{member.identifier}",
            "instrument_start": member.instrument_start,
            "instrument_end": member.instrument_end,
            "station_height_amsl": member.location.station_height_amsl,
            "vertical_surface_offset": member.location.vertical_surface_offset,
            "site_name": member.location.site_name,
            "mount_location_notices": member.notices,
        }
