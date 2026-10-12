<!--
SPDX-FileCopyrightText: 2023 - 2024 Hannes Fuchs (GFZ) <hfuchs@gfz-potsdam.de>
SPDX-FileCopyrightText: 2023 - 2024 Helmholtz Centre Potsdam - GFZ German Research Centre for Geosciences
SPDX-FileCopyrightText: 2025 - 2026 RDMO Community and individual contributors
SPDX-License-Identifier: Apache-2.0
-->

# RDMO Sensor Search option set plugin

This option set plugin allows you to query several sensor registries at the
same time. Additional questions can be filled in automatically with information
from the sensor registries. To use this feature an attribute mapping must be
configured.

The following sensor registries are currently implemented:
- [Geophysical Instrument Pool Potsdam (GIPP)](https://gipp.gfz.de/)
- [O2A Registry](https://registry.o2a-data.de/)
- [Sensor Management System](https://codebase.helmholtz.cloud/hub-terra/sms/service-desk/-/wikis/home)

For every integration it is possible to define multiple instances in the
configuration. This is especially necessary for the Sensor Management System
(SMS), since there are four productive instances.

This plugin is based on the [RDMO Sensor AWI option set plugin](https://github.com/hafu/rdmo-sensor-awi)
with a complete refactoring, to allow configuration and easy extension with
more registries if needed.

## Documentation for catalog editors

The [`docs`](docs/index.md) directory documents how RDMO catalog elements and
`sensorsearch.toml` work together. Start with the
[catalog editor guide](docs/catalog-editor-guide.md), use the
[configuration reference](docs/configuration-reference.md) for TOML settings,
and consult the [Earth Sensor URI map](docs/earth-sensor-catalog.md) to find the
exact pages, questions, attributes, optionsets, and conditions in
`testing/catalogs/earth-sensor+original.xml`. Runtime costs and backend constraints are
covered in [operations and limitations](docs/operations-and-limitations.md).
The [developer architecture](docs/developer-architecture.md) explains the
internal service, handler, and RDMO signal boundaries.

## Setup

Install the plugins in your RDMO virtual environment using pip (directly from
GitHub):

```bash
pip install git+https://github.com/rdmorganiser/rdmo-plugins-sensorsearch
```

Or when editing the code you can put the code a folder beneath your RDMO
installation and install it with:

```bash
pip install -e ../rdmo-plugins-sensorsearch
```

For development, install the test dependencies and run pytest with:

```bash
pip install -e ".[dev]"
pytest -c testing/pytest-unit.ini
```

The focused Django signal tests use RDMO's real models and transaction hooks in
a separate test environment so the lightweight unit suite can continue to run
without a host installation:

```bash
pip install -e ".[django-test]"
pytest -c testing/pytest-django.ini
```

Add the plugin to the `OPTIONSET_PROVIDERS` in `config/settings/local.py`:

```python
OPTIONSET_PROVIDERS = [
    ('sensorsearch_devices', _('Device Search'), 'rdmo_sensorsearch.providers.DeviceSearchProvider'),
    ('sensorsearch_configurations', _('Configuration Search'), 'rdmo_sensorsearch.providers.ConfigurationSearchProvider'),
    ('sensorsearch_project_configuration_devices', _('Project Configuration Devices'), 'rdmo_sensorsearch.providers.ProjectConfigurationDevicesProvider'),
    ('sensorsearch_project_data_collection_devices', _('Project Data Collection Devices'), 'rdmo_sensorsearch.providers.ProjectDataCollectionDevicesProvider'),
    ('sensorsearch_interview_page_refresh', _('Interview Page Refresh'), 'rdmo_sensorsearch.providers.InterviewPageRefreshProvider'),
]
```

Add the plugin to the `INSTALLED_APPS` in `config/settings/local.py`:

```python
INSTALLED_APPS = ['rdmo_sensorsearch'] + INSTALLED_APPS
```

If SMS requests should reuse the currently logged-in user's access token in
post-save synchronization, add the auth context middleware after Django's
session and authentication middleware:

```python
MIDDLEWARE = [
    # ...
    'rdmo_sensorsearch.auth.SensorSearchAuthContextMiddleware',
]
```

After restarting RDMO, `Device Search` should be selectable as a provider
option for option sets. If you enable the additional provider entries, a
separate `Configuration Search` provider, a project-local reuse provider for
mounted devices, and a data collection devices provider are available as well.
The data collection devices provider uses the same project-local value source
for data collection instrument selection questions. The no-op `Interview Page
Refresh` provider can be attached to metadata refresh trigger questions so
RDMO refetches the current interview page after saving the trigger.

The importable [`testing/catalogs/example_catalog_sensorsearch.xml`](testing/catalogs/example_catalog_sensorsearch.xml)
is a complete, independently namespaced (`example.com` / `plugin-dev`) mirror
of the Earth Sensor catalog. Its matching test/example-only profile lives at
[`testing/fixtures/sensorsearch-plugin-dev.toml`](testing/fixtures/sensorsearch-plugin-dev.toml);
do not copy those entries into the packaged production configuration.

## Configuration

With `sensorsearch.toml` the providers which should be used can be configured. The
`DeviceSearchProvider` aggregates the results of the configured providers.
`ConfigurationSearchProvider` works the same way for configuration backends.

To automatically fill out questions with results of the matching backend record,
attribute mapping for the specific catalog(s) must be configured in the
configuration file.

The repository-level `sensorsearch.toml` is the single maintained deployment
configuration and is copied into the installed package when a wheel is built.
Its structure and cross-references are validated when it is first loaded; an
invalid or misspelled setting prevents plugin initialization and reports its
TOML path. The location can be overwritten with
`SENSORSEARCH_CONFIG_FILE_PATH` in `config/settings/local.py` or with an
environment variable of the same name. Restart the RDMO application processes
after changing the configuration because the validated model is cached.

Define connections once in top-level `[[backends]]` entries; providers and
handler `instances` reference their names. Use the installation definitions in
[sensorsearch.toml](sensorsearch.toml) with the examples below. Existing overrides
need the documented [one-time schema migration](docs/configuration-reference.md#named-backend-definitions-and-migration).
Stored external IDs and catalog mappings keep their meaning.

### Configuration: Providers

```toml
[DeviceSearchProvider]
min_search_len = 3
# Optional: restrict SMS device searches to the SMS backend that matches a
# selected configuration in the current project. Leave false for manual
# instrument searches that should query all configured SMS instances.
filter_sms_devices_by_selected_configuration = false

[DeviceSearchProvider.provider_defaults.SensorManagementSystemDeviceProvider]
max_hits = 20

[ConfigurationSearchProvider]
min_search_len = 3

[ProjectConfigurationDevicesProvider]
[[ProjectConfigurationDevicesProvider.catalogs]]
# Omitting catalog_uris makes this mapping available in all catalogs.
source_attribute_uri = "http://example.com/terms/domain/configuration-set/member-sensor"

[ProjectDataCollectionDevicesProvider]
[[ProjectDataCollectionDevicesProvider.catalogs]]
# Omitting catalog_uris makes this mapping available in all catalogs.
source_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/selected-devices"

[MetadataRefresh]
configuration_search_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-search"
device_search_attribute_uri = "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/keywords"

[[MetadataRefresh.actions]]
kind = "configuration"
trigger_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-configuration"
status_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-status"
message_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-message"
timestamp_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-timestamp"

[[MetadataRefresh.actions]]
kind = "configuration"
trigger_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/apply-date-range"
status_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-status"
message_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-message"
timestamp_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-timestamp"
replace_existing_collections = true
require_configuration_period = true
input_attribute_uris = [
    "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-start-datetime",
    "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configurations-end-datetime",
]

[[MetadataRefresh.actions]]
kind = "device"
trigger_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/refresh-device"
status_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/refresh-status"
message_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/refresh-message"
timestamp_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/refresh-timestamp"

[[MetadataRefresh.actions]]
kind = "all_configurations"
trigger_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/metadata-refresh/configurations/trigger"
status_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/metadata-refresh/configurations/status"
message_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/metadata-refresh/configurations/message"
timestamp_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/metadata-refresh/configurations/timestamp"

[[MetadataRefresh.actions]]
kind = "all_devices"
trigger_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/metadata-refresh/devices/trigger"
status_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/metadata-refresh/devices/status"
message_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/metadata-refresh/devices/message"
timestamp_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/metadata-refresh/devices/timestamp"

[[DeviceSearchProvider.providers.O2ARegistryItemProvider]]
backend = "o2a"

[[DeviceSearchProvider.providers.SensorManagementSystemDeviceProvider]]
backend = "gfz"
text_prefix = "GFZ Sensor"

[[DeviceSearchProvider.providers.SensorManagementSystemDeviceProvider]]
backend = "kit"
text_prefix = "KIT Sensor"

[[DeviceSearchProvider.providers.SensorManagementSystemDeviceProvider]]
backend = "ufz"
text_prefix = "UFZ Sensor"

[[DeviceSearchProvider.providers.GIPPInstrumentProvider]]
backend = "gipp"

[[ConfigurationSearchProvider.providers.SensorManagementSystemConfigurationProvider]]
backend = "gfz"
text_prefix = "GFZ Cfg"

[[ConfigurationSearchProvider.providers.O2ARegistryMissionProvider]]
backend = "o2a"
text_prefix = "O2A M"
where_template = "name=ILIKE=\"*{query}*\""

[handlers.SensorManagementSystemConfigurationHandler]
[[handlers.SensorManagementSystemConfigurationHandler.instances]]
backend = "gfz"
[handlers.SensorManagementSystemConfigurationHandler.defaults]
search_attribute_uri = "http://example.com/terms/domain/configuration-set/configuration-search"
configuration_collection_attribute_uri = "http://example.com/terms/domain/configuration-set"
selected_devices_attribute_uri = "http://example.com/terms/domain/configuration-set/member-sensor"
frontend_link_attribute_uri = "https://rdmorganiser.github.io/terms/domain/project/dataset/uri"
api_link_attribute_uri = "https://rdmorganiser.github.io/terms/domain/project/dataset/source"
location_attribute_uri = "https://rdmorganiser.github.io/terms/domain/project/dataset/spatial"
[handlers.SensorManagementSystemConfigurationHandler.defaults.attribute_mapping]
"data.id" = "https://rdmorganiser.github.io/terms/domain/project/dataset/identifier"
"data.attributes.label" = "https://rdmorganiser.github.io/terms/domain/project/dataset/description"
"data.attributes.project" = "https://rdmorganiser.github.io/terms/domain/project/dataset/documentation"
"data.attributes.persistent_identifier" = "https://rdmorganiser.github.io/terms/domain/project/dataset/id"
"data.attributes.description" = "https://rdmorganiser.github.io/terms/domain/project/dataset/annotation"
"data.links.self" = "https://rdmorganiser.github.io/terms/domain/project/dataset/source"
[[handlers.SensorManagementSystemConfigurationHandler.catalogs]]
catalog_uris = ["http://example.com/terms/questions/example-configurations-earth-sensor"]

[handlers.O2ARegistryMissionHandler]
[[handlers.O2ARegistryMissionHandler.instances]]
backend = "o2a"
[handlers.O2ARegistryMissionHandler.defaults]
search_attribute_uri = "http://example.com/terms/domain/configuration-set/configuration-search"
configuration_collection_attribute_uri = "http://example.com/terms/domain/configuration-set"
selected_devices_attribute_uri = "http://example.com/terms/domain/configuration-set/member-sensor"
device_collection_attribute_uri = "http://example.com/terms/domain/instruments/id"
item_text_template = "{configuration} {prefix}({item_id}): {name}{serial}"
[handlers.O2ARegistryMissionHandler.defaults.attribute_mapping]
"description" = "http://example.com/terms/domain/configuration-set/description"
[[handlers.O2ARegistryMissionHandler.catalogs]]
catalog_uris = ["http://example.com/terms/questions/example-configurations-earth-sensor"]
# These are user-entered filtering inputs, not mission metadata outputs.
period_start_attribute_uri = "http://example.com/terms/domain/configuration-set/start"
period_end_attribute_uri = "http://example.com/terms/domain/configuration-set/end"
```

This configures all available providers with three SMS instances to query. The
`DeviceSearchProvider` will only query the configured providers if at least three
characters are entered.

Provider labels follow a common `<backend> <entity>(<id>): <label>` convention:

- SMS devices: `GFZ Sensor(2212): ...`, `KIT Sensor(327): ...`, or
  `UFZ Sensor(823): ...`
- O2A items: `O2A Item(3581): ...`
- GIPP instruments: `GFZ GIPP Instrument(1): ...`
- SMS configurations: `GFZ Cfg(12): ...`, `KIT Cfg(49): ...`, or
  `UFZ Cfg(310): ...`
- O2A missions: `O2A M(30): ...`

Devices imported through a configuration retain their compact relationship in
the Device Set, with the configuration or mission first for easier scanning,
for example `KIT Cfg(49) KIT Sensor(327): ...` or
`O2A M(30) O2A Item(4152): ...`. Device Details tabs use the complete configuration
label and omit the repeated compact relationship, for example
`KIT Cfg(49) KIT Sensor(327): ...`.

Selecting a backend configuration or mission also prefixes the shared
configuration tab while preserving its user-defined alias. For example,
`o2a-test` becomes `O2A M(30): o2a-test`. Replacing the selected backend changes
only the managed prefix, while clearing it restores `o2a-test`. Since the
Configuration/Mission and Device Set pages use the same collection attribute,
the synchronized label identifies the same tab on both pages.

By default, SMS device search is not restricted by configurations already
selected in the project, so manual instrument searches query all configured SMS
instances. Set `filter_sms_devices_by_selected_configuration = true` in
`[DeviceSearchProvider]` only if device searches should be narrowed to the SMS
backend corresponding to an already selected configuration, such as
`kitcfg -> kitsms`.

When RDMO initializes an asynchronous select containing an existing answer, it
requests options using the complete stored answer text. The aggregate providers
resolve an exact match from current project values when its external ID belongs
to an enabled backend. These initialization requests therefore avoid backend
authentication and external API calls. Partial or otherwise unmatched searches
continue to query the configured backends normally.

Every remote provider declares `backend = "name"`. Its referenced definition
supplies connection settings and the resource's external-ID namespace. SMS
providers also declare `text_prefix`; O2A and GIPP use their existing label
defaults unless overridden. `max_hits` defaults to `10`.

The provider label is displayed with search results. The backend's
`device_id_prefix` or `configuration_id_prefix` identifies the namespace stored
in `external_id` and used to route metadata requests. These persisted values
are independent of the backend name.

To avoid repeating shared provider settings, provider defaults can be declared
once per aggregate provider and backend provider class:

```toml
[DeviceSearchProvider.provider_defaults.SensorManagementSystemDeviceProvider]
max_hits = 20
```

These defaults are merged into every
`[[DeviceSearchProvider.providers.SensorManagementSystemDeviceProvider]]` entry. Any value
declared on the concrete provider entry still overrides the default.

### Configuration: SMS authentication

SMS device and configuration providers, plus the corresponding handlers, reuse
an available bearer token for SMS backend requests. The token is sent as:

```text
Authorization: Bearer <access-token>
```

Token resolution is intentionally conservative:

- If `SENSORSEARCH_AUTH_TOKEN_RESOLVER` is configured, it is used first. The
  resolver can be a callable or dotted import path accepting `user` and
  `request` keyword arguments.
- If the auth context middleware is enabled, session keys from
  `SENSORSEARCH_AUTH_SESSION_TOKEN_KEYS` are checked next. Without explicit
  keys, a single unambiguous `access_token` or `*.access_token` session value is
  used.
- If django-allauth social tokens are available for the user, a single
  unexpired token is used. If several social tokens exist, configure
  `SENSORSEARCH_AUTH_SOCIALACCOUNT_PROVIDERS`, for example:

```python
SENSORSEARCH_AUTH_SOCIALACCOUNT_PROVIDERS = ['helmholtz-aai']
```

If no unambiguous token can be resolved, the plugin keeps making public SMS
requests without an `Authorization` header.

The `ProjectConfigurationDevicesProvider` and
`ProjectDataCollectionDevicesProvider` are different. They do not query a
remote backend, but read project-local values which were materialized by a
configuration handler after a configuration was selected. For the Earth-Sensor
catalog, `ProjectDataCollectionDevicesProvider` reads the selected devices from
`https://rdmo.nfdi4earth.de/terms/domain/configuration-set/selected-devices`.

Metadata refresh actions are ordinary Yes/No catalog questions. Only the `Yes`
value triggers an action, and the plugin resets it to `No` after completion
while its own value signals are muted. Four action kinds are supported:

- `configuration` refreshes the backend configuration in the trigger value's
  exact `set_prefix` and `set_index` scope;
- `device` refreshes the backend device in the trigger value's exact
  `set_prefix` and `set_index` scope;
- `all_configurations` refreshes every backend configuration stored in the
  project;
- `all_devices` refreshes every materialized device detail block stored in the
  project.

More than one action can use the `configuration` kind. The Earth Sensor catalog
uses a second configuration action to apply user-entered start and end values
and replace device membership with the matching period. Free-text date changes
do not call a backend. See the
[date-range workflow](docs/catalog-editor-guide.md#optional-date-range-workflow)
and [exact Earth Sensor date URIs](docs/earth-sensor-catalog.md#user-entered-configuration-period).

Place the `configuration` and `device` triggers directly on their respective
collection pages. Place the two bulk triggers on a non-collection maintenance
page. Feedback attributes are optional scalar text questions in the same scope
as their trigger. Status is stored as `success`, `partial`, or `failed`; the
message contains the refreshed target or aggregate counts and backend errors.
Successful single-configuration messages also report how many associated
devices were refreshed. The timestamp uses local server time.

Each user-triggered refresh deduplicates identical backend GET requests for the
duration of that action. This is especially relevant for shared reference
endpoints such as the O2A unit list and for devices reused by more than one
configuration. The cache is shared with the bounded device-fetch workers,
returns isolated response copies to handlers, and is discarded as soon as the
refresh finishes.

The selected-device collection can be represented either by one collection
Question or by a collection QuestionSet. The plugin resolves the active shape
from `selected_devices_page_uri`. Initial configuration or mission selection
imports the complete backend device list using that shape and removes values
using the opposite shape in the same configuration scope. This allows an
existing project to be reused after changing between the two catalog
representations.

User-triggered `configuration` and `all_configurations` refreshes treat the
current Device Set as user-managed input. They refresh configuration metadata
without replacing its membership, then refresh device details only for devices
currently selected in that configuration scope. Consequently, manually removed
devices are not reintroduced, manually added backend devices are included, and
obsolete device-detail blocks are removed. Preserved membership is also moved
to the active collection layout when the catalog representation has changed,
and legacy device-first labels are normalized to the configuration-first
convention during the refresh.
Duplicate selected rows with the same device `external_id` are collapsed to
their first row. Failed configuration requests leave the Device Set unchanged.

Removing a device from the Device Set uses a targeted local cleanup: only that
device's detail block is deleted, without refreshing the remaining devices or
calling an external sensor backend. Adding or changing a selected device still
runs the normal synchronization needed to materialize its detail metadata.

Attach an optionset using `InterviewPageRefreshProvider` to every trigger
question. Its `refresh = True` flag makes RDMO refetch the current page after
the trigger save completes, so the reset trigger and feedback values are shown
without navigating away.

For the Earth-Sensor catalog, selected data collection devices also drive the
parameter list of the following data collection question. When a device is
selected in
`https://rdmorganiser.github.io/terms/domain/project/dataset/collaboration_tools`,
the plugin looks up the device detail values already materialized in section 2
and appends missing parameter name/unit pairs to:

- `https://rdmo.nfdi4earth.de/terms/domain/project/dataset/metadata/dc-variable`
- `https://rdmo.nfdi4earth.de/terms/domain/project/dataset/metadata/dc-unit`

Existing identical parameter name/unit pairs are not added again. Rows generated
by this synchronization are marked with a `sensorsearch:dc-variable:` external
ID. When a device is removed from the data collection device list, generated
parameter rows are removed again if no remaining selected device still provides
that parameter name/unit pair. Manually entered rows and older unmarked rows are
left untouched.

This synchronization is enabled only for catalogs listed under
`DataCollectionVariableSync`. The attribute URI settings are optional when the
catalog uses the defaults shown above:

```toml
[DataCollectionVariableSync]
[[DataCollectionVariableSync.catalogs]]
catalog_uris = [
    "https://rdmo.nfdi4earth.de/terms/questions/earth-sensor-with-refresh-feature-v1",
]
# devices_attribute_uri = "https://rdmorganiser.github.io/terms/domain/project/dataset/collaboration_tools"
# device_collection_attribute_uri = "https://rdmo-sandbox.gfz-potsdam.de/terms/domain/moses/instruments/id"
# parameter_name_attribute_uri = "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/preservation/parameter/name"
# parameter_unit_attribute_uri = "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/preservation/parameter/unit"
# variable_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/project/dataset/metadata/dc-variable"
# unit_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/project/dataset/metadata/dc-unit"
```

O2A Registry missions are exposed through `O2ARegistryMissionProvider`. They
follow the same configuration flow as SMS configurations: selecting a mission
can materialize its items into the configured project-local device collection.
The default search query uses the O2A RSQL form `name=ILIKE="*{query}*"`.

### Configuration: Handlers

Handlers can be used to fill out questions automatically with the use of a
configured attribute mapping. For every provider a handler is implemented,
which can request additional information from the registry to answer questions.

Handler defaults can also be configured once and then reused by multiple
catalogs or even applied as a wildcard mapping for any catalog which uses the
same autocomplete field.

```toml
[handlers.O2ARegistryItemHandler]
[[handlers.O2ARegistryItemHandler.instances]]
backend = "o2a"
[handlers.O2ARegistryItemHandler.defaults]
search_attribute_uri = "http://rdmo-dev.local/terms/domain/sensor/awi/search"
materialize_device_details = true
device_link_attribute_uri = "http://rdmo-dev.local/terms/domain/sensor/device-link"
[handlers.O2ARegistryItemHandler.defaults.attribute_mapping]
"longName" = "http://rdmo-dev.local/terms/domain/sensor/awi/type-name"
"shortName" = "http://rdmo-dev.local/terms/domain/sensor/awi/name"
"serialNumber" = "http://rdmo-dev.local/terms/domain/sensor/awi/serial"

[[handlers.O2ARegistryItemHandler.catalogs]]
catalog_uris = ["http://rdmo-dev.local/terms/questions/sensor-awi-test"]
# optional per-catalog overrides can be added here

[handlers.SensorManagementSystemDeviceHandler]
[[handlers.SensorManagementSystemDeviceHandler.instances]]
backend = "gfz"
[[handlers.SensorManagementSystemDeviceHandler.instances]]
backend = "kit"
[[handlers.SensorManagementSystemDeviceHandler.instances]]
backend = "ufz"
[handlers.SensorManagementSystemDeviceHandler.defaults]
search_attribute_uri = "http://rdmo-dev.local/terms/domain/sensor/awi/search"
[handlers.SensorManagementSystemDeviceHandler.defaults.attribute_mapping]
"data.attributes.long_name" = "http://rdmo-dev.local/terms/domain/sensor/awi/type-name"
"data.attributes.short_name" = "http://rdmo-dev.local/terms/domain/sensor/awi/name"
"data.attributes.serial_number" = "http://rdmo-dev.local/terms/domain/sensor/awi/serial"

[[handlers.SensorManagementSystemDeviceHandler.catalogs]]
catalog_uris = ["http://rdmo-dev.local/terms/questions/sensor-awi-test"]

[handlers.GIPPInstrumentHandler]
[[handlers.GIPPInstrumentHandler.instances]]
backend = "gipp"
[handlers.GIPPInstrumentHandler.defaults]
search_attribute_uri = "http://rdmo-dev.local/terms/domain/sensor/awi/search"
[handlers.GIPPInstrumentHandler.defaults.attribute_mapping]
"Instrument.code" = "http://rdmo-dev.local/terms/domain/sensor/awi/type-name"
"Instrumentcategory.name" = "http://rdmo-dev.local/terms/domain/sensor/awi/name"
"Instrument.serialNo" = "http://rdmo-dev.local/terms/domain/sensor/awi/serial"

[[handlers.GIPPInstrumentHandler.catalogs]]
catalog_uris = ["http://rdmo-dev.local/terms/questions/sensor-awi-test"]
```

Every provider and handler instance references a named backend. Its separate
device/configuration namespaces determine stored IDs; they are independent of
the backend's configuration name. Connection URLs and API policies belong to
typed backend-specific settings.

The `catalogs` configuration is used to identify the catalog(s) where the
attribute mapping should be used to map values from the API response to
attributes of the catalog. It is possible to configure more than one catalog.
- `catalog_uris` lists the catalog URIs where the handler should map values
  to attributes; omission makes the mapping available in all catalogs.
- `search_attribute_uri` is the uri of the question with the option set
  provider used in the catalog
- `managed_attribute_uris` adds attributes to the handler's ownership beyond
  those in `attribute_mapping`. Every successful refresh is authoritative for
  this complete set: returned values are created or updated in place, while
  owned values omitted by the backend are removed. Unmanaged interview values
  are left untouched. Clearing the source question applies the same ownership
  rules with an empty result.
- `materialize_device_details = true` marks an item or device handler as eligible
  for configuration or mission based detail-block synchronization.
- `supports_mount_period_lookup = true` enables the SMS-specific
  fallback that resolves instrument start/end from device mount actions.

The new `defaults` table is merged into every `catalogs` entry for the same
handler. If `defaults` define `search_attribute_uri`, they also act as a
wildcard handler configuration for any catalog using that field, even when no
explicit `[[handlers.<Handler>.catalogs]]` entry exists. Explicit catalog
entries take precedence over the wildcard defaults.

With `catalogs.attribute_mapping` the mapping from the APIs JSON response is
mapped to attributes of the specified catalog. On the left a
[JMESPath](https://jmespath.org/) for the value from the API and on the right
the uri to the attribute in the catalog.

# Acknowledgements

As of 2026, this plugin has been further developed and maintained through the [DMP4NFDI](https://dmp.services.base4nfdi.de/) project, as an Incubator for the NFDI4Earth consortium.

DMP4NFDI is a Basic Service of Base4NFDI, funded by the German Research Foundation (DFG) under project [521453681](https://gepris.dfg.de/gepris/projekt/521453681). NFDI4Earth is funded by the DFG under project [460036893](https://gepris.dfg.de/gepris/projekt/460036893). Both projects are part of the German National Research Data Infrastructure (NFDI).
