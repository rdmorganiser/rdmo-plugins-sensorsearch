<!--
SPDX-FileCopyrightText: 2026 RDMO Community and individual contributors
SPDX-License-Identifier: Apache-2.0
-->

# Earth Sensor catalog URI map

[Documentation index](index.md) · [Catalog editor guide](catalog-editor-guide.md) · [Configuration reference](configuration-reference.md) · [Operations and limitations](operations-and-limitations.md)

This map describes the concrete elements in
[`testing/catalogs/earth-sensor+original.xml`](../testing/catalogs/earth-sensor+original.xml). Copy the URIs
exactly when searching the RDMO editor or the XML. The catalog URI is:

```text
https://rdmo.nfdi4earth.de/terms/questions/earth-sensor
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

## Backend configuration or mission period

Question set 2.1.4 records the period of the selected configuration or mission.
The synchronization owns these fields when a backend record is selected.

| Role | URI |
| --- | --- |
| Time-period question set | `https://rdmo.nfdi4earth.de/terms/questions/configurations/time-period` |
| Start question | `https://rdmo.nfdi4earth.de/terms/questions/configurations/time-period/start` |
| Start attribute | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-start-datetime` |
| End question | `https://rdmo.nfdi4earth.de/terms/questions/configurations/time-period/end` |
| End attribute | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configurations-end-datetime` |

The SMS handler maps `data.attributes.start_date` and
`data.attributes.end_date`; the O2A mission handler maps `startDate` and
`endDate`. Both targets are also listed in `managed_attribute_uris`. Datetimes
are normalized to `YYYY-MM-DD hh:mm`. The end remains empty for an active,
open-ended backend record.

The original catalog has no apply question and these two attributes do not
filter device membership. A future SMS-only membership filter needs separate
catalog attributes and explicit TOML activation; see
[Configuration-period baseline and optional membership filtering](configuration-period-reassessment.md).

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
configuration device collections.

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
`sensorsearch_devices` optionset also permits manual additions. Selecting a
configuration initially synchronizes its backend-derived member set; a normal
configuration refresh preserves the current collection.

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
| Owner institution | `https://rdmo.nfdi4earth.de/terms/questions/instrument_owner` | `https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/owner` |

These three fields can be enriched for SMS devices from static-location and
device/platform mount actions. The AMSL value is the resolved static-location
`z` without adjustment by device or platform mounts. The relative value retains
its sign, so a negative `offset_z` can describe a sensor below the local
surface. See the calculation limits in
[Operations and limitations](operations-and-limitations.md#sms-location-height-and-depth).

| Earth Sensor answer | SMS source |
| --- | --- |
| Site name | `/static-location-actions` → `attributes.label` at the resolved time |
| Relative height/depth | Accumulated `attributes.offset_z` from the active device/platform mount chain |
| Instrument location AMSL | `/static-location-actions` → `attributes.z` at the resolved time, without mount offsets |

The SMS configuration handler fetches configuration-scoped device mount,
platform mount, and static-location action collections. The device handler can
also inspect `/devices/{id}/device-mount-actions` when refreshing an already
materialized device. An exact static-location interval is preferred; the
optional bounded end-time tolerance and incomplete-chain policy are documented
under [SMS location, height, and depth](operations-and-limitations.md#sms-location-height-and-depth).

Site-name resolution requires the device's configuration and mount-time
context. A standalone device selection does not borrow a site from another
configuration. If a deployment leaves question 2.4.4 empty, compare its plugin
version, attribute URI, selected configuration, mount actions, and matching
static-location label before changing the resolver.

Question 2.4.6 uses `select_creatable` with `value_type=option` and the existing
ROR provider, accepting both ROR suggestions and imported SMS organisation
names. SMS Owner roles are joined to their included contacts; distinct
organisation names merge into the existing answer using `; `. Manually
entered and historical names are retained until edited, even if SMS removes
them. See the [SMS device mapping](configuration-reference.md#sensormanagementsystemdevicehandler)
for refresh and identifier handling.

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

These four per-device controls are unconditional. Keeping them visible avoids an
additional condition-resolution lookup for every device collection row; backend
refresh handling continues to decide whether a selected device can be refreshed.

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
