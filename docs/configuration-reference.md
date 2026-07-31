<!--
SPDX-FileCopyrightText: 2026 RDMO Community and individual contributors
SPDX-License-Identifier: Apache-2.0
-->

# `sensorsearch.toml` configuration reference

[Documentation index](index.md) · [Catalog editor guide](catalog-editor-guide.md) · [Earth Sensor URI map](earth-sensor-catalog.md) · [Operations and limitations](operations-and-limitations.md)

This reference follows the repository's [`sensorsearch.toml`](../sensorsearch.toml).
The file is an example deployment configuration, so backend URLs and catalog
scope should be reviewed before using it in production.

The path can be selected with the Django setting or environment variable
`SENSORS_SEARCH_PROVIDER_CONFIG_FILE_PATH`. Otherwise the packaged
`rdmo_sensorsearch/config.toml` is loaded.

## Provider aggregators

### `[SensorsProvider]`

| Setting | Meaning |
| --- | --- |
| `min_search_len` | Minimum number of typed characters before remote device providers are queried. |
| `filter_sms_by_selected_configuration` | When `true`, SMS device search is restricted to the SMS backend matching a selected configuration. Leave `false` when manual searches should cover all SMS instances. |

Each `[[SensorsProvider.providers.<ProviderClass>]]` entry enables one device
source. Multiple entries of the same class are allowed. Common provider fields
are `id_prefix`, `text_prefix`, and `base_url`; provider-specific URL templates
can be overridden when required.

The example enables:

- `O2ARegistrySearchProvider`;
- three `SensorManagementSystemProvider` instances for GFZ, KIT, and UFZ;
- `GeophysicalInstrumentPoolPotsdamProvider`.

Prefixes must be unique across the aggregate provider because they are used to
route a selected option to its handler.

### `[ConfigurationsProvider]`

`min_search_len` has the same meaning for configuration and mission search.
Each `[[ConfigurationsProvider.providers.<ProviderClass>]]` entry enables a
configuration source. The example uses three SMS configuration providers and
one O2A mission provider.

For SMS, keep configuration and device prefixes paired:

| Configuration prefix | Device prefix | Backend |
| --- | --- | --- |
| `gfzcfg` | `gfzsms` | GFZ SMS |
| `kitcfg` | `kitsms` | KIT SMS |
| `ufzcfg` | `ufzsms` | UFZ SMS |

## Project-local providers

### `[ProjectConfigurationSensorsProvider]`

Each `[[ProjectConfigurationSensorsProvider.catalogs]]` entry selects an
attribute whose project values become device options. In the Earth Sensor
catalog it is the selected-devices attribute. Use `catalog_uri` for one catalog,
`catalog_uris` for several, or omit both for a wildcard mapping.

### `[ProjectDataCollectionDevicesProvider]`

This section has the same catalog scoping and `source_attribute_uri` setting,
but supplies the data-collection device optionset. It can reuse the same source
as `ProjectConfigurationSensorsProvider`.

## `[DataCollectionVariableSync]`

`[[DataCollectionVariableSync.catalogs]]` enables automatic variable and unit
rows for selected data-collection devices. `catalog_uri` selects one catalog;
`catalog_uris` selects several. Do not add a wildcard entry unless every catalog
using the plugin has compatible data-collection attributes and collection
layout.

Each catalog entry can override these attributes; otherwise the built-in Earth
Sensor defaults are used:

| Setting | Purpose |
| --- | --- |
| `devices_attribute_uri` | Selected devices in the data-collection section. |
| `device_collection_attribute_uri` | Device-detail collection used to find the selected device's parameters. |
| `parameter_name_attribute_uri` | Parameter name inside a device detail block. |
| `parameter_unit_attribute_uri` | Parameter unit inside a device detail block. |
| `variable_attribute_uri` | Generated data-collection variable target. |
| `unit_attribute_uri` | Generated data-collection unit target. |

