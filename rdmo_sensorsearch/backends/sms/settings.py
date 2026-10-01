from dataclasses import dataclass


@dataclass(frozen=True)
class SMSSearchSettings:
    base_url: str
    query_url: str


@dataclass(frozen=True)
class SMSDeviceSettings:
    base_url: str
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
    backend_link_marker: str = "/backend/api/v1/"
    static_location_end_tolerance_seconds: int = 0
    incomplete_mount_chain_policy: str = "strict"


@dataclass(frozen=True)
class SMSConfigurationSettings:
    base_url: str
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
    self_link_fallback_enabled: bool = False
    frontend_link_suffix: str | None = None
    backend_link_marker: str = "/backend/api/v1/"
    static_location_end_tolerance_seconds: int = 0
    incomplete_mount_chain_policy: str = "strict"
