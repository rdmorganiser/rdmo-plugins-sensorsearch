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
- [Geophysical Instrument Pool Potsdam (GIPP)](https://gipp.gfz-potsdam.de/)
- [O2A Registry](https://registry.o2a-data.de/)
- [Sensor Management System](https://codebase.helmholtz.cloud/hub-terra/sms/service-desk/-/wikis/home)

For every integration it is possible to define multiple instances in the
configuration. This is especially necessary for the Sensor Management System
(SMS), since there are four productive instances.

This plugin is based on the [RDMO Sensor AWI option set plugin](https://github.com/hafu/rdmo-sensor-awi)
with a complete refactoring, to allow configuration and easy extension with
more registries if needed.

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

Add the plugin to the `OPTIONSET_PROVIDERS` in `config/settings/local.py`:

```python
OPTIONSET_PROVIDERS = [
    ('sensorssearch', _('Sensor Search'), 'rdmo_sensorsearch.providers.SensorsProvider'),
    ('sensorssearch_configurations', _('Configuration Search'), 'rdmo_sensorsearch.providers.ConfigurationsProvider'),
    ('sensorssearch_project_sensors', _('Project Configuration Sensors'), 'rdmo_sensorsearch.providers.ProjectConfigurationSensorsProvider'),
    ('sensorssearch_project_data_collection_devices', _('Project Data Collection Devices'), 'rdmo_sensorsearch.providers.ProjectDataCollectionDevicesProvider'),
    ('sensorssearch_project_device_refresh', _('Project Device Refresh'), 'rdmo_sensorsearch.providers.ProjectDeviceRefreshProvider'),
    ('sensorssearch_refresh_values', _('Refresh Values'), 'rdmo_sensorsearch.providers.ProjectValueRefreshProvider'),
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
mounted sensors, a data collection devices provider, and a device refresh
provider are available as well. The data collection devices provider uses the
same project-local value source for data collection instrument selection
questions. The device refresh provider lists already materialized device
detail blocks so an interview question can trigger backend refreshes.

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
catalog_uri = "http://example.com/terms/questions/example-configurations-earth-sensor"
source_attribute_uri = "http://example.com/terms/domain/configuration-set/member-sensor"

[ProjectDataCollectionDevicesProvider]
[[ProjectDataCollectionDevicesProvider.catalogs]]
catalog_uri = "https://rdmo.nfdi4earth.de/terms/questions/earth-sensor"
# Optional aliases for draft or derived catalog URIs using the same attribute layout.
catalog_uris = [
    "https://rdmo.nfdi4earth.de/terms/questions/earth-sensor-with-refresh-feature",
]
source_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/selected-devices"

[ProjectDeviceRefreshProvider]
[[ProjectDeviceRefreshProvider.catalogs]]
catalog_uri = "https://rdmo.nfdi4earth.de/terms/questions/earth-sensor"
catalog_uris = [
    "https://rdmo.nfdi4earth.de/terms/questions/earth-sensor-with-refresh-feature",
]
source_attribute_uri = "https://rdmo-sandbox.gfz-potsdam.de/terms/domain/moses/instruments/id"
trigger_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-devices"
selected_devices_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/selected-devices"
configuration_search_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-search"
clear_trigger_value = false
# Optional attributes for interview-visible refresh feedback.
status_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-status"
error_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-error"
timestamp_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-timestamp"

[[SensorsProvider.providers.O2ARegistrySearchProvider]]

[[SensorsProvider.providers.SensorManagementSystemProvider]]
id_prefix = "gfzsms"
text_prefix = "GFZ Sensors:"
base_url = "https://sensors.gfz-potsdam.de/backend/api/v1/devices"

[[SensorsProvider.providers.SensorManagementSystemProvider]]
id_prefix = "kitsms"
text_prefix = "KIT Sensors:"
base_url = "https://sms.atmohub.kit.edu/backend/api/v1/devices"

[[SensorsProvider.providers.SensorManagementSystemProvider]]
id_prefix = "ufzsms"
text_prefix = "UFZ Sensors:"
base_url = "https://web.app.ufz.de/sms/backend/api/v1/devices"

[[SensorsProvider.providers.GeophysicalInstrumentPoolPotsdamProvider]]

[[ConfigurationsProvider.providers.SensorManagementSystemConfigurationsProvider]]
id_prefix = "gfzcfg"
text_prefix = "GFZ Configurations:"
base_url = "https://sensors.gfz.de/backend/api/v1/configurations"

[[ConfigurationsProvider.providers.O2ARegistryMissionsProvider]]
id_prefix = "o2amission"
text_prefix = "O2A Mission"
base_url = "https://registry.o2a-data.de/rest/v2/missions"
where_template = "name=ILIKE=\"*{query}*\""

[handlers.SensorManagementSystemConfigurationsHandler]
[[handlers.SensorManagementSystemConfigurationsHandler.backends]]
id_prefix = "gfzcfg"
base_url = "https://sensors.gfz.de/backend/api/v1"
sensor_id_prefix = "gfzsms"
[handlers.SensorManagementSystemConfigurationsHandler.defaults]
auto_complete_field_uri = "http://example.com/terms/domain/configuration-set/configuration-search"
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
member_sensors_attribute_uri = "http://example.com/terms/domain/configuration-set/member-sensor"
device_collection_attribute_uri = "http://example.com/terms/domain/instruments/id"
item_id_prefix = "o2aregistry"
item_text_template = "{prefix}({item_id}) Mission({mission_id}): {name}{serial}"
[handlers.O2ARegistryMissionsHandler.defaults.attribute_mapping]
"description" = "http://example.com/terms/domain/configuration-set/description"
"startDate" = "http://example.com/terms/domain/configuration-set/start"
"endDate" = "http://example.com/terms/domain/configuration-set/end"
[[handlers.O2ARegistryMissionsHandler.catalogs]]
catalog_uri = "http://example.com/terms/questions/example-configurations-earth-sensor"
```

This configures all available providers with three SMS instances to query. The
`SensorsProvider` will only query the configured providers if at least three
characters are entered.
By default, SMS device search is not restricted by configurations already
selected in the project, so manual instrument searches query all configured SMS
instances. Set `filter_sms_by_selected_configuration = true` in
`[SensorsProvider]` only if device searches should be narrowed to the SMS
backend corresponding to an already selected configuration, such as
`kitcfg -> kitsms`.

The `O2ARegistrySearchProvider` and `GeophysicalInstrumentPoolPotsdamProvider`
uses their default values for `id_prefix`, `text_prefix`, `base_url` and
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

`ProjectDeviceRefreshProvider` is also project-local. The preferred
Earth-Sensor catalog layout uses a collection question set for selected devices
inside the configuration page. Each row contains the selected device and a
row-local refresh trigger whose attribute URI matches the configured
`trigger_attribute_uri`, by default
`https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-devices`,
and the selected device attribute configured by `selected_devices_attribute_uri`.
When the trigger value has no provider `external_id`, the plugin resolves the
selected device from the same question set row and refreshes the corresponding
materialized device detail block in
`https://rdmo-sandbox.gfz-potsdam.de/terms/domain/moses/instruments/id`.

The older provider-select trigger remains supported: if the saved trigger value
has an `external_id`, it is treated as the materialized device detail block id
and refreshed directly.

Refresh backend errors happen after RDMO has already saved the trigger value.
To make these failures visible in the interview, configure
`status_attribute_uri`, `error_attribute_uri`, and optionally
`timestamp_attribute_uri` to point to scalar catalog questions in the same
interview scope. The plugin then stores `success` or `failed`, a short error
message, and the refresh timestamp as normal RDMO values.

Do not use a provider-backed checkbox for this trigger in standard RDMO. RDMO's
checkbox conflict validation compares regular option values by `option`, while
dynamic provider values are stored with `external_id` and `option=None`. This
means multiple dynamic checkbox selections for the same question can collide
before the sensorsearch refresh signal is reached.

A minimal row-local Earth-Sensor catalog layout can use:

- page:
  `https://rdmo.nfdi4earth.de/terms/questions/instruments/configuration-set`
  with `is_collection=true`
- child question set:
  `https://rdmo.nfdi4earth.de/terms/questions/instruments/configuration-set/devices`
  with `is_collection=true`
- selected-device question inside that question set:
  `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/selected-devices`
  as a scalar text value with the selected device `external_id`
- refresh trigger question inside that same question set:
  `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-devices`
  as a Yes/No row-local action trigger
- optional refresh optionset on that trigger question:
  an optionset with provider key `sensorssearch_refresh_values`

`sensorssearch_refresh_values` intentionally returns no options. It exists only
to use RDMO's release-compatible `optionset.has_refresh` hook, which refetches
the current page values after the trigger is saved. This makes sibling feedback
values, such as refresh status and timestamp, visible without a manual browser
refresh in RDMO versions that support the `fetchValues(page)` refresh branch.
After a boolean Yes/No trigger refresh, the plugin resets the trigger value from
`Yes` (`1`) to `No` (`0`) while sensorsearch signals are muted. This lets users
click `Yes` again later to request another refresh without deleting the row.

The older provider-select trigger question can use:

- attribute:
  `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-devices`
- widget/value type: select / option
- collection: true
- option set:
  `https://rdmo.nfdi4earth.de/terms/options/device-refresh/optionset`
- provider key:
  `sensorssearch_project_device_refresh`

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
base_url = "https://sensors.gfz-potsdam.de/backend/api/v1"
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
- `reset_attribute_uris` can be used to clear additional attributes when the
  selection changes or the search field is erased. This is useful for
  sensor-related fields which are not filled by every backend but must still
  be reset when replacing a sensor.
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
