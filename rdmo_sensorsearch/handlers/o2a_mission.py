from collections import defaultdict
from collections.abc import Mapping
from datetime import timezone as dt_timezone

from rdmo_sensorsearch.contracts import (
    BackendFailure,
    CollectionAssignment,
    ConfigurationMember,
    ConfigurationWithMembersSource,
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


class O2ARegistryMissionHandler(BackendRecordHandler):
    """Map a mission and declare catalog collections and device refresh effects."""

    item_id_prefix: str
    item_text_prefix = "O2A Item"
    item_text_template = "{configuration} {prefix}({item_id}): {name}{serial}"
    mission_start_date_path = "startDate"
    mission_end_date_path = "endDate"
    date_mapping_paths = ("startDate", "endDate")
    datetime_output_format = "%Y-%m-%d %H:%M"

    def __init__(self, *, backend: ConfigurationWithMembersSource, id_prefix: str, attribute_mapping: Mapping[str, str]):
        super().__init__(id_prefix=id_prefix, attribute_mapping=attribute_mapping)
        self.backend = backend

    def handle(self, backend_id: str, *, context: HandlerExecutionContext, auth_token: str | None = None) -> HandlerOutcome:
        response = self.backend.get_configuration(backend_id, auth_token=auth_token)
        if isinstance(response, BackendFailure):
            return HandlerFailure(response.errors)
        metadata = response.value
        mapped_values = evaluate_jmespath_mapping(self.attribute_mapping, metadata.document)
        for name, link in (
            ("api_link_attribute_uri", metadata.api_link),
            ("frontend_link_attribute_uri", metadata.frontend_link),
        ):
            uri = getattr(self, name, None)
            if uri and link:
                mapped_values[uri] = link
        self._normalize_datetimes(mapped_values)
        selected_uri = getattr(self, "selected_devices_attribute_uri", None)
        if not selected_uri or context.preserve_existing_collections:
            return HandlerResult(mapped_values=mapped_values, notices=response.notices)

        membership = self.backend.get_configuration_members(
            metadata,
            period=context.configuration_period,
            require_configuration_period=context.require_configuration_period,
            auth_token=auth_token,
        )
        if isinstance(membership, BackendFailure):
            return HandlerFailure(membership.errors)
        # Period source fields and display formats are catalog choices, not API mechanics.
        start = self._format_timepoint(metadata.document.get(self.mission_start_date_path))
        end = self._format_timepoint(metadata.document.get(self.mission_end_date_path))
        values = tuple(
            {
                "text": self._format_item_text(backend_id, metadata.document, member),
                "external_id": f"{self.item_id_prefix}:{member.identifier}",
                "instrument_start": start,
                "instrument_end": end,
            }
            for member in membership.value.members
        )
        collections = (CollectionAssignment(selected_uri, self.selected_devices_page_uri, values),)
        root = getattr(self, "device_collection_attribute_uri", None)
        effects = ()
        if root:
            effects = (
                RefreshDeviceDetails(
                    tuple(
                        SelectedDevice(
                            text=value["text"],
                            external_id=value["external_id"],
                            instrument_start=start,
                            instrument_end=end,
                        )
                        for value in values
                    ),
                    selected_uri,
                    root,
                ),
            )
        return HandlerResult(
            mapped_values=mapped_values, collections=collections, effects=effects, notices=response.notices + membership.notices
        )

    def _normalize_datetimes(self, mapped_values: dict[str, str | None]) -> None:
        datetime_paths = set(getattr(self, "date_mapping_paths", []))
        for source_path, attribute_uri in self.attribute_mapping.items():
            if source_path not in datetime_paths:
                continue

            value = mapped_values.get(attribute_uri)
            formatted = self._format_timepoint(value)
            if formatted is not None:
                mapped_values[attribute_uri] = formatted

    def get_member_device_period(self, mapped_values=None) -> tuple[str | None, str | None]:
        mapped_values = mapped_values or {}
        start_attribute_uri = self.attribute_mapping.get(self.mission_start_date_path)
        end_attribute_uri = self.attribute_mapping.get(self.mission_end_date_path)
        return (
            mapped_values.get(start_attribute_uri) if start_attribute_uri else None,
            mapped_values.get(end_attribute_uri) if end_attribute_uri else None,
        )

    def _format_item_text(self, mission_id: str, mission_data: dict, member: ConfigurationMember) -> str:
        values = defaultdict(str, member.attributes)
        serial = member.attributes.get("serial_number")
        values.update(
            {
                "prefix": self.item_text_prefix,
                "configuration": configuration_short_label(f"{self.id_prefix}:{mission_id}") or f"M({mission_id})",
                "mission_id": mission_id,
                "mission_name": mission_data.get("name", ""),
                "mission_uuid": mission_data.get("@uuid", ""),
                "serial": f" (s/n: {serial})" if serial else "",
            }
        )
        return self.item_text_template.format_map(values)

    def _format_timepoint(self, value) -> str | None:
        parsed = parse_datetime(value) if isinstance(value, str) and value else None
        if parsed is None:
            return None
        if parsed.tzinfo is not None:
            utc_value = parsed.astimezone(dt_timezone.utc)
        else:
            utc_value = parsed.replace(tzinfo=dt_timezone.utc)
        return utc_value.strftime(self.datetime_output_format)
