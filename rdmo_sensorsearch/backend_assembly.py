"""Typed composition root. Backend types select builders; consumers select capabilities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

from rdmo_sensorsearch.backends.gipp.backend import GIPPBackend
from rdmo_sensorsearch.backends.o2a.backend import O2ABackend
from rdmo_sensorsearch.backends.sms.backend import SMSBackend
from rdmo_sensorsearch.backends.sms.settings import SMSConfigurationSettings, SMSDeviceSettings, SMSSearchSettings
from rdmo_sensorsearch.client import fetch_json
from rdmo_sensorsearch.config_models.backend_settings import (
    GIPPBackendSettings,
    O2ABackendSettings,
    O2AMissionQuerySettings,
    SMSBackendSettings,
)
from rdmo_sensorsearch.config_models.consumer_settings import (
    GIPPInstrumentCatalogSettings,
    O2AMissionSearchSettings,
    O2ARegistryItemCatalogSettings,
    O2ARegistryMissionCatalogSettings,
    SensorManagementSystemConfigurationCatalogSettings,
    SensorManagementSystemDeviceCatalogSettings,
)
from rdmo_sensorsearch.config_models.models import (
    BackendDefinition,
    HandlerCatalogConfig,
    HandlerInstanceConfig,
    ProviderInstanceConfig,
)
from rdmo_sensorsearch.handlers.gipp_instrument import GIPPInstrumentHandler
from rdmo_sensorsearch.handlers.o2a_item import O2ARegistryItemHandler
from rdmo_sensorsearch.handlers.o2a_mission import O2ARegistryMissionHandler
from rdmo_sensorsearch.handlers.sms_configuration import SensorManagementSystemConfigurationHandler
from rdmo_sensorsearch.handlers.sms_device import SensorManagementSystemDeviceHandler

if TYPE_CHECKING:
    from rdmo_sensorsearch.handlers.base import BackendRecordHandler
    from rdmo_sensorsearch.providers.base import BaseRemoteSearchProvider
    from rdmo_sensorsearch.providers.gipp_instrument import GIPPInstrumentProvider
    from rdmo_sensorsearch.providers.o2a_item import O2ARegistryItemProvider
    from rdmo_sensorsearch.providers.o2a_mission import O2ARegistryMissionProvider
    from rdmo_sensorsearch.providers.sms_configuration import SensorManagementSystemConfigurationProvider
    from rdmo_sensorsearch.providers.sms_device import SensorManagementSystemDeviceProvider

Capability = Literal["device", "configuration", "device_search", "configuration_search"]


BackendBinding = SMSBackend | O2ABackend | GIPPBackend


class BackendBuilder(Protocol):
    def __call__(
        self, definition: BackendDefinition, capability: Capability, *, self_link_fallback_enabled: bool = False
    ) -> BackendBinding: ...


class ProviderBuilder(Protocol):
    def __call__(self, config: ProviderInstanceConfig, definition: BackendDefinition) -> BaseRemoteSearchProvider: ...


class HandlerBuilder(Protocol):
    def __call__(
        self, instance: HandlerInstanceConfig, catalog: HandlerCatalogConfig, definition: BackendDefinition
    ) -> BackendRecordHandler: ...


def build_sms_backend(
    definition: BackendDefinition, capability: Capability, *, self_link_fallback_enabled: bool = False
) -> SMSBackend:
    settings = definition.settings
    assert isinstance(settings, SMSBackendSettings)
    if capability in {"device_search", "configuration_search"}:
        resource_url = settings.device_search_url if capability == "device_search" else settings.configuration_search_url
        query_url = settings.device_query_url if capability == "device_search" else settings.configuration_query_url
        return SMSBackend(
            fetch=fetch_json, search_settings=SMSSearchSettings(resource_url.format(base_url=definition.base_url), query_url)
        )
    if capability == "device":
        return SMSBackend(
            fetch=fetch_json,
            device_settings=SMSDeviceSettings(
                base_url=definition.base_url,
                device_url=settings.device.device_url,
                contact_url=settings.device.contact_url,
                device_mount_actions_url=settings.device.device_mount_actions_url,
                configuration_device_mount_actions_url=settings.device.configuration_device_mount_actions_url,
                configuration_platform_mount_actions_url=settings.device.configuration_platform_mount_actions_url,
                configuration_static_location_actions_url=settings.device.configuration_static_location_actions_url,
                backend_link_marker=settings.backend_link_marker,
                static_location_end_tolerance_seconds=settings.static_location_end_tolerance_seconds,
                incomplete_mount_chain_policy=settings.incomplete_mount_chain_policy,
            ),
        )
    if capability == "configuration":
        return SMSBackend(
            fetch=fetch_json,
            configuration_settings=SMSConfigurationSettings(
                base_url=definition.base_url,
                configuration_url=settings.configuration.configuration_url,
                device_url=settings.configuration.device_url,
                device_mount_action_url=settings.configuration.device_mount_action_url,
                device_mount_actions_url=settings.configuration.device_mount_actions_url,
                platform_mount_actions_url=settings.configuration.platform_mount_actions_url,
                static_location_actions_url=settings.configuration.static_location_actions_url,
                mounting_action_timepoints_url=settings.configuration.mounting_action_timepoints_url,
                device_mount_action_page_size=settings.configuration.device_mount_action_page_size,
                platform_mount_action_page_size=settings.configuration.platform_mount_action_page_size,
                static_location_action_page_size=settings.configuration.static_location_action_page_size,
                max_collection_pages=settings.configuration.max_collection_pages,
                configuration_self_link_path=settings.configuration.configuration_self_link_path,
                self_link_fallback_enabled=self_link_fallback_enabled,
                frontend_link_suffix=settings.configuration.frontend_link_suffix,
                backend_link_marker=settings.backend_link_marker,
                static_location_end_tolerance_seconds=settings.static_location_end_tolerance_seconds,
                incomplete_mount_chain_policy=settings.incomplete_mount_chain_policy,
            ),
        )
    raise ValueError(f"Unsupported SMS capability {capability!r}")


def build_o2a_backend(
    definition: BackendDefinition, capability: Capability, *, self_link_fallback_enabled: bool = False
) -> O2ABackend:
    settings = definition.settings
    assert isinstance(settings, O2ABackendSettings)
    return O2ABackend(base_url=definition.base_url, settings=settings, fetch=fetch_json)


def build_gipp_backend(
    definition: BackendDefinition, capability: Capability, *, self_link_fallback_enabled: bool = False
) -> GIPPBackend:
    settings = definition.settings
    assert isinstance(settings, GIPPBackendSettings)
    return GIPPBackend(base_url=definition.base_url, settings=settings, fetch=fetch_json)


BACKEND_BUILDERS: dict[str, BackendBuilder] = {"sms": build_sms_backend, "o2a": build_o2a_backend, "gipp": build_gipp_backend}


def build_backend(
    definition: BackendDefinition, capability: Capability, *, self_link_fallback_enabled: bool = False
) -> BackendBinding:
    return BACKEND_BUILDERS[definition.type](definition, capability, self_link_fallback_enabled=self_link_fallback_enabled)


def build_sms_device_provider(
    config: ProviderInstanceConfig, definition: BackendDefinition
) -> SensorManagementSystemDeviceProvider:
    from rdmo_sensorsearch.providers.sms_device import SensorManagementSystemDeviceProvider

    connection = build_backend(definition, "device_search")
    assert isinstance(connection, SMSBackend)
    assert isinstance(definition.settings, SMSBackendSettings)
    settings = config.settings
    provider = SensorManagementSystemDeviceProvider(
        id_prefix=definition.prefix("device"),
        text_prefix=settings.text_prefix,
        base_url=definition.settings.device_search_url.format(base_url=definition.base_url),
        max_hits=settings.max_hits,
        backend=connection,
    )
    if settings.option_id is not None:
        provider.option_id = settings.option_id
    if settings.option_text is not None:
        provider.option_text = settings.option_text
    provider.backend_name = definition.name
    provider.backend_type = definition.type
    provider.resource_kind = "device"
    return provider


def build_sms_configuration_provider(
    config: ProviderInstanceConfig, definition: BackendDefinition
) -> SensorManagementSystemConfigurationProvider:
    from rdmo_sensorsearch.providers.sms_configuration import SensorManagementSystemConfigurationProvider

    connection = build_backend(definition, "configuration_search")
    assert isinstance(connection, SMSBackend)
    assert isinstance(definition.settings, SMSBackendSettings)
    settings = config.settings
    provider = SensorManagementSystemConfigurationProvider(
        id_prefix=definition.prefix("configuration"),
        text_prefix=settings.text_prefix,
        base_url=definition.settings.configuration_search_url.format(base_url=definition.base_url),
        max_hits=settings.max_hits,
        backend=connection,
    )
    if settings.option_id is not None:
        provider.option_id = settings.option_id
    if settings.option_text is not None:
        provider.option_text = settings.option_text
    provider.backend_name = definition.name
    provider.backend_type = definition.type
    provider.resource_kind = "configuration"
    return provider


def build_o2a_item_provider(config: ProviderInstanceConfig, definition: BackendDefinition) -> O2ARegistryItemProvider:
    from rdmo_sensorsearch.providers.o2a_item import O2ARegistryItemProvider

    connection = build_backend(definition, "device_search")
    assert isinstance(connection, O2ABackend)
    settings = config.settings
    provider = O2ARegistryItemProvider(
        base_url=connection._item.search_url,
        id_prefix=definition.prefix("device"),
        text_prefix=settings.text_prefix,
        backend=connection,
        max_hits=settings.max_hits,
    )
    if settings.option_id is not None:
        provider.option_id = settings.option_id
    if settings.option_text is not None:
        provider.option_text = settings.option_text
    provider.backend_name = definition.name
    provider.backend_type = definition.type
    provider.resource_kind = "device"
    return provider


def build_o2a_mission_provider(config: ProviderInstanceConfig, definition: BackendDefinition) -> O2ARegistryMissionProvider:
    from rdmo_sensorsearch.providers.o2a_mission import O2ARegistryMissionProvider

    settings = config.settings
    assert isinstance(settings, O2AMissionSearchSettings)
    assert isinstance(definition.settings, O2ABackendSettings)
    connection = O2ABackend(
        base_url=definition.base_url,
        settings=definition.settings,
        fetch=fetch_json,
        mission_query_settings=O2AMissionQuerySettings(settings.where_template, settings.sorts, settings.offset),
    )
    provider = O2ARegistryMissionProvider(
        base_url=connection._mission.search_url,
        id_prefix=definition.prefix("configuration"),
        text_prefix=settings.text_prefix,
        backend=connection,
        max_hits=settings.max_hits,
    )
    if settings.option_id is not None:
        provider.option_id = settings.option_id
    if settings.option_text is not None:
        provider.option_text = settings.option_text
    provider.backend_name = definition.name
    provider.backend_type = definition.type
    provider.resource_kind = "configuration"
    return provider


def build_gipp_instrument_provider(config: ProviderInstanceConfig, definition: BackendDefinition) -> GIPPInstrumentProvider:
    from rdmo_sensorsearch.providers.gipp_instrument import GIPPInstrumentProvider

    connection = build_backend(definition, "device_search")
    assert isinstance(connection, GIPPBackend)
    settings = config.settings
    provider = GIPPInstrumentProvider(
        base_url=definition.base_url,
        id_prefix=definition.prefix("device"),
        text_prefix=settings.text_prefix,
        backend=connection,
        max_hits=settings.max_hits,
    )
    if settings.option_id is not None:
        provider.option_id = settings.option_id
    if settings.option_text is not None:
        provider.option_text = settings.option_text
    provider.backend_name = definition.name
    provider.backend_type = definition.type
    provider.resource_kind = "device"
    return provider


PROVIDER_BUILDERS: dict[str, ProviderBuilder] = {
    "SensorManagementSystemDeviceProvider": build_sms_device_provider,
    "SensorManagementSystemConfigurationProvider": build_sms_configuration_provider,
    "O2ARegistryItemProvider": build_o2a_item_provider,
    "O2ARegistryMissionProvider": build_o2a_mission_provider,
    "GIPPInstrumentProvider": build_gipp_instrument_provider,
}


def build_sms_device_handler(
    instance: HandlerInstanceConfig, catalog: HandlerCatalogConfig, definition: BackendDefinition
) -> SensorManagementSystemDeviceHandler:
    settings = catalog.settings
    assert isinstance(settings, SensorManagementSystemDeviceCatalogSettings)
    connection = build_backend(definition, "device")
    assert isinstance(connection, SMSBackend)
    handler = SensorManagementSystemDeviceHandler(
        id_prefix=definition.prefix("device"),
        base_url=definition.base_url,
        attribute_mapping=dict(catalog.attribute_mapping),
        backend=connection,
    )
    if settings.device_collection_attribute_uri is not None:
        handler.device_collection_attribute_uri = settings.device_collection_attribute_uri
    if settings.device_link_attribute_uri is not None:
        handler.device_link_attribute_uri = settings.device_link_attribute_uri
    handler.managed_attribute_uris = settings.managed_attribute_uris
    handler.materialize_device_details = settings.materialize_device_details
    handler.supports_mount_location_lookup = settings.supports_mount_location_lookup
    handler.supports_mount_period_lookup = settings.supports_mount_period_lookup
    return handler


def build_sms_configuration_handler(
    instance: HandlerInstanceConfig, catalog: HandlerCatalogConfig, definition: BackendDefinition
) -> SensorManagementSystemConfigurationHandler:
    settings = catalog.settings
    assert isinstance(settings, SensorManagementSystemConfigurationCatalogSettings)
    assert isinstance(definition.settings, SMSBackendSettings)
    fallback = definition.settings.configuration.configuration_self_link_path in catalog.attribute_mapping
    connection = build_backend(definition, "configuration", self_link_fallback_enabled=fallback)
    assert isinstance(connection, SMSBackend)
    handler = SensorManagementSystemConfigurationHandler(
        id_prefix=definition.prefix("configuration"),
        base_url=definition.base_url,
        attribute_mapping=dict(catalog.attribute_mapping),
        backend=connection,
    )
    if settings.api_link_attribute_uri is not None:
        handler.api_link_attribute_uri = settings.api_link_attribute_uri
    if settings.configuration_collection_attribute_uri is not None:
        handler.configuration_collection_attribute_uri = settings.configuration_collection_attribute_uri
    if settings.configuration_end_date_path is not None:
        handler.configuration_end_date_path = settings.configuration_end_date_path
    if settings.configuration_start_date_path is not None:
        handler.configuration_start_date_path = settings.configuration_start_date_path
    if settings.device_collection_attribute_uri is not None:
        handler.device_collection_attribute_uri = settings.device_collection_attribute_uri
    if settings.frontend_link_attribute_uri is not None:
        handler.frontend_link_attribute_uri = settings.frontend_link_attribute_uri
    if settings.latitude_attribute_uri is not None:
        handler.latitude_attribute_uri = settings.latitude_attribute_uri
    if settings.location_attribute_uri is not None:
        handler.location_attribute_uri = settings.location_attribute_uri
    if settings.longitude_attribute_uri is not None:
        handler.longitude_attribute_uri = settings.longitude_attribute_uri
    handler.managed_attribute_uris = settings.managed_attribute_uris
    handler.membership_filter_enabled = settings.membership_filter_enabled
    if settings.membership_filter_end_attribute_uri is not None:
        handler.membership_filter_end_attribute_uri = settings.membership_filter_end_attribute_uri
    if settings.membership_filter_start_attribute_uri is not None:
        handler.membership_filter_start_attribute_uri = settings.membership_filter_start_attribute_uri
    if settings.selected_devices_attribute_uri is not None:
        handler.selected_devices_attribute_uri = settings.selected_devices_attribute_uri
    if settings.selected_devices_page_uri is not None:
        handler.selected_devices_page_uri = settings.selected_devices_page_uri
    handler.device_id_prefix = definition.device_id_prefix
    handler.device_text_prefix = instance.device_text_prefix
    return handler


def build_o2a_item_handler(
    instance: HandlerInstanceConfig, catalog: HandlerCatalogConfig, definition: BackendDefinition
) -> O2ARegistryItemHandler:
    settings = catalog.settings
    assert isinstance(settings, O2ARegistryItemCatalogSettings)
    connection = build_backend(definition, "device")
    assert isinstance(connection, O2ABackend)
    handler = O2ARegistryItemHandler(
        base_url=connection._item.base_url,
        id_prefix=definition.prefix("device"),
        backend=connection,
        attribute_mapping=dict(catalog.attribute_mapping),
    )
    if settings.device_collection_attribute_uri is not None:
        handler.device_collection_attribute_uri = settings.device_collection_attribute_uri
    if settings.device_link_attribute_uri is not None:
        handler.device_link_attribute_uri = settings.device_link_attribute_uri
    handler.managed_attribute_uris = settings.managed_attribute_uris
    handler.materialize_device_details = settings.materialize_device_details
    handler.supports_mount_location_lookup = settings.supports_mount_location_lookup
    handler.supports_mount_period_lookup = settings.supports_mount_period_lookup
    return handler


def build_o2a_mission_handler(
    instance: HandlerInstanceConfig, catalog: HandlerCatalogConfig, definition: BackendDefinition
) -> O2ARegistryMissionHandler:
    settings = catalog.settings
    assert isinstance(settings, O2ARegistryMissionCatalogSettings)
    connection = build_backend(definition, "configuration")
    assert isinstance(connection, O2ABackend)
    handler = O2ARegistryMissionHandler(
        base_url=connection._mission.base_url,
        id_prefix=definition.prefix("configuration"),
        backend=connection,
        attribute_mapping=dict(catalog.attribute_mapping),
    )
    if settings.api_link_attribute_uri is not None:
        handler.api_link_attribute_uri = settings.api_link_attribute_uri
    if settings.configuration_collection_attribute_uri is not None:
        handler.configuration_collection_attribute_uri = settings.configuration_collection_attribute_uri
    handler.date_mapping_paths = settings.date_mapping_paths
    if settings.datetime_output_format is not None:
        handler.datetime_output_format = settings.datetime_output_format
    if settings.device_collection_attribute_uri is not None:
        handler.device_collection_attribute_uri = settings.device_collection_attribute_uri
    if settings.frontend_link_attribute_uri is not None:
        handler.frontend_link_attribute_uri = settings.frontend_link_attribute_uri
    handler.managed_attribute_uris = settings.managed_attribute_uris
    if settings.mission_end_date_path is not None:
        handler.mission_end_date_path = settings.mission_end_date_path
    if settings.mission_start_date_path is not None:
        handler.mission_start_date_path = settings.mission_start_date_path
    if settings.selected_devices_attribute_uri is not None:
        handler.selected_devices_attribute_uri = settings.selected_devices_attribute_uri
    if settings.selected_devices_page_uri is not None:
        handler.selected_devices_page_uri = settings.selected_devices_page_uri
    handler.item_id_prefix = definition.device_id_prefix
    handler.item_text_prefix = instance.item_text_prefix
    handler.item_text_template = instance.item_text_template
    return handler


def build_gipp_instrument_handler(
    instance: HandlerInstanceConfig, catalog: HandlerCatalogConfig, definition: BackendDefinition
) -> GIPPInstrumentHandler:
    settings = catalog.settings
    assert isinstance(settings, GIPPInstrumentCatalogSettings)
    connection = build_backend(definition, "device")
    assert isinstance(connection, GIPPBackend)
    handler = GIPPInstrumentHandler(
        base_url=definition.settings.metadata_url.format(base_url=definition.base_url),
        id_prefix=definition.prefix("device"),
        backend=connection,
        attribute_mapping=dict(catalog.attribute_mapping),
    )
    handler.managed_attribute_uris = settings.managed_attribute_uris
    return handler


HANDLER_BUILDERS: dict[str, HandlerBuilder] = {
    "SensorManagementSystemDeviceHandler": build_sms_device_handler,
    "SensorManagementSystemConfigurationHandler": build_sms_configuration_handler,
    "O2ARegistryItemHandler": build_o2a_item_handler,
    "O2ARegistryMissionHandler": build_o2a_mission_handler,
    "GIPPInstrumentHandler": build_gipp_instrument_handler,
}
