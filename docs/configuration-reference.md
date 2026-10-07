<!--
SPDX-FileCopyrightText: 2026 RDMO Community and individual contributors
SPDX-License-Identifier: Apache-2.0
-->

# `sensorsearch.toml` configuration reference

[Documentation index](index.md) · [Catalog editor guide](catalog-editor-guide.md) · [Earth Sensor URI map](earth-sensor-catalog.md) · [Operations and limitations](operations-and-limitations.md)

This reference follows the repository's [`sensorsearch.toml`](../sensorsearch.toml).
The file is an example deployment configuration, so backend URLs and catalog
scope should be reviewed before using it in production.

The configuration source and request timeout use consistently prefixed Django
settings. The two configuration settings can also be supplied as environment
variables with the same names.

| Setting | Meaning |
| --- | --- |
| `SENSORSEARCH_CONFIG_FILE_PATH` | Complete path to the TOML configuration. Takes precedence over the file name. |
| `SENSORSEARCH_CONFIG_FILE_NAME` | Configuration file name. Defaults to `sensorsearch.toml`. |
| `SENSORSEARCH_REQUEST_TIMEOUT` | Timeout in seconds for backend HTTP requests. Defaults to `10`. |

Without an override, the repository-level `sensorsearch.toml` is used during
development and the identical packaged `rdmo_sensorsearch/sensorsearch.toml`
resource is used after installation.

## Configuration validation

The plugin parses the TOML into immutable standard-library dataclasses before
constructing providers or handlers. An invalid configuration therefore fails
early instead of silently turning a misspelled setting into an unused keyword
argument. The exception includes the path to the failing table or setting, for
example:

```text
handlers.SensorManagementSystemConfigurationHandler.defaults: unknown setting(s): selected_device_attribute_uri
```

Validation currently covers:

- known sections, provider and handler class names, and settings;
- string, integer, boolean, and string-array value types;
- named backend definitions, absolute HTTP(S) URLs, labels, and typed settings;
- globally unique namespace declarations and provider-to-handler backend references;
- backend type/capability compatibility and same-backend membership relationships;
- paired and explicitly enabled SMS membership-filter start/end attributes;
- required search and configuration-membership attributes;
- explicit catalog scope for data-collection variable synchronization.

Configuration is loaded once and cached for the process lifetime. Restart the
RDMO application processes after editing the file. Tests can call
`rdmo_sensorsearch.config.clear_config_cache()` when switching configuration
files within one Python process.

Only the repository-level `sensorsearch.toml` is maintained. The wheel build
copies that exact file to `rdmo_sensorsearch/sensorsearch.toml`; do not maintain
a second package-local source copy.

`testing/fixtures/sensorsearch-plugin-dev.toml` is deliberately different: it is
a complete, generated **test/example-only** profile for the independently
namespaced `testing/catalogs/example_catalog_sensorsearch.xml`. It is not packaged or loaded
by production. Regenerate both assets with
`python testing/tools/generate_plugin_dev_assets.py` after changing the original
catalog or the production baseline.

## Named backend definitions and migration

This schema replaces the former inline connection layout. There is one
`[[backends]]` definition per installation. `name` is configuration identity;
`device_id_prefix` and `configuration_id_prefix` are persisted namespaces.
Renaming a backend and updating its references does not change stored IDs.
Prefixes must be globally unique and contain neither `:` nor `||`.

```toml
[[backends]]
name = "gfz"
type = "sms"
base_url = "https://sensors.gfz.de/backend/api/v1"
device_id_prefix = "gfzsms"
configuration_id_prefix = "gfzcfg"
[backends.settings]
static_location_end_tolerance_seconds = 120
incomplete_mount_chain_policy = "direct_device_offset"

[[DeviceSearchProvider.providers.SensorManagementSystemDeviceProvider]]
backend = "gfz"
text_prefix = "GFZ Sensor"

[[handlers.SensorManagementSystemDeviceHandler.instances]]
backend = "gfz"
```

`type` selects `sms`, `o2a`, or `gipp`. The `settings` table has a distinct
validated type for each backend. SMS uses its API root as `base_url`; O2A uses
its origin and separate search/API templates; GIPP uses its instruments root.
See the maintained TOML for all five installation definitions.

SMS optionally declares `[backends.auth]` with `source = "sms_user_token"`.
Omitting it selects the same existing resolver. Tokens remain request-specific;
TOML contains no credentials. O2A and GIPP remain anonymous. This field records
the existing authentication mechanism and does not introduce new strategies.

Migrate an existing override once:

