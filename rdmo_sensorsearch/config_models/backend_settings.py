"""Backend-specific connection settings. No catalog or request state belongs here."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SMSDeviceEndpoints:
    device_url: str = "{base_url}/devices/{id}?include=device_properties"
    contact_url: str = (
        "{base_url}/devices/{id}/device-contact-roles?include=contact&page[size]={page_size}&page[number]={page_number}"
    )
    device_mount_actions_url: str = (
        "{base_url}/devices/{id}/device-mount-actions"
        "?page[size]=10000&include=begin_contact,end_contact,parent_platform,parent_device,configuration"
    )
    configuration_device_mount_actions_url: str = (
        "{base_url}/device-mount-actions?filter[configuration_id]={id}"
        "&page[size]=10000&include=parent_platform,parent_device,configuration"
    )
    configuration_platform_mount_actions_url: str = (
        "{base_url}/platform-mount-actions?filter[configuration_id]={id}&page[size]=10000"
    )
    configuration_static_location_actions_url: str = (
        "{base_url}/static-location-actions?filter[configuration_id]={id}&page[size]=10000"
    )


@dataclass(frozen=True)
class SMSConfigurationEndpoints:
    configuration_url: str = "{base_url}/configurations/{id}"
    device_url: str = "{base_url}/devices/{id}"
    device_mount_action_url: str = "{base_url}/device-mount-actions/{id}"
    device_mount_actions_url: str = (
        "{base_url}/device-mount-actions?filter[configuration_id]={id}&include=device"
        "&page[size]={page_size}&page[number]={page_number}"
    )
    platform_mount_actions_url: str = (
        "{base_url}/platform-mount-actions?filter[configuration_id]={id}&page[size]={page_size}&page[number]={page_number}"
    )
    static_location_actions_url: str = (
        "{base_url}/static-location-actions?filter[configuration_id]={id}&page[size]={page_size}&page[number]={page_number}"
    )
    mounting_action_timepoints_url: str = "{base_url}/configurations/{id}/mounting-action-timepoints"
    device_mount_action_page_size: int = 100
    platform_mount_action_page_size: int = 100
    static_location_action_page_size: int = 100
    max_collection_pages: int = 1000
    configuration_self_link_path: str = "data.links.self"
    frontend_link_suffix: str | None = None


@dataclass(frozen=True)
class SMSBackendSettings:
    device: SMSDeviceEndpoints = SMSDeviceEndpoints()
    configuration: SMSConfigurationEndpoints = SMSConfigurationEndpoints()
    device_search_url: str = "{base_url}/devices"
    configuration_search_url: str = "{base_url}/configurations"
    device_query_url: str = "{base_url}?q={query}"
    configuration_query_url: str = (
        "{base_url}?page[size]={page_size}&page[number]=1&include=created_by.contact"
        "&filter=[]&q={query}&sort=label&hide_archived=false"
    )
    backend_link_marker: str = "/backend/api/v1/"
    static_location_end_tolerance_seconds: int = 0
    incomplete_mount_chain_policy: str = "strict"


@dataclass(frozen=True)
class O2AItemEndpoints:
    item_url: str = "{base_url}/items/{id}"
    contacts_url: str = "{base_url}/items/{id}/contacts"
    parameters_url: str = "{base_url}/items/{id}/parameters"
    units_url: str = "{base_url}/units"
    item_api_link_template: str = "{base_url}/items/{id}"
    item_frontend_link_template: str = "{base_url_origin}/items/{id}"


@dataclass(frozen=True)
class O2AMissionEndpoints:
    mission_url: str = "{base_url}/missions/{id}"
    mission_items_url: str = "{base_url}/missions/{id}/items?offset={offset}&hits={page_size}"
    item_url: str = "{base_url}/items/{id}"
    mission_item_page_size: int = 100
    max_collection_pages: int = 1000
    api_link_template: str = "{base_url}/missions/{id}"
    frontend_link_template: str = "{base_url_origin}/missions/{id}"


@dataclass(frozen=True)
class O2AMissionQuerySettings:
    where_template: str = 'name=ILIKE="*{query}*"'
    sorts: str = ""
    offset: int = 0


@dataclass(frozen=True)
class O2ABackendSettings:
    api_url: str = "{base_url}/rest/v2"
    item_search_url: str = "{base_url}/index/rest/search/sensor-v2"
    mission_search_url: str = "{base_url}/rest/v2/missions"
    mission_query_url: str = "{base_url}?where={where}&sorts={sorts}&offset={offset}&hits={hits}"
    item: O2AItemEndpoints = O2AItemEndpoints()
    mission: O2AMissionEndpoints = O2AMissionEndpoints()


@dataclass(frozen=True)
class GIPPBackendSettings:
    instruments_url: str = "{base_url}/index.json?limit=10000&program=MOSES"
    metadata_url: str = "{base_url}/rest"
    json_url: str = "{base_url}/{id}.json"


BackendSettings = SMSBackendSettings | O2ABackendSettings | GIPPBackendSettings
