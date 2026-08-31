<!--
SPDX-FileCopyrightText: 2026 RDMO Community and individual contributors
SPDX-License-Identifier: Apache-2.0
-->

# Configuration-period baseline and optional membership filtering

This document supersedes the configuration-period recommendation in
[`sms-location-and-configuration-period-plan.md`](sms-location-and-configuration-period-plan.md).
It records the reassessment made after adopting
[`testing/catalogs/earth-sensor+original.xml`](../testing/catalogs/earth-sensor+original.xml) as the
authoritative Earth Sensor catalog.

## Baseline catalog meaning

Question set 2.1.4 is titled **Time period of the configuration or mission**.
Its two questions use these established attributes:

| Meaning | Question URI | Attribute URI |
| --- | --- | --- |
| Configuration/mission start | `https://rdmo.nfdi4earth.de/terms/questions/configurations/time-period/start` | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-start-datetime` |
| Configuration/mission end | `https://rdmo.nfdi4earth.de/terms/questions/configurations/time-period/end` | `https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configurations-end-datetime` |

The surrounding catalog help says that configuration or mission information
is filled automatically after a backend record is selected. The catalog does
not contain an **Apply date range** question or an `apply-date-range` trigger.
The two existing period attributes therefore describe the backend
configuration or mission; they are not device-membership filter inputs.

The plugin must populate them from:

| Backend | Start path | End path |
| --- | --- | --- |
| SMS | `data.attributes.start_date` | `data.attributes.end_date` |
| O2A Registry | `startDate` | `endDate` |

When no backend configuration or mission is selected, catalog users can still
enter the period manually. Selecting or refreshing a backend record makes the
backend authoritative for these two answers.

## Baseline synchronization behavior

| Operation | Configuration period | Device membership |
| --- | --- | --- |
| Select an SMS configuration | Populate the SMS period | Synchronize all mounted devices |
| Select an O2A mission | Populate the mission period | Synchronize all mission items |
| Refresh one configuration or mission | Refresh backend-owned metadata | Preserve the current selected-device collection |
| Edit the two period text fields | Store the user's answer | Do not call a backend or alter refresh state |

SMS devices retain their individual mount-action periods. O2A mission items
inherit the mission period because the Registry does not expose an equivalent
historical mount model.

## Problems in the earlier implementation

The first date-filter prototype reinterpreted the established 2.1.4 attributes
as user-owned filter inputs. As a result:

- SMS and O2A backend period mappings were removed;
- both handlers explicitly discarded mapped values for those attributes;
- reconciliation excluded them from synchronization ownership;
- an `apply-date-range` action was configured although the authoritative
  catalog did not contain its trigger; and
- handler behavior could change merely because a hard-coded trigger URI was
  found anywhere in the active catalog.

The last point allowed a partially configured extension to defer or clear
device assignments even when no working apply action was available. O2A also
did not truly filter membership: it only copied the entered period into every
mission item's deployment fields.

## Extension design

Date-based membership selection remains useful, but it must be an explicit,
optional extension rather than a reinterpretation of question 2.1.4.

### Separate catalog attributes

A future catalog revision should add a separate question set such as **Device
membership period**, using new attributes. Example URIs are:

```text
https://rdmo.nfdi4earth.de/terms/domain/configuration-set/member-filter-start-datetime
https://rdmo.nfdi4earth.de/terms/domain/configuration-set/member-filter-end-datetime
https://rdmo.nfdi4earth.de/terms/domain/configuration-set/apply-member-filter
```

The actual URI names must be agreed with the catalog editors before release.
The start and end questions should be optional while editing; the plugin
validates the required start only when the user applies the filter. The apply
question should:

- use a `yesno` widget;
- use optionset
  `https://rdmo.nfdi4earth.de/terms/options/interview-page-refresh`;
- be conditioned on a selected backend configuration; and
- explain that it rebuilds device membership without changing question 2.1.4.

### Explicit TOML activation

The matching SMS configuration handler mapping must explicitly enable and map
the extension inputs:

```toml
membership_filter_enabled = true
membership_filter_start_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/member-filter-start-datetime"
membership_filter_end_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/member-filter-end-datetime"
```

The corresponding metadata-refresh action is:

```toml
[[MetadataRefresh.actions]]
kind = "configuration"
trigger_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/apply-member-filter"
replace_existing_collections = true
require_configuration_period = true
input_attribute_uris = [
    "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/member-filter-start-datetime",
    "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/member-filter-end-datetime",
]
```

Catalog and TOML are both required naturally: without the question no action
can be submitted, and without the action configuration the saved answer has no
plugin behavior. Normal configuration selection never waits for or implicitly
applies a membership period.

### SMS and O2A capability boundary

SMS can filter device mount actions by overlap with the requested period. A
missing end remains open-ended.

O2A Registry mission membership has no comparable historical mount model.
The membership-filter extension should therefore remain disabled for O2A until
the project team chooses a separate, accurately named behavior. Copying an
entered range to every mission item is not membership filtering.

## Implementation and verification plan

1. Restore SMS and O2A backend mappings for the established 2.1.4 attributes.
2. Remove the date-filter action and filter-input settings from the baseline
   `sensorsearch.toml`.
3. Make membership filtering run only through an explicit refresh execution
   context; remove catalog-presence activation.
4. Restore O2A mission periods on materialized mission items.
5. Retain validated, clearly named membership-filter settings for future SMS
   catalog extensions.
6. Use `earth-sensor+original.xml` as the catalog test fixture and assert that
   it has no filter-apply question.
7. Test baseline synchronization separately from synthetic opt-in extension
   configuration and handler tests.

The authoritative deployment TOML should contain only currently deployed
behavior. The extension snippet belongs in documentation until its catalog
questions and final URIs have been approved.