1. Gather each installation's root URL and existing device/configuration
   namespaces into a top-level backend definition. Keep the namespace values
   exactly, including `gfzsms`, `gfzcfg`, and other existing prefixes.
2. Replace each provider's `id_prefix` and `base_url` with `backend = "name"`.
   Move query/endpoint templates into the appropriate backend settings table.
   Keep labels, result limits, option templates, and O2A query criteria with
   providers.
3. Replace handler `backends`/`backend_defaults` with named `instances`.
   Move endpoint overrides and API policies into backend-specific settings.
   Keep catalog mappings, capability flags, output formatting, and member
   presentation with consumers. Member namespace overrides become the backend's
   declared device namespace.
4. Consolidate SMS tolerance and incomplete-chain policies once per installation.
   If former consumers used different policies, select the intended shared
   policy explicitly before deployment.
5. Validate with `PluginConfig.from_mapping(tomllib.load(file))` (use `tomli`
   on Python 3.10), update the plugin and TOML together, then restart RDMO.

The runtime accepts only the new schema. Old tables report migration guidance;
there is no permanent compatibility parser. Project values and catalog URIs
require no migration. Configuration defaults are resolved during parsing;
assembly receives immutable typed objects.

## Provider aggregators

### `[DeviceSearchProvider]`

| Setting | Meaning |
| --- | --- |
| `min_search_len` | Minimum number of typed characters before remote device providers are queried. |
| `filter_sms_devices_by_selected_configuration` | When `true`, SMS device search is restricted to the SMS backend matching a selected configuration. Leave `false` when manual searches should cover all SMS instances. |

Each `[[DeviceSearchProvider.providers.<ProviderClass>]]` entry enables one device
source. Multiple entries of the same class are allowed. Common provider fields
are `backend`, `text_prefix`, and `max_hits`. The referenced backend supplies
connection settings and the correct resource namespace.

The example enables:

- `O2ARegistryItemProvider`;
- three `SensorManagementSystemDeviceProvider` instances for GFZ, KIT, and UFZ;
- `GIPPInstrumentProvider`.

Each provider/backend binding is unique. A matching handler must reference the
same backend and resource capability.

### `[ConfigurationSearchProvider]`

`min_search_len` has the same meaning for configuration and mission search.
Each `[[ConfigurationSearchProvider.providers.<ProviderClass>]]` entry enables a
configuration source. The example uses three SMS configuration providers and
one O2A mission provider.

For SMS, keep configuration and device prefixes paired:

| Configuration prefix | Device prefix | Backend |
| --- | --- | --- |
| `gfzcfg` | `gfzsms` | GFZ SMS |
| `kitcfg` | `kitsms` | KIT SMS |
| `ufzcfg` | `ufzsms` | UFZ SMS |

## Project-local providers

### `[ProjectConfigurationDevicesProvider]`

Each `[[ProjectConfigurationDevicesProvider.catalogs]]` entry selects an
attribute whose project values become device options. In the Earth Sensor
catalog it is the selected-devices attribute. Use `catalog_uris` for one or
more catalogs, or omit it for a wildcard mapping.

### `[ProjectDataCollectionDevicesProvider]`

This section has the same catalog scoping and `source_attribute_uri` setting,
but supplies the data-collection device optionset. It can reuse the same source
as `ProjectConfigurationDevicesProvider`.

## `[DataCollectionVariableSync]`

`[[DataCollectionVariableSync.catalogs]]` enables automatic variable and unit
rows for selected data-collection devices. `catalog_uris` must explicitly
select one or more catalogs. Omitted or empty scope is rejected for this section.

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

## `[DeviceDetailSync]`

`[[DeviceDetailSync.catalogs]]` controls the URIs that identify repeated device
detail blocks and SMS mount metadata. It uses `catalog_uris` like
other scoped tables; an exact match wins over a wildcard entry. The packaged
profile is the Earth Sensor baseline, whose concrete elements are in the
[catalog map](earth-sensor-catalog.md). All fields are required per profile:

| Setting | Purpose |
| --- | --- |
| `device_details_page_uri`, `device_optional_info_page_uri` | Pages whose values make up a device detail collection and its optional detail page. |
| `configuration_collection_attribute_uri` | Repeated configuration root used to associate device blocks with their configuration. |
| `device_link_attribute_uri`, `usage_technology_attribute_uri` | Fields used to detect stale device metadata. |
| `instrument_start_attribute_uri`, `instrument_end_attribute_uri` | Scoped deployment-period fields. |
| `instrument_location_amsl_attribute_uri`, `surface_offset_z_attribute_uri`, `site_name_attribute_uri` | SMS-derived mount-location fields. |
| `serial_number_attribute_uri` | Device serial-number field used when selecting an SMS mount action. |

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
| `replace_existing_collections` | Rebuild configuration device membership instead of preserving existing collections. Used by an optional explicit SMS membership-filter action. |
| `require_configuration_period` | Request a validated period from a handler that supports optional membership filtering. |
| `input_attribute_uris` | User-owned input fields that affect this action. Changes clear stale feedback but do not execute the action. |

