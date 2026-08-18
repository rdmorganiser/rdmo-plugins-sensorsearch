from pathlib import Path

from rdmo_sensorsearch.config_models.contracts import (
    CATALOG_SCOPE_KEYS,
    DEVICE_DETAIL_SYNC_SETTINGS,
    HANDLER_SETTINGS,
    PROVIDER_SETTINGS,
)


def test_configuration_reference_mentions_every_validated_toml_setting():
    reference = (Path(__file__).parents[1] / "docs" / "configuration-reference.md").read_text(encoding="utf-8")
    settings = (
        set(CATALOG_SCOPE_KEYS)
        | set(DEVICE_DETAIL_SYNC_SETTINGS)
        | set().union(*PROVIDER_SETTINGS.values())
        | set().union(*HANDLER_SETTINGS.values())
        | {
            "min_search_len",
            "filter_sms_devices_by_selected_configuration",
            "provider_defaults",
            "providers",
            "catalogs",
            "attribute_mapping",
            "defaults",
            "backend_defaults",
            "backends",
            "kind",
            "trigger_attribute_uri",
            "configuration_search_attribute_uri",
            "device_search_attribute_uri",
            "status_attribute_uri",
            "message_attribute_uri",
            "timestamp_attribute_uri",
            "replace_existing_collections",
            "require_configuration_period",
            "input_attribute_uris",
            "devices_attribute_uri",
            "parameter_name_attribute_uri",
            "parameter_unit_attribute_uri",
            "variable_attribute_uri",
            "unit_attribute_uri",
        }
    )

    undocumented = sorted(setting for setting in settings if f"`{setting}`" not in reference)
    assert undocumented == []
