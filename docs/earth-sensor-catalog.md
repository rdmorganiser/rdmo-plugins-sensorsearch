<!--
SPDX-FileCopyrightText: 2026 RDMO Community and individual contributors
SPDX-License-Identifier: Apache-2.0
-->

# Earth Sensor catalog URI map

[Documentation index](index.md) · [Catalog editor guide](catalog-editor-guide.md) · [Configuration reference](configuration-reference.md) · [Operations and limitations](operations-and-limitations.md)

This map describes the concrete elements in
[`xml/earth-sensor+refresh.xml`](../xml/earth-sensor+refresh.xml). Copy the URIs
exactly when searching the RDMO editor or the XML. The catalog URI is:

```text
https://rdmo.nfdi4earth.de/terms/questions/earth-sensor-with-refresh-feature-v1
```

## Configuration and mission selection

The configuration collection is shared by the general configuration page and
the selected device-set page.

| Role | URI |
| --- | --- |
| Configuration page | `https://rdmo.nfdi4earth.de/terms/questions/configurations-general` |
| Configuration collection attribute | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set` |
| Search question | `https://rdmo.nfdi4earth.de/terms/questions/configuration_ident_api` |
| Search attribute | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-search` |
| Search optionset | `https://rdmo.nfdi4earth.de/terms/options/configurations/optionset` |
| Optionset provider key | `sensorsearch_configurations` |

The search attribute is configured as
`MetadataRefresh.configuration_search_attribute_uri` and as the
`search_attribute_uri` of both configuration handlers. The collection
attribute is configured as `configuration_collection_attribute_uri`.

Configuration metadata targets are:

| Question | Attribute |
| --- | --- |
| `https://rdmo.nfdi4earth.de/terms/questions/configurations-general/description` | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-description` |
| `https://rdmo.nfdi4earth.de/terms/questions/configurations-general/link` | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-link` |
| `https://rdmo.nfdi4earth.de/terms/questions/configurations-general/static-location/lat` | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/static-location-lat` |
| `https://rdmo.nfdi4earth.de/terms/questions/configurations-general/static-location/lon` | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/static-location-lon` |

The latitude and longitude questions are grouped in question set
`https://rdmo.nfdi4earth.de/terms/questions/configurations-general/static-location`.

The condition controlling configuration-only controls is:

| Role | URI/value |
| --- | --- |
| Condition | `https://rdmo.nfdi4earth.de/terms/conditions/configurations-general/has-backend-configuration` |
| Source attribute | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-search` |
| Relation | `notempty` |

## User-entered configuration period

These fields are synchronization inputs. They must not be populated from SMS
configuration dates or O2A mission dates.

| Role | URI |
| --- | --- |
| Time-period question set | `https://rdmo.nfdi4earth.de/terms/questions/configurations/time-period` |
| Start question | `https://rdmo.nfdi4earth.de/terms/questions/configurations/time-period/start` |
| Start attribute | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-start-datetime` |
| End question | `https://rdmo.nfdi4earth.de/terms/questions/configurations/time-period/end` |
| End attribute | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configurations-end-datetime` |
| Apply question | `https://rdmo.nfdi4earth.de/terms/questions/configurations/time-period/apply` |
| Apply trigger attribute | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/apply-date-range` |
| Apply optionset | `https://rdmo.nfdi4earth.de/terms/options/interview-page-refresh` |
| Optionset provider key | `sensorsearch_interview_page_refresh` |

The accepted interview format is `YYYY-MM-DD hh:mm`; values with timezone
information are also normalized when supported by the parser. Start is required
for **Apply date range**, while end is optional. Editing either text field clears
old refresh feedback but does not synchronize. This prevents a remote request
on every keystroke.

The same start and end attributes appear as `period_start_attribute_uri` and `period_end_attribute_uri`
under both:

- `handlers.SensorManagementSystemConfigurationHandler.catalogs`;
- `handlers.O2ARegistryMissionHandler.catalogs`.