The authoritative deployment configuration has no period-filter action. A
future SMS catalog extension must define a separate apply trigger, list its
separate filter input attributes in `input_attribute_uris`, set both flags
above, and explicitly enable the matching handler settings. Catalog presence
alone never changes selection behavior.

## Handler structure

Handlers turn a selected provider option into RDMO answers. Their common layout
is:

```toml
[handlers.SomeHandler]

[[handlers.SomeHandler.instances]]
backend = "example"

[handlers.SomeHandler.defaults]
# settings shared by all catalog mappings

[[handlers.SomeHandler.catalogs]]
catalog_uris = ["https://example.org/catalog"]
search_attribute_uri = "https://example.org/attributes/search"
managed_attribute_uris = ["https://example.org/attributes/output"]

[handlers.SomeHandler.catalogs.attribute_mapping]
"backend.path" = "https://example.org/attributes/output"
```

`defaults` are merged into each catalog entry. A catalog entry can override a
default. Omitting `catalog_uris` creates a wildcard catalog
mapping. Prefer explicit scope when two catalogs use different attribute
semantics.

Each handler `instances` entry references a named backend. SMS configuration
instances carry `device_text_prefix`; O2A mission instances may carry
`item_text_prefix` and `item_text_template`. These labels describe application
usage and are independent of persisted namespaces.

Provider `provider_defaults` supplies presentation and query criteria for its
`providers` entries. Each instance overrides these defaults. Catalog mappings
merge handler `defaults` with catalog-specific settings during parsing; mapping
entries are merged by JMESPath key. Connection fields are rejected in consumer
tables so their source is unambiguous.

Common handler settings are:

| Setting | Meaning |
| --- | --- |
| `search_attribute_uri` | Search attribute monitored for a selected backend option. |
| `attribute_mapping` | JMESPath-to-RDMO-attribute mapping. Array results create indexed values. |
| `managed_attribute_uris` | Additional fields authoritatively owned by the handler. |
| `materialize_device_details` | Allows selected devices to be materialized into repeated detail collections. |
| `device_link_attribute_uri` | Target for a backend or frontend record link. |
| `catalog_uris` | Catalog scope; omitted means wildcard. |

### `O2ARegistryItemHandler`

This handler fetches one O2A item. Its mapping can read names, type,
manufacturer, model, serial number, citation, parameters, units, and contacts.
`item_api_link_template` and `item_frontend_link_template` configure record
links.

### `SensorManagementSystemDeviceHandler`

This handler fetches one SMS device. Its `instances` reference shared SMS
definitions. API settings below belong to `backends.settings` or its `device`
subtable; capability flags remain catalog settings:

| Setting | Meaning |
| --- | --- |
| `backend_link_marker` | Recognizes and normalizes SMS backend links. |
| `device_mount_actions_url` | Endpoint template used for device deployment periods and mount context. |
| `supports_mount_period_lookup` | Enables SMS mount-action enrichment for device detail blocks. |
| `static_location_end_tolerance_seconds` | Maximum accepted end-time difference between an overlapping static-location action and a device mount. The library default is `0` (strict). |
| `incomplete_mount_chain_policy` | Controls question 2.53 when a parent action is unavailable: `strict` leaves it empty; `direct_device_offset` uses only the direct device action's numeric `offset_z`. |

