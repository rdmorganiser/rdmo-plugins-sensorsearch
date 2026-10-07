import logging
from collections.abc import Mapping
from dataclasses import replace

from rdmo_sensorsearch.contracts import (
    AuthoritativeTextScalar,
    BackendFailure,
    DeviceSource,
    HandlerExecutionContext,
    HandlerResult,
    RefreshNotice,
)
from rdmo_sensorsearch.handlers.base import BackendRecordHandler
from rdmo_sensorsearch.handlers.parser import evaluate_jmespath_mapping
from rdmo_sensorsearch.services.device_detail_profile import DEFAULT_DEVICE_DETAIL_SETTINGS
from rdmo_sensorsearch.services.device_details import parse_external_id

logger = logging.getLogger(__name__)

DEVICE_LINK_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/device-link"
INSTRUMENT_START_ATTRIBUTE_URI = DEFAULT_DEVICE_DETAIL_SETTINGS.instrument_start_attribute_uri
INSTRUMENT_END_ATTRIBUTE_URI = DEFAULT_DEVICE_DETAIL_SETTINGS.instrument_end_attribute_uri
INSTRUMENT_LOCATION_AMSL_ATTRIBUTE_URI = DEFAULT_DEVICE_DETAIL_SETTINGS.instrument_location_amsl_attribute_uri
SURFACE_OFFSET_Z_ATTRIBUTE_URI = DEFAULT_DEVICE_DETAIL_SETTINGS.surface_offset_z_attribute_uri
SITE_NAME_ATTRIBUTE_URI = DEFAULT_DEVICE_DETAIL_SETTINGS.site_name_attribute_uri
OWNER_ORGANIZATIONS_PATH = "sms_owner_organizations"


class SensorManagementSystemDeviceHandler(BackendRecordHandler):
    """
    Synchronizes device information from a Sensor Management System (SMS).

    This handler fetches device information, including properties, from the
    SMS API.
    """

    materialize_device_details = True
    supports_mount_period_lookup = True
    supports_mount_location_lookup = True

    uses_auth_token = True

    def __init__(self, *, backend: DeviceSource, id_prefix: str, base_url: str, attribute_mapping: Mapping[str, str]):
        super().__init__(id_prefix=id_prefix, base_url=base_url, attribute_mapping=attribute_mapping)
        self.backend = backend

    def handle(
        self,
        backend_id: str,
        *,
        auth_token: str | None = None,
        context: HandlerExecutionContext,
    ) -> dict | HandlerResult:
        """
        Synchronizes one SMS device with its RDMO value.

        Args:
            backend_id (str): The ID of the device to get information for.

        Returns:
            dict: A dictionary containing the mapped values from the SMS API
                  response.
        """

        response = self.backend.get_device(backend_id, auth_token=auth_token)
        if isinstance(response, BackendFailure):
            return {"errors": list(response.errors)}
        metadata = response.value
        mapped_values = evaluate_jmespath_mapping(self.attribute_mapping, metadata.document)
        owner_attribute_uri = self.attribute_mapping.get(OWNER_ORGANIZATIONS_PATH)
        if owner_attribute_uri:
            mapped_values[owner_attribute_uri] = AuthoritativeTextScalar(metadata.owner_organizations)
        detail_settings = context.device_detail_settings or DEFAULT_DEVICE_DETAIL_SETTINGS
        link_uri = getattr(self, "device_link_attribute_uri", detail_settings.device_link_attribute_uri)
        if metadata.frontend_link and link_uri:
            mapped_values[link_uri] = metadata.frontend_link
        external_id = f"{self.id_prefix}:{backend_id}"
        notices = [replace(notice, external_id=external_id) for notice in response.notices]
        mount_metadata_errors = self._set_mount_metadata(
            mapped_values,
            backend_id,
            context.configuration_external_id,
            auth_token=auth_token,
            notice_sink=notices,
            detail_settings=detail_settings,
        )
        if mount_metadata_errors:
            return {"errors": mount_metadata_errors}
        return HandlerResult(mapped_values=mapped_values, notices=tuple(notices))

    def _set_mount_metadata(
        self,
        mapped_values: dict,
        device_id: str,
        configuration_external_id: str | None = None,
        auth_token: str | None = None,
        notice_sink: list[RefreshNotice] | None = None,
        detail_settings=DEFAULT_DEVICE_DETAIL_SETTINGS,
    ) -> list[str]:
        if not configuration_external_id:
            return []

        configuration_id = parse_external_id(configuration_external_id)[1]
        if not configuration_id:
            return []

        period = self.backend.get_mount_period(device_id, configuration_id, auth_token=auth_token)
        if isinstance(period, BackendFailure):
            return list(period.errors)
        if period.value is None:
            return []
        mapped_values[detail_settings.instrument_start_attribute_uri] = period.value.start
        mapped_values[detail_settings.instrument_end_attribute_uri] = period.value.end or ""
        location = self.backend.get_mount_location(device_id, configuration_id, period=period.value, auth_token=auth_token)
        if isinstance(location, BackendFailure):
            return list(location.errors)
        if location.value is None:
            return []
        if notice_sink is not None:
            notice_sink.extend(location.notices)
        mapped_values[detail_settings.instrument_location_amsl_attribute_uri] = (
            location.value.station_height_amsl if location.value.station_height_amsl is not None else ""
        )
        mapped_values[detail_settings.surface_offset_z_attribute_uri] = (
            location.value.vertical_surface_offset if location.value.vertical_surface_offset is not None else ""
        )
        mapped_values[detail_settings.site_name_attribute_uri] = (
            location.value.site_name if location.value.site_name is not None else ""
        )
        return []
