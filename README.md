<!--
SPDX-FileCopyrightText: 2023 - 2024 Hannes Fuchs (GFZ) <hfuchs@gfz-potsdam.de>
SPDX-FileCopyrightText: 2023 - 2024 Helmholtz Centre Potsdam - GFZ German Research Centre for Geosciences

SPDX-License-Identifier: Apache-2.0
-->

# RDMO Sensor Search option set plugin

This option set plugin allows you to query several sensor registries at the
same time. Additional questions can be filled in automatically with informations
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
]
```

Add the plugin to the `INSTALLED_APPS` in `config/settings/local.py`:

```python
INSTALLED_APPS = ['rdmo_sensorsearch'] + INSTALLED_APPS
```

After restarting RDMO, the `Sensor Search` should be selectable as a provider
option for option sets.

## Configuration

With `config.toml` the providers which should be used can be configured. The
`SensorsProvider` aggregates the results of the configured providers.

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

[[SensorsProvider.providers.O2ARegistrySearchProvider]]

[[SensorsProvider.providers.SensorManagentSystemProvider]]
id_prefix = "gfzsms" 
text_prefix = "GFZ Sensors:" 
base_url = "https://sensors.gfz-potsdam.de/backend/api/v1/devices"

[[SensorsProvider.providers.SensorManagentSystemProvider]]
id_prefix = "kitsms"
text_prefix = "KIT Sensors:"
base_url = "https://sms.atmohub.kit.edu/backend/rdm/svm-api/v1/devices"

[[SensorsProvider.providers.SensorManagentSystemProvider]]
id_prefix = "ufzsms"
text_prefix = "UFZ Sensors:"
base_url = "https://web.app.ufz.de/sms/backend/api/v1/devices"

[[SensorsProvider.providers.GeophysicalInstrumentPoolPotsdamProvider]]
```

This configures all available providers with three SMS instances to query. The
`SensorsProvider` will only query the configured providers if at least three
characters are entered.

The `O2ARegistrySearchProvider` and `GeophysicalInstrumentPoolPotsdamProvider`
uses their default values for `id_prefix`, `text_prefix`, `base_url` and
`max_hits`.

There is no default `base_url` for `SensorManagentSystemProvider` defined,
therefore the `base_url` for every instance must be set. In addition the
`text_prefix` and `id_prefix` is configured. The `text_prefix` is displayed
before the result, so that the user can identify the correct registry and
sensor. The `id_prefix` is used internally, to prefix the id which is saved
along the value in `external_id`. This is used by the handler to query the
correct registry when filling out questions with attribute mapping
automatically.

In conclusion, every provider has the following options:
- `id_prefix` to identify the instance internally and used by the handler
- `text_prefix` is displayed next to the queried result to identify the used
  registry
- `max_hits` defaults to `10` and limits the results to display
- `base_url` the API URL of the used instance, must be set for the
  `SensorManagentSystemProvider`

### Configuration: Handlers

Handlers can be used to fill out questions automatically with the use of a
configured attribute mapping. For every provider a handler is implemented,
which can request additional information from the registry to answer questions.

For every catalog, which should use handlers, the catalog must be configured
and the attribute mapping for every provider must also be configured. 

```toml
[handlers.O2ARegistrySearchHandler]
#[[handlers.O2ARegistrySearchHandler.backends]]
#id_prefix = "o2aregistry"
[[handlers.O2ARegistrySearchHandler.catalogs]]
catalog_uri = "http://rdmo-dev.local/terms/questions/sensor-awi-test"
auto_complete_field_uri = "http://rdmo-dev.local/terms/domain/sensor/awi/search"
[handlers.O2ARegistrySearchHandler.catalogs.attribute_mapping]
"longName" = "http://rdmo-dev.local/terms/domain/sensor/awi/type-name"
"shortName" = "http://rdmo-dev.local/terms/domain/sensor/awi/name"
"serialNumber" = "http://rdmo-dev.local/terms/domain/sensor/awi/serial"

[handlers.SensorManagentSystemHandler]
[[handlers.SensorManagentSystemHandler.backends]]
id_prefix = "gfzsms" 
base_url = "https://sensors.gfz-potsdam.de/backend/api/v1"
[[handlers.SensorManagentSystemHandler.backends]]
id_prefix = "kitsms"
base_url = "https://sms.atmohub.kit.edu/backend/rdm/svm-api/v1"
[[handlers.SensorManagentSystemHandler.backends]]
id_prefix = "ufzsms"
base_url = "https://web.app.ufz.de/sms/backend/api/v1"
[[handlers.SensorManagentSystemHandler.catalogs]]
catalog_uri = "http://rdmo-dev.local/terms/questions/sensor-awi-test"
auto_complete_field_uri = "http://rdmo-dev.local/terms/domain/sensor/awi/search"
[handlers.SensorManagentSystemHandler.catalogs.attribute_mapping]
"data.attributes.long_name" = "http://rdmo-dev.local/terms/domain/sensor/awi/type-name"
"data.attributes.short_name" = "http://rdmo-dev.local/terms/domain/sensor/awi/name"
"data.attributes.serial_number" = "http://rdmo-dev.local/terms/domain/sensor/awi/serial"

[handlers.GeophysicalInstrumentPoolPotsdamHandler]
[[handlers.GeophysicalInstrumentPoolPotsdamHandler.catalogs]]
catalog_uri = "http://rdmo-dev.local/terms/questions/sensor-awi-test"
auto_complete_field_uri = "http://rdmo-dev.local/terms/domain/sensor/awi/search"
[handlers.GeophysicalInstrumentPoolPotsdamHandler.catalogs.attribute_mapping]
"Instrument.code" = "http://rdmo-dev.local/terms/domain/sensor/awi/type-name"
"Instrumentcategory.name" = "http://rdmo-dev.local/terms/domain/sensor/awi/name"
"Instrument.serialNo" = "http://rdmo-dev.local/terms/domain/sensor/awi/serial"
```

A `backends` configuration must be defined in the case of
`SensorManagentSystemHandler` or if more than one instance of one provider is
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

With `catalogs.attribute_mapping` the mapping from the APIs JSON response is
mapped to attributes of the specified catalog. On the left a
[JMESPath](https://jmespath.org/) for the value from the API and on the right
the uri to the attribute in the catalog.