The concrete Earth Sensor elements are listed in the
[catalog map](earth-sensor-catalog.md#data-collection-device-and-variable-sync).

## `[MetadataRefresh]`

`configuration_search_attribute_uri` and `device_search_attribute_uri` tell
refresh actions where the selected backend IDs are stored.

Each `[[MetadataRefresh.actions]]` supports:

| Setting | Meaning |
| --- | --- |
| `kind` | One of `configuration`, `device`, `all_configurations`, or `all_devices`. |
| `trigger_attribute_uri` | Attribute whose saved answer invokes the action. |
| `status_attribute_uri` | Optional target for machine-readable or concise status text. |
| `message_attribute_uri` | Optional target for user-facing details and errors. |
| `timestamp_attribute_uri` | Optional target for the refresh time. |
| `replace_collections` | Rebuild configuration device membership instead of preserving existing collections. Used by explicit period application. |
| `require_configuration_period` | Reject the action unless the configured start/end inputs form a valid period. |
| `input_attribute_uris` | User-owned input fields that affect this action. Changes clear stale feedback but do not execute the action. |

The date-range action is a second `kind = "configuration"` action. The presence
of the exact Earth Sensor trigger attribute
`https://rdmo.nfdi4earth.de/terms/domain/configuration-set/apply-date-range` in
the current catalog activates the explicit date-range workflow for
configuration and mission selection. Therefore, removing the question from a
catalog changes behavior even when the TOML action remains configured. A
different custom trigger URI can configure an action, but it does not currently
replace this URI in the catalog-presence check.

## Handler structure

Handlers turn a selected provider option into RDMO answers. Their common layout
is:

```toml
[handlers.SomeHandler]

[[handlers.SomeHandler.backends]]
id_prefix = "example"
base_url = "https://api.example.org"

[handlers.SomeHandler.defaults]
# settings shared by all catalog mappings

[[handlers.SomeHandler.catalogs]]
catalog_uri = "https://example.org/catalog"
auto_complete_field_uri = "https://example.org/attributes/search"
managed_attribute_uris = ["https://example.org/attributes/output"]

[handlers.SomeHandler.catalogs.attribute_mapping]
"backend.path" = "https://example.org/attributes/output"
```

`defaults` are merged into each catalog entry. A catalog entry can override a
default. Omitting `catalog_uri` and `catalog_uris` creates a wildcard catalog
mapping. Prefer explicit scope when two catalogs use different attribute
semantics.

Common handler settings are:

| Setting | Meaning |
| --- | --- |
| `auto_complete_field_uri` | Search attribute monitored for a selected backend option. |
| `attribute_mapping` | JMESPath-to-RDMO-attribute mapping. Array results create indexed values. |
| `managed_attribute_uris` | Additional fields authoritatively owned by the handler. |
| `sync_device_detail_blocks` | Allows selected devices to be materialized into repeated detail collections. |
| `device_link_attribute_uri` | Target for a backend or frontend record link. |
| `catalog_uri`, `catalog_uris` | Catalog scope; omitted means wildcard. |

### `O2ARegistrySearchHandler`

This handler fetches one O2A item. Its mapping can read names, type,
manufacturer, model, serial number, citation, parameters, units, and contacts.
`item_api_link_template` and `item_frontend_link_template` configure record
links.

### `SensorManagementSystemHandler`

This handler fetches one SMS device. Multiple `backends` associate SMS
`id_prefix` values with base URLs. Important settings are:

| Setting | Meaning |
| --- | --- |
| `backend_link_marker` | Recognizes and normalizes SMS backend links. |
| `device_mount_actions_url` | Endpoint template used for device deployment periods and mount context. |
| `supports_mount_action_period_lookup` | Enables SMS mount-action enrichment for device detail blocks. |

SMS mount enrichment can derive a device's active period, site name, and
vertical position. See [Operations and limitations](operations-and-limitations.md#sms-location-height-and-depth).

### `SensorManagementSystemConfigurationsHandler`

This handler fetches one SMS configuration and its mounted devices.

| Setting | Meaning |
| --- | --- |
| `configuration_collection_attribute_uri` | Repeated configuration collection root. |
| `member_sensors_attribute_uri` | Attribute storing selected or mounted devices. |
| `selected_devices_page_uri` | Page containing the selected device set. |
| `device_collection_attribute_uri` | Repeated device-detail collection root. |
| `frontend_link_attribute_uri` | Configuration link target. |
| `latitude_attribute_uri`, `longitude_attribute_uri` | Configuration static-location targets. |
| `cfg_start_uri`, `cfg_end_uri` | User-entered filtering period inputs. These are not backend output mappings. |
| `sensor_id_prefix`, `sensor_text_prefix` | Converts a mounted SMS device into an option understood by the matching device handler. |

The configuration provider's `id_prefix` must match the handler backend entry,
and `sensor_id_prefix` must match a configured SMS device provider and handler.

### `O2ARegistryMissionsHandler`

This handler treats an O2A mission as a configuration and its items as member
devices. The configuration collection, member sensor, selected-device page,
device collection, frontend link, and `cfg_start_uri`/`cfg_end_uri` settings
have the same catalog meaning as for SMS.

`mission_url`, `mission_items_url`, and `item_url` control API requests.
`mission_item_max_hits` limits the page size. `item_id_prefix` must match the
O2A device provider. `mission_start_date_path`, `mission_end_date_path`, and
`date_mapping_paths` describe dates present in the mission API; they do not
make the catalog's user-entered start/end attributes backend-managed outputs.

### `GeophysicalInstrumentPoolPotsdamHandler`

This handler maps GIPP records, including instrument code, category,
manufacturer, serial number, PID, and contact. It participates in device search
and detail synchronization but not configuration or mission membership.

## Catalog scope and wildcard mappings

The example configuration contains wildcard catalog entries so the same Earth
Sensor attribute scheme can be reused by compatible catalogs. This is
convenient but broad: a handler can run in any catalog containing its search
attribute. To isolate behavior, add `catalog_uri` or `catalog_uris` to every
handler and project-local provider mapping.

When two matching catalog entries could apply, avoid relying on file order.
Give each catalog one unambiguous mapping for a handler.