The apply action repeats them in `MetadataRefresh.actions[].input_attribute_uris`
and sets `require_configuration_period = true` and
`replace_existing_collections = true`.

If the apply trigger attribute is removed from a derived catalog, selecting a
configuration or mission immediately synchronizes all its devices without
interview date filtering. Keeping the TOML action alone does not activate the
workflow; the trigger must be part of the active catalog.

## Configuration-local refresh

| Role | URI |
| --- | --- |
| Refresh question | `https://rdmo.nfdi4earth.de/terms/questions/configurations-general/refresh` |
| Trigger attribute | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-configuration` |
| Status question | `https://rdmo.nfdi4earth.de/terms/questions/configurations-general/refresh-status` |
| Status attribute | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-status` |
| Timestamp question | `https://rdmo.nfdi4earth.de/terms/questions/configurations-general/refresh-timestamp` |
| Timestamp attribute | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-timestamp` |
| Message question | `https://rdmo.nfdi4earth.de/terms/questions/configurations-general/refresh-message` |
| Message attribute | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-message` |
| Trigger optionset | `https://rdmo.nfdi4earth.de/terms/options/interview-page-refresh` |

This normal refresh updates backend-owned metadata while preserving the current
configuration device collections. Applying the date range is the action that
authoritatively rebuilds the filtered device set.

## Selected Device Set page

| Role | URI |
| --- | --- |
| Page | `https://rdmo.nfdi4earth.de/terms/questions/instruments/configuration-set` |
| Configuration collection attribute | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set` |
| Selected devices question | `https://rdmo.nfdi4earth.de/terms/questions/instruments/configuration-set/selected` |
| Selected devices attribute | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/selected-devices` |
| Optionset | `https://rdmo-sandbox.gfz-potsdam.de/terms/options/optionsets/sensorsearch` |
| Optionset provider key | `sensorsearch_devices` |

The selected devices attribute is used by:

- `selected_devices_attribute_uri` on SMS configuration and O2A mission handlers;
- `ProjectConfigurationDevicesProvider.catalogs[].source_attribute_uri`;
- `ProjectDataCollectionDevicesProvider.catalogs[].source_attribute_uri`.

The page URI is configured as `selected_devices_page_uri`. The remote
`sensorsearch_devices` optionset also permits manual additions. A later authoritative
date-range application can replace membership with the backend-derived set.

## Device detail pages

Both device pages use this repeated collection root:

```text
https://rdmo-sandbox.gfz-potsdam.de/terms/domain/moses/instruments/id
```

It is the `device_collection_attribute_uri` on the configuration and mission
handlers.

### Instrument general

| Role | URI |
| --- | --- |
| Page | `https://rdmo.nfdi4earth.de/terms/questions/instruments_general` |
| Device search question | `https://rdmo.nfdi4earth.de/terms/questions/instrument_ident_api` |
| Device search attribute | `https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/keywords` |
| Remote optionset | `https://rdmo-sandbox.gfz-potsdam.de/terms/options/optionsets/sensorsearch` |
| Optionset provider key | `sensorsearch_devices` |

The device search attribute is the item/device handlers'
`search_attribute_uri` and
`MetadataRefresh.device_search_attribute_uri`.

Core device metadata questions are:

| Meaning | Question | Attribute |
| --- | --- | --- |
| Name | `https://rdmo.nfdi4earth.de/terms/questions/instrument_name_api` | `https://rdmorganiser.github.io/terms/domain/project/dataset/usage_technology` |
| Type | `https://rdmo.nfdi4earth.de/terms/questions/instrument-type` | `https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/type/title` |
| Manufacturer | `https://rdmo.nfdi4earth.de/terms/questions/instrument-manufacturer` | `https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/manufacturer` |
| Model | `https://rdmo.nfdi4earth.de/terms/questions/instrument-model` | `https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/type/name` |
| Serial number | `https://rdmo.nfdi4earth.de/terms/questions/instrument_serial_nr` | `https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/serial_number` |
| Persistent identifier | `https://rdmo.nfdi4earth.de/terms/questions/instrument_PID` | `https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/type/pid` |
| Device link | `https://rdmo.nfdi4earth.de/terms/questions/instruments_general/device-link` | `https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/device-link` |

