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
| Catalog URI | `catalog_uris` | Lists the catalogs using a mapping. Omission makes it a wildcard, except for `DataCollectionVariableSync`, which requires explicit scope. |
| Search question attribute | `search_attribute_uri` | Starts item, device, configuration, or mission synchronization after selection. |
| Output question attribute | `attribute_mapping` value | Receives a value selected from a backend response using the mapping's JMESPath expression. |
| Managed output attribute | `managed_attribute_uris` | Declares fields owned by synchronization even when the current response contains no value. |
| Configuration collection attribute | `configuration_collection_attribute_uri` | Identifies one repeated configuration or mission block. |
| Device collection attribute | `device_collection_attribute_uri` | Identifies one repeated device-detail block. |
| Selected devices attribute | `selected_devices_attribute_uri` and project-local provider source | Stores the devices assigned to a configuration. |
| Refresh question attribute | `MetadataRefresh.actions[].trigger_attribute_uri` | Executes one refresh action. |
| Optional membership-filter attributes | `membership_filter_enabled`, `membership_filter_start_attribute_uri`, `membership_filter_end_attribute_uri`, and action `input_attribute_uris` | Opt an SMS catalog extension into explicit historical membership filtering. |
| Optionset provider key | Django `OPTIONSET_PROVIDERS` entry | Connects an RDMO optionset to the plugin provider. |

## Search and metadata synchronization

Two aggregate providers are available:

- `sensorsearch_devices` searches devices in every configured device provider;
- `sensorsearch_configurations` searches configurations and O2A missions.

Set the provider on an RDMO optionset and attach that optionset to the intended
search question. The question's attribute URI must equal the relevant
handler's `search_attribute_uri`.

When an option is selected, its ID prefix selects a handler. For example,
`kitsms:324` belongs to the KIT SMS device handler, while `kitcfg:27` belongs
to the KIT SMS configuration handler. The handler retrieves the full record and
applies the catalog's `attribute_mapping`.

Mapping keys are JMESPath expressions evaluated against the backend response.
Mapping values are exact RDMO attribute URIs. A simple mapping is:

```toml
[handlers.SensorManagementSystemDeviceHandler.catalogs.attribute_mapping]
"data.attributes.serial_number" = "https://example.org/attributes/device/serial-number"
```

Only add a target to `managed_attribute_uris` when the backend is authoritative
for that field. Managed fields may be cleared when the backend stops returning
a value. In the original Earth Sensor catalog, question set 2.1.4 describes the
selected backend configuration or mission, so its start and end attributes are
managed outputs. Separate attributes introduced by a future membership-filter
extension remain user-owned inputs.

## Configuration and mission device sets

Selecting a configuration or mission creates or updates one configuration
collection and stores its assigned devices in `selected_devices_attribute_uri`.
Those values feed two project-local providers:

- `sensorsearch_project_configuration_devices` presents devices already associated with the
  project's configurations;
- `sensorsearch_project_data_collection_devices` presents the same source for
  data-collection instrument questions.

With `materialize_device_details = true` on the matching device handler, the
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

## Optional SMS membership-filter extension

The original Earth Sensor catalog does not contain or activate a date-based
membership filter. Configuration and mission selection immediately
synchronizes all backend members, while question set 2.1.4 receives the
backend configuration or mission period.

A future catalog can add a distinct SMS-only workflow. It needs three new
attributes for filter start, filter end, and an explicit apply trigger. Do not
reuse the established 2.1.4 attributes. The SMS handler catalog mapping must
then opt in with:

```toml
membership_filter_enabled = true
membership_filter_start_attribute_uri = "<filter start attribute URI>"
membership_filter_end_attribute_uri = "<filter end attribute URI>"
```

The matching refresh action should use:

```toml
replace_existing_collections = true
require_configuration_period = true
input_attribute_uris = ["<start attribute URI>", "<end attribute URI>"]
```

Editing the free-text filter questions alone makes no backend request. The
action validates the start, accepts an optional open end, and replaces SMS
device membership using mount-action overlap. Normal selection never waits for
the filter fields, even when an extension catalog contains them.

O2A Registry has no equivalent historical mount model. The handler rejects
membership-filter actions until an accurately defined O2A policy exists. See
[the reassessment](configuration-period-reassessment.md) for a complete catalog
and TOML extension sketch.

## Metadata refresh controls

Refresh actions can operate on one configuration, one device, all
configurations, or all devices. Each action has one trigger URI and can have
status, message, and timestamp output URIs. Those output fields are useful for
showing success, partial failure, or validation errors in the interview.

Attach the `sensorsearch_interview_page_refresh` provider to a one-option
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

## Independent development mirror

`testing/catalogs/example_catalog_sensorsearch.xml` is a complete independent mirror of
`testing/catalogs/earth-sensor+original.xml`. Every catalog-defined and referenced URI uses
the `https://example.com/terms/.../plugin-dev/...` namespace; legacy source
URIs are normalized to include `/terms/`. It preserves the original optionset provider keys, so
it needs the matching test/example profile at
`testing/fixtures/sensorsearch-plugin-dev.toml`; do not add these bindings to the
production `sensorsearch.toml`.

The mirror is generated, not hand-maintained. Run
`python testing/tools/generate_plugin_dev_assets.py` to update it, then inspect its
diff as a catalog change. The complete list of TOML settings is in the
[configuration reference](configuration-reference.md#complete-setting-index).

RDMO derives an attribute URI from its `key` and parent tree during import; it
does not retain a manually supplied `<path>`. The generated mirror therefore
adds one synthetic `plugin-dev` root attribute and parents every original root
attribute beneath it. Do not remove or flatten that root.

## Adapting the catalog safely

Use this order when introducing the plugin into another catalog:

1. choose stable attribute URIs and identify the collection roots;
2. add the remote-search optionsets and verify that search results appear;
3. add a catalog-specific handler mapping with only two or three output fields;
4. test selection, replacement, and clearing of the search answer;
5. configure the configuration collection and selected-devices relationship;
6. add repeated device details and project-local optionsets;
7. add explicit refresh actions and, if approved, separate SMS membership-filter controls;
8. add data-collection variable synchronization last;
9. test with a new project and with an existing project containing manual data.

When reusing a URI, confirm its RDMO attribute value type and collection shape
as well as its spelling. Matching text values are not enough if one question is
single-valued and another is a collection.
