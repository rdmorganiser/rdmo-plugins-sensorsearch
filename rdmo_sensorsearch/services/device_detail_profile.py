"""Catalog-scoped URIs used by device-detail synchronization."""

from __future__ import annotations

from rdmo_sensorsearch.config_models import PluginConfig
from rdmo_sensorsearch.contracts import DeviceDetailSettings

DEFAULT_DEVICE_DETAIL_SETTINGS = DeviceDetailSettings(
    device_details_page_uri="https://rdmo.nfdi4earth.de/terms/questions/instruments_general",
    device_optional_info_page_uri="https://rdmo.nfdi4earth.de/terms/questions/instruments/further-info",
    configuration_collection_attribute_uri="https://rdmo.nfdi4earth.de/terms/domain/configuration-set",
    device_link_attribute_uri="https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/device-link",
    usage_technology_attribute_uri="https://rdmorganiser.github.io/terms/domain/project/dataset/usage_technology",
    instrument_start_attribute_uri="https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/instrument-start-datetime",
    instrument_end_attribute_uri="https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/instrument-end-datetime",
    instrument_location_amsl_attribute_uri="https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/geo_location/height",
    surface_offset_z_attribute_uri="https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/geo_location/depth",
    site_name_attribute_uri="https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/processing/location",
    serial_number_attribute_uri="https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/serial_number",
)


def get_device_detail_settings(catalog_uri: str, *, config: PluginConfig) -> DeviceDetailSettings:
    """Return the exact catalog profile, then a wildcard profile, then defaults."""

    profiles = config.device_detail_sync.catalogs
    for profile in profiles:
        if profile.scope.catalog_uris and catalog_uri in profile.scope.catalog_uris:
            return DeviceDetailSettings(**profile.settings)
    for profile in profiles:
        if not profile.scope.catalog_uris:
            return DeviceDetailSettings(**profile.settings)
    return DEFAULT_DEVICE_DETAIL_SETTINGS