Deployment period elements are:

| Role | URI |
| --- | --- |
| Question set | `https://rdmo.nfdi4earth.de/terms/questions/instruments_general/time-range` |
| Start question | `https://rdmo.nfdi4earth.de/terms/questions/instruments_general/time-range/start` |
| Start attribute | `https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/instrument-start-datetime` |
| End question | `https://rdmo.nfdi4earth.de/terms/questions/instruments_general/time-range/end` |
| End attribute | `https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/instrument-end-datetime` |

Device parameter elements are:

| Role | URI |
| --- | --- |
| Question set | `https://rdmo.nfdi4earth.de/terms/questions/instruments/variable-unit` |
| Variable question | `https://rdmo.nfdi4earth.de/terms/questions/instruments/variable` |
| Variable attribute | `https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/preservation/parameter/name` |
| Unit question | `https://rdmo.nfdi4earth.de/terms/questions/instruments/unit` |
| Unit attribute | `https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/preservation/parameter/unit` |

### Instrument location and further information

| Meaning | Question | Attribute |
| --- | --- | --- |
| Instrument location AMSL | `https://rdmo.nfdi4earth.de/terms/questions/instrument_location_above-sealevel` | `https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/geo_location/height` |
| Height/depth relative to surface | `https://rdmo.nfdi4earth.de/terms/questions/instrument_location_above-ground` | `https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/geo_location/depth` |
| Site name | `https://rdmo.nfdi4earth.de/terms/questions/instrument_location-name` | `https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/processing/location` |

