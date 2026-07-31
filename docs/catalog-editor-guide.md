<!--
SPDX-FileCopyrightText: 2026 RDMO Community and individual contributors
SPDX-License-Identifier: Apache-2.0
-->

# Catalog editor guide

[Documentation index](index.md) · [Configuration reference](configuration-reference.md) · [Earth Sensor URI map](earth-sensor-catalog.md) · [Operations and limitations](operations-and-limitations.md)

## How catalog elements and TOML configuration connect

The plugin does not discover questions by their labels. Its contract with a
catalog is made from attribute URIs, page URIs, catalog URIs, optionset provider
keys, and collection indexes.

| Catalog element | TOML counterpart | Purpose |
| --- | --- | --- |
| Catalog URI | `catalog_uri` or `catalog_uris` | Selects the mapping used for the current project. Omitting both makes a mapping a wildcard. |
| Search question attribute | `auto_complete_field_uri` | Starts item, device, configuration, or mission synchronization after selection. |
| Output question attribute | `attribute_mapping` value | Receives a value selected from a backend response using the mapping's JMESPath expression. |
| Managed output attribute | `managed_attribute_uris` | Declares fields owned by synchronization even when the current response contains no value. |
| Configuration collection attribute | `configuration_collection_attribute_uri` | Identifies one repeated configuration or mission block. |
| Device collection attribute | `device_collection_attribute_uri` | Identifies one repeated device-detail block. |
| Selected devices attribute | `member_sensors_attribute_uri` and project-local provider source | Stores the devices assigned to a configuration. |
| Refresh question attribute | `MetadataRefresh.actions[].trigger_attribute_uri` | Executes one refresh action. |
| Date input attributes | `cfg_start_uri`, `cfg_end_uri`, and `input_attribute_uris` | Supply a user-entered period for device assignment. |
| Optionset provider key | Django `OPTIONSET_PROVIDERS` entry | Connects an RDMO optionset to the plugin provider. |

## Search and metadata synchronization

Two aggregate providers are available:

- `sensorssearch` searches devices in every configured device provider;
- `sensorssearch_configurations` searches configurations and O2A missions.

Set the provider on an RDMO optionset and attach that optionset to the intended
search question. The question's attribute URI must equal the relevant
handler's `auto_complete_field_uri`.

When an option is selected, its ID prefix selects a handler. For example,
`kitsms:324` belongs to the KIT SMS device handler, while `kitcfg:27` belongs
to the KIT SMS configuration handler. The handler retrieves the full record and
applies the catalog's `attribute_mapping`.

Mapping keys are JMESPath expressions evaluated against the backend response.
Mapping values are exact RDMO attribute URIs. A simple mapping is:

```toml
[handlers.SensorManagementSystemHandler.catalogs.attribute_mapping]
"data.attributes.serial_number" = "https://example.org/attributes/device/serial-number"
```

Only add a target to `managed_attribute_uris` when the backend is authoritative
for that field. Managed fields may be cleared when the backend stops returning
a value. User-owned fields, especially the configuration start and end inputs,
must not be managed or mapped from backend dates.

## Configuration and mission device sets

Selecting a configuration or mission creates or updates one configuration
collection and stores its assigned devices in `member_sensors_attribute_uri`.
Those values feed two project-local providers:

- `sensorssearch_project_sensors` presents devices already associated with the
  project's configurations;
- `sensorssearch_project_data_collection_devices` presents the same source for
  data-collection instrument questions.

With `sync_device_detail_blocks = true` on the matching device handler, the
plugin also creates or updates repeated device-detail blocks. Device attributes
such as name, serial number, parameters, deployment period, and location can
then be mapped into ordinary catalog questions.

The following relationships must be consistent:

```text
configuration search selection
  -> configuration collection
    -> selected-devices values
      -> project-local device options
      -> repeated device-detail collections
```

The selected-devices page and device collection attribute are configured on
the configuration or mission handler. Do not change only the catalog side of
this relationship.

## Optional date-range workflow

Date filtering is enabled by catalog structure. If the catalog contains the
Earth Sensor apply trigger attribute
`https://rdmo.nfdi4earth.de/terms/domain/configuration-set/apply-date-range`,
selecting a configuration or mission still synchronizes its metadata, but
device assignment is finalized by the explicit apply action. Editing either
free-text date field alone does not make a backend request.

The workflow is:

1. the user selects a configuration or mission;
2. the user enters a start datetime and, optionally, an end datetime;
3. the user activates **Apply date range**;
4. the plugin validates the period and rebuilds the selected device set;
5. the interview page is refetched so synchronized answers are visible.

The action should use:

```toml
replace_collections = true
require_configuration_period = true
input_attribute_uris = ["<start attribute URI>", "<end attribute URI>"]
```

The same URIs must be configured as `cfg_start_uri` and `cfg_end_uri` on both
the SMS configuration and O2A mission catalog mappings that use this feature.
The start field is required when applying a range; a missing end is open-ended.
An end earlier than the start is invalid.

If the apply trigger attribute is absent from a catalog, configuration and
mission selection keeps the immediate behavior: all member devices are
synchronized without applying interview date filters. This makes the feature
backward-compatible with catalogs that do not expose date-range controls.

The plugin currently checks for that exact trigger attribute anywhere in the
active catalog, not by its visible label or page position. If a derived catalog
changes this URI, the catalog-presence check in the plugin must be adapted as
well. Catalog editors should nevertheless keep the trigger beside the two date
inputs so its meaning is clear to interview users.

## Metadata refresh controls

Refresh actions can operate on one configuration, one device, all
configurations, or all devices. Each action has one trigger URI and can have
status, message, and timestamp output URIs. Those output fields are useful for
showing success, partial failure, or validation errors in the interview.

Attach the `sensorssearch_interview_page_refresh` provider to a one-option
optionset used by trigger questions. It intentionally has no remote search
logic; it causes the page to be refetched after the answer has been saved.

Keep trigger, status, message, and timestamp attributes out of ordinary backend
attribute mappings. They describe synchronization itself, not sensor metadata.

## Data-collection variable synchronization

`DataCollectionVariableSync` connects selected data-collection devices with
repeated variable and unit questions. The provider source is the configured
selected-devices attribute. When a device is added, the plugin can generate one
row per backend parameter and unit. Rows generated by the plugin are marked so
they can be updated or removed without deleting manually entered rows.

This automation is catalog-scoped. Add the catalog URI under
`[DataCollectionVariableSync]` only after the catalog uses the expected data
collection device, variable, and unit attributes. See the exact Earth Sensor
URIs in [Earth Sensor catalog map](earth-sensor-catalog.md#data-collection-device-and-variable-sync).

## Adapting the catalog safely

Use this order when introducing the plugin into another catalog:

1. choose stable attribute URIs and identify the collection roots;
2. add the remote-search optionsets and verify that search results appear;
3. add a catalog-specific handler mapping with only two or three output fields;
4. test selection, replacement, and clearing of the search answer;
5. configure the configuration collection and selected-devices relationship;
6. add repeated device details and project-local optionsets;
7. add explicit refresh actions and optional date-range controls;
8. add data-collection variable synchronization last;
9. test with a new project and with an existing project containing manual data.

When reusing a URI, confirm its RDMO attribute value type and collection shape
as well as its spelling. Matching text values are not enough if one question is
single-valued and another is a collection.