SMS mount enrichment can derive a device's active period, site name, and
vertical position. See [Operations and limitations](operations-and-limitations.md#sms-location-height-and-depth).

The derived mapping input `sms_owner_organizations` contains the distinct,
trimmed `attributes.organization` names of contacts linked to device roles
whose `role_name` is exactly `Owner`. The handler joins contacts by resource
type and ID; other contacts remain available to responsible-person mappings.
Contact roles are paginated with 100 records per page and a 100-page limit,
using the configured backend and the same authentication as the device request.
Endpoint overrides for `contact_url` can use `{base_url}`, `{id}`, `{page_size}`,
and `{page_number}`. Keep the page placeholders to support APIs that omit a
next-page link. Relative next-page links resolve against the contact endpoint.

```toml
[handlers.SensorManagementSystemDeviceHandler.catalogs.attribute_mapping]
"sms_owner_organizations" = "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/owner"
```

This exact mapping key opts its configured target into backend-authoritative
scalar synchronization, rather than the normal array-to-collection behavior.
Use a single optional
`select_creatable` question with `value_type=option` and provider `ror` for the
target. A successful metadata refresh replaces the complete current Owner
answer with the distinct SMS Owner organizations, joined using `; ` in backend
role order. Each organization name is trimmed and treated as one atomic name;
embedded semicolons are preserved. Matching is exact after trimming, without
fuzzy institution matching. A successful response without usable Owner names
clears the answer. Failed or malformed contact requests do not persist
device metadata; unresolved Owner contact references produce nonfatal feedback.
Backend text is stored as free text with `value_type=option`. Its previous ROR
identifier and option are cleared even when the visible organization name
already matches, because SMS supplies organization names rather than ROR IDs.
Snapshot answers remain unchanged.
Normal selection clearing and device-block deletion still clear managed data.

Update both exact and wildcard catalog profiles if they share this field, then
regenerate the development catalog and profile. Existing deployment overrides
must add the mapping and import the updated owner question; a plugin upgrade
alone does not change an already imported catalog.

### `SensorManagementSystemConfigurationHandler`

This handler fetches one SMS configuration and its mounted devices.

| Setting | Meaning |
| --- | --- |
| `configuration_collection_attribute_uri` | Repeated configuration collection root. |
| `selected_devices_attribute_uri` | Attribute storing selected or mounted devices. |
| `selected_devices_page_uri` | Page containing the selected device set. |
| `device_collection_attribute_uri` | Repeated device-detail collection root. |
| `frontend_link_attribute_uri` | Configuration link target. |
| `latitude_attribute_uri`, `longitude_attribute_uri` | Configuration static-location targets. |
| `membership_filter_enabled` | Explicit opt-in for a future SMS-only historical membership-filter extension. Omit for baseline catalogs. |
| `membership_filter_start_attribute_uri`, `membership_filter_end_attribute_uri` | Separate user-owned filter inputs. They must be configured together when the extension is enabled and must not reuse question set 2.1.4. |
| `device_text_prefix` | Converts a mounted SMS device into an option understood by the matching device handler. |
| `static_location_end_tolerance_seconds` | Same bounded static-location fallback used by the SMS device handler. Declared once in `backends.settings`. |
| `incomplete_mount_chain_policy` | Same `strict` or `direct_device_offset` policy used by the SMS device handler. |

The configuration provider and handler reference the same named backend.
Its `device_id_prefix` supplies the namespace of configuration members, and a
matching device handler must reference that same backend.
The supplied `sensorsearch.toml` enables a 120-second location tolerance and
the `direct_device_offset` fallback for both handlers. Invalid policies and
negative or non-integer tolerance values are rejected while loading the
configuration.

### `O2ARegistryMissionHandler`

This handler treats an O2A mission as a configuration and its items as member
devices. The configuration collection, selected-devices attribute and page,
device collection, and frontend link settings have the same catalog meaning as
for SMS.

`mission_url`, `mission_items_url`, and `item_url` control API requests.
`mission_item_page_size` limits the page size. These API settings live in
`backends.settings.mission`; the member namespace is the backend's
`device_id_prefix`. `mission_start_date_path`, `mission_end_date_path`, and
`date_mapping_paths` describe dates present in the mission API. Their mapped
targets are the backend-owned question set 2.1.4 answers, and materialized
mission items inherit that mission period. O2A membership-filter settings are
rejected because the Registry has no comparable historical mount model.

### `GIPPInstrumentHandler`

This handler maps GIPP records, including instrument code, category,
manufacturer, serial number, PID, and contact. It participates in device search
and detail synchronization but not configuration or mission membership.

## Catalog scope and wildcard mappings

The example configuration contains wildcard catalog entries so the same Earth
Sensor attribute scheme can be reused by compatible catalogs. This is
convenient but broad: a handler can run in any catalog containing its search
attribute. To isolate behavior, add `catalog_uris` to every
handler and project-local provider mapping.

When two matching catalog entries could apply, avoid relying on file order.
Give each catalog one unambiguous mapping for a handler.

## Complete setting index

This index is exhaustive for the validated TOML schema. `catalog_uris` is
allowed on every `catalogs` entry. `attribute_mapping` is a
table of JMESPath source expressions to RDMO attribute URI strings. URL fields
are templates where documented placeholders such as `{base_url}` and `{id}`
are substituted by the handler.

| Settings | Accepted by | Purpose |
| --- | --- | --- |
| `backend`, `text_prefix`, `max_hits` | provider entries | Named connection, displayed label, and result cap. |
| `name`, `type`, `base_url`, `device_id_prefix`, `configuration_id_prefix`, `settings`, `auth` | backend definitions | Configuration identity, backend discriminator, connection root, namespaces, and typed API/auth settings. |
| `source` | SMS `auth` | Existing `sms_user_token` resolver. |
| `instances` | handlers | Named backend bindings. |
| `option_id`, `option_text` | SMS/GIPP and O2A mission providers | Option ID and display templates. |
| `device_search_url`, `configuration_search_url`, `device_query_url`, `configuration_query_url` | SMS backend settings | Resource and query templates. |
| `api_url`, `item_search_url`, `mission_search_url`, `mission_query_url` | O2A backend settings | Separate API and search templates. |
| `metadata_url` | GIPP backend settings | Metadata API root template. |
| `where_template`, `sorts`, `offset` | O2A mission provider | Registry query filter, ordering, and result offset. |
| `instruments_url` | GIPP backend settings | GIPP instruments endpoint. |
| `item_url`, `contacts_url`, `parameters_url`, `units_url` | O2A `settings.item` | Endpoints used to enrich one Registry item. |
| `item_api_link_template`, `item_frontend_link_template` | O2A `settings.item` | API and browser link templates for an item. |
| `device_url`, `contact_url` | SMS `settings.device` | Endpoints for one SMS device and its contacts. |
| `device_mount_actions_url` | SMS `settings.device` | Device mount-action endpoint used for period enrichment. |
| `configuration_device_mount_actions_url`, `configuration_platform_mount_actions_url`, `configuration_static_location_actions_url` | SMS `settings.device` | Configuration-scoped endpoints used to resolve mount location. |
| `backend_link_marker` | SMS backend settings | API path fragment replaced when forming a browser link. |
| `configuration_url`, `device_mount_action_url`, `platform_mount_actions_url`, `mounting_action_timepoints_url`, `static_location_actions_url` | SMS `settings.configuration` | Endpoints used to fetch a configuration, members, time points, and locations. |
| `device_mount_actions_url` | SMS `settings.configuration` | Endpoint for a configuration's device mount actions. |
| `device_mount_action_page_size`, `platform_mount_action_page_size`, `static_location_action_page_size`, `max_collection_pages` | SMS `settings.configuration` | Remote pagination limits. |
| `configuration_self_link_path`, `frontend_link_suffix` | SMS `settings.configuration` | Response link path and browser-link suffix. |
| `configuration_start_date_path`, `configuration_end_date_path` | SMS configuration catalogs | Date mapping paths. |
| `device_text_prefix` | SMS configuration handler instance | Member display label. |
| `location_attribute_uri`, `latitude_attribute_uri`, `longitude_attribute_uri` | SMS configuration handler | Optional location target and latitude/longitude targets. |
| `mission_url`, `mission_items_url`, `item_url` | O2A `settings.mission` | Endpoints for a mission, its items, and one item. |
| `mission_item_page_size`, `max_collection_pages` | O2A `settings.mission` | Mission-member page size and maximum pages. |
| `item_text_prefix`, `item_text_template` | O2A mission handler instance | Mission-member display text. |
| `mission_start_date_path`, `mission_end_date_path`, `date_mapping_paths`, `datetime_output_format` | O2A mission handler | Mission period source paths, alternate date paths, and output formatting. |
| `api_link_template`, `frontend_link_template` | O2A `settings.mission` | API and browser link templates for a mission. |
| `json_url` | GIPP backend settings | Endpoint returning an instrument record. |
| `materialize_device_details`, `device_collection_attribute_uri`, `device_link_attribute_uri` | device handlers | Enable repeated device blocks, choose their root attribute, and choose the link output. |
| `supports_mount_location_lookup`, `supports_mount_period_lookup` | device handlers | Explicitly enable SMS mount-location or deployment-period enrichment. |
| `static_location_end_tolerance_seconds`, `incomplete_mount_chain_policy` | SMS backend settings | Bound static-location matching; use `strict` or `direct_device_offset` for incomplete mount chains. |
| `configuration_collection_attribute_uri`, `selected_devices_attribute_uri`, `selected_devices_page_uri`, `frontend_link_attribute_uri`, `api_link_attribute_uri` | configuration/mission handlers | Repeated configuration root, member devices, their page, and configuration link targets. |
| `membership_filter_enabled`, `membership_filter_start_attribute_uri`, `membership_filter_end_attribute_uri` | SMS configuration handler | Explicit opt-in and paired user-owned historical-membership inputs. |

Nested backend tables are `device` and `configuration` for SMS, and `item` and
`mission` for O2A. They hold only that backend type's endpoint settings.