These three fields can be enriched for SMS devices from static-location and
device/platform mount actions. The relative value retains its sign, so a
negative `offset_z` can describe a sensor below the local surface. The AMSL
value is based on the nearest absolute `z` anchor in the mount context, or on a
static-location `z` plus the accumulated vertical offsets when the complete
mount chain is available. See the calculation limits in
[Operations and limitations](operations-and-limitations.md#sms-location-height-and-depth).

| Earth Sensor answer | SMS source |
| --- | --- |
| Site name | `/static-location-actions` → `attributes.label` at the resolved time |
| Relative height/depth | Accumulated `attributes.offset_z` from the active device/platform mount chain |
| Instrument location AMSL | Nearest active mount `attributes.z` plus offsets below it; otherwise `/static-location-actions` → `attributes.z` plus the complete mount-chain offset |

The SMS configuration handler fetches configuration-scoped device mount,
platform mount, and static-location action collections. The device handler can
also inspect `/devices/{id}/device-mount-actions` when refreshing an already
materialized device.

The further-information location question set and coordinates are:

| Role | URI |
| --- | --- |
| Page | `https://rdmo.nfdi4earth.de/terms/questions/instruments/further-info` |
| Location question set | `https://rdmo.nfdi4earth.de/terms/questions/instruments/further-info/location` |
| Latitude attribute | `https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/geo_location/lat` |
| Longitude attribute | `https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/geo_location/lon` |

## Device-local refresh

| Role | URI |
| --- | --- |
| Refresh question | `https://rdmo.nfdi4earth.de/terms/questions/instruments_general/refresh` |
| Trigger attribute | `https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/refresh-device` |
| Status question | `https://rdmo.nfdi4earth.de/terms/questions/instruments_general/refresh-status` |
| Status attribute | `https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/refresh-status` |
| Timestamp question | `https://rdmo.nfdi4earth.de/terms/questions/instruments_general/refresh-timestamp` |
| Timestamp attribute | `https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/refresh-timestamp` |
| Message question | `https://rdmo.nfdi4earth.de/terms/questions/instruments_general/refresh-message` |
| Message attribute | `https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/refresh-message` |
| Trigger optionset | `https://rdmo.nfdi4earth.de/terms/options/interview-page-refresh` |

The condition for backend-linked device controls is:

| Role | URI/value |
| --- | --- |
| Condition | `https://rdmo.nfdi4earth.de/terms/conditions/instruments-general/has-backend-device` |
| Source attribute | `https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/keywords` |
| Relation | `notempty` |

## Bulk metadata refresh page

The page URI is
`https://rdmo.nfdi4earth.de/terms/questions/metadata-refresh`.

| Scope | Trigger question | Trigger attribute |
| --- | --- | --- |
| All configurations | `https://rdmo.nfdi4earth.de/terms/questions/metadata-refresh/configurations/trigger` | `https://rdmo.nfdi4earth.de/terms/domain/metadata-refresh/configurations/trigger` |
| All devices | `https://rdmo.nfdi4earth.de/terms/questions/metadata-refresh/devices/trigger` | `https://rdmo.nfdi4earth.de/terms/domain/metadata-refresh/devices/trigger` |

The feedback fields are:

| Scope and role | Question | Attribute |
| --- | --- | --- |
| Configurations status | `https://rdmo.nfdi4earth.de/terms/questions/metadata-refresh/configurations/status` | `https://rdmo.nfdi4earth.de/terms/domain/metadata-refresh/configurations/status` |
| Configurations timestamp | `https://rdmo.nfdi4earth.de/terms/questions/metadata-refresh/configurations/timestamp` | `https://rdmo.nfdi4earth.de/terms/domain/metadata-refresh/configurations/timestamp` |
| Configurations message | `https://rdmo.nfdi4earth.de/terms/questions/metadata-refresh/configurations/message` | `https://rdmo.nfdi4earth.de/terms/domain/metadata-refresh/configurations/message` |
| Devices status | `https://rdmo.nfdi4earth.de/terms/questions/metadata-refresh/devices/status` | `https://rdmo.nfdi4earth.de/terms/domain/metadata-refresh/devices/status` |
| Devices timestamp | `https://rdmo.nfdi4earth.de/terms/questions/metadata-refresh/devices/timestamp` | `https://rdmo.nfdi4earth.de/terms/domain/metadata-refresh/devices/timestamp` |
| Devices message | `https://rdmo.nfdi4earth.de/terms/questions/metadata-refresh/devices/message` | `https://rdmo.nfdi4earth.de/terms/domain/metadata-refresh/devices/message` |

Both trigger questions use
`https://rdmo.nfdi4earth.de/terms/options/interview-page-refresh` with provider
key `sensorsearch_interview_page_refresh`.

## Data-collection device and variable sync

| Role | URI |
| --- | --- |
| Data-collection device question | `https://rdmo.nfdi4earth.de/terms/questions/dc-instruments` |
| Device attribute | `https://rdmorganiser.github.io/terms/domain/project/dataset/collaboration_tools` |
| Device optionset | `https://rdmo.nfdi4earth.de/terms/options/options/data-collection/devices/optionset` |
| Optionset provider key | `sensorsearch_project_data_collection_devices` |
| Variable question set | `https://rdmo.nfdi4earth.de/terms/questions/dc-variables` |
| Variable question | `https://rdmo.nfdi4earth.de/terms/questions/dc-variables/variable` |
| Variable attribute | `https://rdmo.nfdi4earth.de/terms/domain/project/dataset/metadata/dc-variable` |
| Unit question | `https://rdmo.nfdi4earth.de/terms/questions/dc-variables/unit` |
| Unit attribute | `https://rdmo.nfdi4earth.de/terms/domain/project/dataset/metadata/dc-unit` |

The project-local options come from
`https://rdmo.nfdi4earth.de/terms/domain/configuration-set/selected-devices` as
configured under `ProjectDataCollectionDevicesProvider`.

## URI change checklist

Before importing a modified catalog, search the XML and TOML for every changed
URI. In particular, verify:

- page and question-set collection attributes;
- optionset URIs and provider keys;
- condition source attributes;
- handler search, mapping, and managed attributes;
- configuration/member/device collection settings;
- refresh trigger and feedback attributes;
- both copies of the date input URIs and the apply action inputs;
- project-local provider sources and data-collection attributes.
