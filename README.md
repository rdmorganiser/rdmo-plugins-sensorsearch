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
`xml/earth-sensor+refresh.xml`. Runtime costs and backend constraints are
covered in [operations and limitations](docs/operations-and-limitations.md).

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
pytest
```

Add the plugin to the `OPTIONSET_PROVIDERS` in `config/settings/local.py`:

```python
OPTIONSET_PROVIDERS = [
    ('sensorssearch', _('Sensor Search'), 'rdmo_sensorsearch.providers.SensorsProvider'),
    ('sensorssearch_configurations', _('Configuration Search'), 'rdmo_sensorsearch.providers.ConfigurationsProvider'),
    ('sensorssearch_project_sensors', _('Project Configuration Sensors'), 'rdmo_sensorsearch.providers.ProjectConfigurationSensorsProvider'),
    ('sensorssearch_project_data_collection_devices', _('Project Data Collection Devices'), 'rdmo_sensorsearch.providers.ProjectDataCollectionDevicesProvider'),
    ('sensorssearch_interview_page_refresh', _('Interview Page Refresh'), 'rdmo_sensorsearch.providers.InterviewPageRefreshProvider'),
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

After restarting RDMO, the `Sensor Search` should be selectable as a provider
option for option sets. If you enable the additional provider entries, a
separate `Configuration Search` provider, a project-local reuse provider for
mounted sensors, and a data collection devices provider are available as well.
The data collection devices provider uses the same project-local value source
for data collection instrument selection questions. The no-op `Interview Page
Refresh` provider can be attached to metadata refresh trigger questions so
RDMO refetches the current interview page after saving the trigger.

The importable [`xml/example_catalog_sensorsearch.xml`](xml/example_catalog_sensorsearch.xml)
combines all plugin workflows in one compact catalog: configuration and device
search, automatic device detail materialization, both project-local optionset
providers, individual and bulk metadata refresh actions, interview page
refetching, and data collection parameter synchronization.

## Configuration

With `config.toml` the providers which should be used can be configured. The
`SensorsProvider` aggregates the results of the configured providers.
`ConfigurationsProvider` works the same way for configuration backends.

To automatically fill out questions with results of the matching sensor,
attribute mapping for the specific catalog(s) must be configured in the
configuration file.

The configuration file default location is inside the directory of the plugin.
The location can be overwritten with `SENSORS_SEARCH_PROVIDER_CONFIG_FILE_PATH`
in the in `config/settings/local.py` or as environment variable with the same
name.

### Configuration: Providers

```toml
[SensorsProvider]
min_search_len = 3
# Optional: restrict SMS device searches to the SMS backend that matches a
# selected configuration in the current project. Leave false for manual
# instrument searches that should query all configured SMS instances.
filter_sms_by_selected_configuration = false

[SensorsProvider.provider_defaults.SensorManagementSystemProvider]
max_hits = 20

[ConfigurationsProvider]
min_search_len = 3

[ProjectConfigurationSensorsProvider]
[[ProjectConfigurationSensorsProvider.catalogs]]
# Omitting catalog_uri/catalog_uris makes this mapping available in all catalogs.
source_attribute_uri = "http://example.com/terms/domain/configuration-set/member-sensor"

[ProjectDataCollectionDevicesProvider]
[[ProjectDataCollectionDevicesProvider.catalogs]]
# Omitting catalog_uri/catalog_uris makes this mapping available in all catalogs.
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
replace_collections = true
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

[[SensorsProvider.providers.O2ARegistrySearchProvider]]

[[SensorsProvider.providers.SensorManagementSystemProvider]]
id_prefix = "gfzsms"
text_prefix = "GFZ Sensor"
base_url = "https://sensors.gfz.de/backend/api/v1/devices"

[[SensorsProvider.providers.SensorManagementSystemProvider]]
id_prefix = "kitsms"
text_prefix = "KIT Sensor"
base_url = "https://sms.atmohub.kit.edu/backend/api/v1/devices"

[[SensorsProvider.providers.SensorManagementSystemProvider]]
id_prefix = "ufzsms"
text_prefix = "UFZ Sensor"
base_url = "https://web.app.ufz.de/sms/backend/api/v1/devices"

[[SensorsProvider.providers.GeophysicalInstrumentPoolPotsdamProvider]]

[[ConfigurationsProvider.providers.SensorManagementSystemConfigurationsProvider]]
id_prefix = "gfzcfg"
text_prefix = "GFZ Cfg"
base_url = "https://sensors.gfz.de/backend/api/v1/configurations"

[[ConfigurationsProvider.providers.O2ARegistryMissionsProvider]]
id_prefix = "o2amission"
text_prefix = "O2A M"
base_url = "https://registry.o2a-data.de/rest/v2/missions"
where_template = "name=ILIKE=\"*{query}*\""

[handlers.SensorManagementSystemConfigurationsHandler]
[[handlers.SensorManagementSystemConfigurationsHandler.backends]]
id_prefix = "gfzcfg"
base_url = "https://sensors.gfz.de/backend/api/v1"
sensor_id_prefix = "gfzsms"
[handlers.SensorManagementSystemConfigurationsHandler.defaults]
auto_complete_field_uri = "http://example.com/terms/domain/configuration-set/configuration-search"
configuration_collection_attribute_uri = "http://example.com/terms/domain/configuration-set"
member_sensors_attribute_uri = "http://example.com/terms/domain/configuration-set/member-sensor"
frontend_link_attribute_uri = "https://rdmorganiser.github.io/terms/domain/project/dataset/uri"
api_link_attribute_uri = "https://rdmorganiser.github.io/terms/domain/project/dataset/source"
location_attribute_uri = "https://rdmorganiser.github.io/terms/domain/project/dataset/spatial"
[handlers.SensorManagementSystemConfigurationsHandler.defaults.attribute_mapping]
"data.id" = "https://rdmorganiser.github.io/terms/domain/project/dataset/identifier"
"data.attributes.label" = "https://rdmorganiser.github.io/terms/domain/project/dataset/description"
"data.attributes.project" = "https://rdmorganiser.github.io/terms/domain/project/dataset/documentation"
"data.attributes.persistent_identifier" = "https://rdmorganiser.github.io/terms/domain/project/dataset/id"
"data.attributes.description" = "https://rdmorganiser.github.io/terms/domain/project/dataset/annotation"
"data.links.self" = "https://rdmorganiser.github.io/terms/domain/project/dataset/source"
[[handlers.SensorManagementSystemConfigurationsHandler.catalogs]]
catalog_uri = "http://example.com/terms/questions/example-configurations-earth-sensor"

[handlers.O2ARegistryMissionsHandler]
[handlers.O2ARegistryMissionsHandler.defaults]
auto_complete_field_uri = "http://example.com/terms/domain/configuration-set/configuration-search"
configuration_collection_attribute_uri = "http://example.com/terms/domain/configuration-set"
member_sensors_attribute_uri = "http://example.com/terms/domain/configuration-set/member-sensor"
device_collection_attribute_uri = "http://example.com/terms/domain/instruments/id"
item_id_prefix = "o2aregistry"
item_text_template = "{configuration} {prefix}({item_id}): {name}{serial}"
[handlers.O2ARegistryMissionsHandler.defaults.attribute_mapping]
"description" = "http://example.com/terms/domain/configuration-set/description"
[[handlers.O2ARegistryMissionsHandler.catalogs]]
catalog_uri = "http://example.com/terms/questions/example-configurations-earth-sensor"
# These are user-entered filtering inputs, not mission metadata outputs.
cfg_start_uri = "http://example.com/terms/domain/configuration-set/start"
cfg_end_uri = "http://example.com/terms/domain/configuration-set/end"
```

This configures all available providers with three SMS instances to query. The
`SensorsProvider` will only query the configured providers if at least three
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
instances. Set `filter_sms_by_selected_configuration = true` in
`[SensorsProvider]` only if device searches should be narrowed to the SMS
backend corresponding to an already selected configuration, such as
`kitcfg -> kitsms`.

When RDMO initializes an asynchronous select containing an existing answer, it
requests options using the complete stored answer text. The meta-providers
resolve an exact match from current project values when its external ID belongs
to an enabled backend. These initialization requests therefore avoid backend
authentication and external API calls. Partial or otherwise unmatched searches
continue to query the configured backends normally.

The `O2ARegistrySearchProvider` and `GeophysicalInstrumentPoolPotsdamProvider`
use their default values for `id_prefix`, `text_prefix`, `base_url` and
`max_hits`.

There is no default `base_url` for `SensorManagementSystemProvider` defined,
therefore the `base_url` for every instance must be set. In addition the
`text_prefix` and `id_prefix` is configured. The `text_prefix` is displayed
before the result, so that the user can identify the correct registry and
sensor. The `id_prefix` is used internally, to prefix the id which is saved
along the value in `external_id`. This is used by the handler to query the
correct registry when filling out questions with attribute mapping
automatically.

In conclusion, every remote provider has the following options:
- `id_prefix` to identify the instance internally and used by the handler
- `text_prefix` is displayed next to the queried result to identify the used
  registry
- `max_hits` defaults to `10` and limits the results to display
- `base_url` the API URL of the used instance, must be set for the
  `SensorManagementSystemProvider` and
  `SensorManagementSystemConfigurationsProvider`

To avoid repeating shared provider settings, provider defaults can be declared
once per meta-provider and provider class:

```toml
[SensorsProvider.provider_defaults.SensorManagementSystemProvider]
max_hits = 20
```

These defaults are merged into every
`[[SensorsProvider.providers.SensorManagementSystemProvider]]` entry. Any value
declared on the concrete provider entry still overrides the default.

### Configuration: SMS authentication

SMS device and configuration providers, plus the corresponding handlers, reuse
an available bearer token for SMS backend requests. The token is sent as:

```text
Authorization: Bearer <access-token>
```

Token resolution is intentionally conservative:

- If `SENSORS_SEARCH_AUTH_TOKEN_RESOLVER` is configured, it is used first. The
  resolver can be a callable or dotted import path accepting `user` and
  `request` keyword arguments.
- If the auth context middleware is enabled, session keys from
  `SENSORS_SEARCH_AUTH_SESSION_TOKEN_KEYS` are checked next. Without explicit
  keys, a single unambiguous `access_token` or `*.access_token` session value is
  used.
- If django-allauth social tokens are available for the user, a single
  unexpired token is used. If several social tokens exist, configure
  `SENSORS_SEARCH_AUTH_SOCIALACCOUNT_PROVIDERS`, for example:

```python
SENSORS_SEARCH_AUTH_SOCIALACCOUNT_PROVIDERS = ['helmholtz-aai']
```

If no unambiguous token can be resolved, the plugin keeps making public SMS
requests without an `Authorization` header.

The `ProjectConfigurationSensorsProvider` and
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

O2A Registry missions are exposed through `O2ARegistryMissionsProvider`. They
follow the same configuration flow as SMS configurations: selecting a mission
can materialize its items into the configured project-local sensor collection.
The default search query uses the O2A RSQL form `name=ILIKE="*{query}*"`.

### Configuration: Handlers

Handlers can be used to fill out questions automatically with the use of a
configured attribute mapping. For every provider a handler is implemented,
which can request additional information from the registry to answer questions.

Handler defaults can also be configured once and then reused by multiple
catalogs or even applied as a wildcard mapping for any catalog which uses the
same autocomplete field.

```toml
[handlers.O2ARegistrySearchHandler]
#[[handlers.O2ARegistrySearchHandler.backends]]
#id_prefix = "o2aregistry"
[handlers.O2ARegistrySearchHandler.defaults]
auto_complete_field_uri = "http://rdmo-dev.local/terms/domain/sensor/awi/search"
sync_device_detail_blocks = true
device_link_attribute_uri = "http://rdmo-dev.local/terms/domain/sensor/device-link"
[handlers.O2ARegistrySearchHandler.defaults.attribute_mapping]
"longName" = "http://rdmo-dev.local/terms/domain/sensor/awi/type-name"
"shortName" = "http://rdmo-dev.local/terms/domain/sensor/awi/name"
"serialNumber" = "http://rdmo-dev.local/terms/domain/sensor/awi/serial"

[[handlers.O2ARegistrySearchHandler.catalogs]]
catalog_uri = "http://rdmo-dev.local/terms/questions/sensor-awi-test"
# optional per-catalog overrides can be added here

[handlers.SensorManagementSystemHandler]
[[handlers.SensorManagementSystemHandler.backends]]
id_prefix = "gfzsms"
base_url = "https://sensors.gfz.de/backend/api/v1"
[[handlers.SensorManagementSystemHandler.backends]]
id_prefix = "kitsms"
base_url = "https://sms.atmohub.kit.edu/backend/api/v1"
[[handlers.SensorManagementSystemHandler.backends]]
id_prefix = "ufzsms"
base_url = "https://web.app.ufz.de/sms/backend/api/v1"
[handlers.SensorManagementSystemHandler.defaults]
auto_complete_field_uri = "http://rdmo-dev.local/terms/domain/sensor/awi/search"
[handlers.SensorManagementSystemHandler.defaults.attribute_mapping]
"data.attributes.long_name" = "http://rdmo-dev.local/terms/domain/sensor/awi/type-name"
"data.attributes.short_name" = "http://rdmo-dev.local/terms/domain/sensor/awi/name"
"data.attributes.serial_number" = "http://rdmo-dev.local/terms/domain/sensor/awi/serial"

[[handlers.SensorManagementSystemHandler.catalogs]]
catalog_uri = "http://rdmo-dev.local/terms/questions/sensor-awi-test"

[handlers.GeophysicalInstrumentPoolPotsdamHandler]
[handlers.GeophysicalInstrumentPoolPotsdamHandler.defaults]
auto_complete_field_uri = "http://rdmo-dev.local/terms/domain/sensor/awi/search"
[handlers.GeophysicalInstrumentPoolPotsdamHandler.defaults.attribute_mapping]
"Instrument.code" = "http://rdmo-dev.local/terms/domain/sensor/awi/type-name"
"Instrumentcategory.name" = "http://rdmo-dev.local/terms/domain/sensor/awi/name"
"Instrument.serialNo" = "http://rdmo-dev.local/terms/domain/sensor/awi/serial"

[[handlers.GeophysicalInstrumentPoolPotsdamHandler.catalogs]]
catalog_uri = "http://rdmo-dev.local/terms/questions/sensor-awi-test"
```

A `backends` configuration must be defined in the case of
`SensorManagementSystemHandler` or if more than one instance of one provider is
used. Here the `id_prefix` and the `base_url` is critical and must be the same
as in the `providers` configuration, so that additional requests can be made
to the correct endpoint.

The `catalogs` configuration is used to identify the catalog(s) where the
attribute mapping should be used to map values from the API response to
attributes of the catalog. It is possible to configure more than one catalog.
- `catalog_uri` is the uri of the catalog where the handler should map values
  to attributes
- `auto_complete_field_uri` is the uri of the question with the option set
  provider used in the catalog
- `managed_attribute_uris` adds attributes to the handler's ownership beyond
  those in `attribute_mapping`. Every successful refresh is authoritative for
  this complete set: returned values are created or updated in place, while
  owned values omitted by the backend are removed. Unmanaged interview values
  are left untouched. Clearing the source question applies the same ownership
  rules with an empty result.
- `sync_device_detail_blocks = true` marks an item/sensor handler as eligible
  for configuration or mission based detail-block synchronization.
- `supports_mount_action_period_lookup = true` enables the SMS-specific
  fallback that resolves instrument start/end from device mount actions.

The new `defaults` table is merged into every `catalogs` entry for the same
handler. If `defaults` define `auto_complete_field_uri`, they also act as a
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
