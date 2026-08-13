<!--
SPDX-FileCopyrightText: 2026 RDMO Community and individual contributors
SPDX-License-Identifier: Apache-2.0
-->

# SMS location and configuration-period remediation plan

This document records the findings from reviewer testing performed in August
2026 and turns them into an implementation, verification, and reviewer-feedback
plan. It covers the inconsistent synchronization of Earth Sensor questions
2.52, 2.53, and 2.54 and explains the separate configuration-period behavior.

## Implementation status

Fixes 1–5 are implemented. The mount resolver now supports the bounded
static-location tolerance, structured nonfatal notices, and the configurable
incomplete-chain policy. Both SMS handlers use the same settings, the supplied
`sensorsearch.toml` selects a 120-second tolerance with
`direct_device_offset`, and refresh feedback aggregates the notices without
changing a successful status. Resolver, handler, configuration, and feedback
tests cover the reviewer cases described below.

The configuration-period catalog changes remain a separate editor task. The
plugin support already exists, but the reviewer catalog must contain the
`apply-date-range` trigger before its user-entered start/end values control
membership synchronization.

The findings are based on:

- [`xml/earth-sensor+original.xml`](../xml/earth-sensor+original.xml), the
  catalog used for the review;
- `rdmo.log-20260811`, a local diagnostic log that is intentionally not part of
  the documentation or package;
- the current SMS mount resolver in
  [`rdmo_sensorsearch/handlers/sms_mounting.py`](../rdmo_sensorsearch/handlers/sms_mounting.py).

## Confirmed causes

The catalog maps the three questions to the expected attributes:

| Question | Catalog question URI | Target attribute |
| --- | --- | --- |
| 2.52, station height AMSL | `https://rdmo.nfdi4earth.de/terms/questions/instrument_location_above-sealevel` | `https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/geo_location/height` |
| 2.53, height or depth relative to the surface | `https://rdmo.nfdi4earth.de/terms/questions/instrument_location_above-ground` | `https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/geo_location/depth` |
| 2.54, site name | `https://rdmo.nfdi4earth.de/terms/questions/instrument_location-name` | `https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/processing/location` |

The definitions can be found in
[`xml/earth-sensor+original.xml`](../xml/earth-sensor+original.xml) around the
questions `instrument_location_above-sealevel`,
`instrument_location_above-ground`, and `instrument_location-name`. The
inconsistent answers therefore do not originate from incorrect question-to-
attribute mappings.

Two different SMS action-model cases cause the reported results.

### Configuration 43, device 338

The device mount ends at `2025-08-10 12:00:00`. For a completed mount, the
resolver evaluates the location one microsecond before the end:
`2025-08-10 11:59:59.999999`.

The associated static-location action ends at `2025-08-10 11:59:00`, about one
minute earlier. The current strict interval check consequently rejects that
location, even though it overlaps nearly the complete device deployment. The
mount chain remains resolvable, which explains the observed combination:

```text
2.52 station height: blank
2.53 surface offset: 5
2.54 site name:      blank
```

### Configuration 47, device 330 (SMTEB32)

The applicable static-location action contains `z = 235` and the label
`TEAMx KITcube main site Bozen/Bolzano`, so questions 2.52 and 2.54 can be
filled.

The device mount action has `offset_z = -0.1` and refers to parent platform 55,
but the configuration response contains no matching platform-mount action. The
resolver currently suppresses the offset when it cannot resolve the complete
chain to the configuration root:

```text
2.52 station height: 235
2.53 surface offset: blank
2.54 site name:      TEAMx KITcube main site Bozen/Bolzano
```

This is a deliberate safety rule, but its reason is not visible in the current
refresh feedback.

## 1. Static-location end tolerance

### Goal

Accept a small timestamp discrepancy between an otherwise applicable static
location and a device mount without reusing unrelated, stale locations.

### Configuration

Add this optional setting to both SMS handlers:

```toml
[handlers.SensorManagementSystemDeviceHandler.defaults]
static_location_end_tolerance_seconds = 120

[handlers.SensorManagementSystemConfigurationHandler.defaults]
static_location_end_tolerance_seconds = 120
```

The code-level default should be `0`, preserving strict behavior when the
setting is omitted. A deployment can enable the two-minute tolerance shown
above. Configuration validation should accept non-negative integers and reject
booleans, strings, floats, and negative values.

The setting must be available to both handlers so that configuration import,
configuration refresh, and individual-device refresh produce identical
answers.

### Selection algorithm

Extend `select_static_location_action()` so the mount resolver can provide the
device mount action and configured tolerance.

1. Prefer a static-location action whose half-open interval contains the exact
   reference time.
2. If no exact action exists, consider only static-location actions that:

   - overlap the device mount interval;
   - end before the reference time; and
   - end no more than the configured tolerance before the reference time.

3. Select the candidate with the smallest time gap. If two candidates have the
   same gap, prefer the one with the latest start.
4. Return no static location if there is no eligible candidate.

The fallback must be used only by device mount-location resolution. Existing
configuration-level selection of the latest static location for latitude and
longitude should retain its current semantics.

### Acceptance criteria

For configuration 43/device 338, a 120-second tolerance produces:

```text
2.52 = 594
2.53 = 5
2.54 = St. Martin in Passeier
```

A static location ending before the device mount starts, or outside the
configured tolerance, must remain unavailable.

## 2. Structured resolution diagnostics

### Goal

Make every intentionally blank location value explainable without treating
missing optional metadata as a failed synchronization.

### Result model

Extend `ResolvedMountLocation` with structured notices while keeping its three
existing value fields:

```python
@dataclass(frozen=True)
class MountLocationNotice:
    code: MountLocationNoticeCode
    details: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedMountLocation:
    station_height_amsl: float | None
    vertical_surface_offset: float | None
    site_name: str | None
    notices: tuple[MountLocationNotice, ...] = ()
```

Suggested notice codes are:

- `static_location_not_found`;
- `static_location_not_active_at_reference_time`;
- `static_location_end_tolerance_used`;
- `static_location_height_missing`;
- `static_location_label_missing`;
- `parent_mount_action_missing`;
- `mount_chain_cycle`;
- `device_offset_missing`;
- `device_offset_invalid`;
- `direct_device_offset_fallback_used`.

### Mount-chain model

Replace the current `(chain, complete)` internal return value with a structured
result containing:

- the resolved actions;
- a status such as `complete`, `missing_parent`, or `cycle`;
- the missing parent type and ID when applicable.

The distinction is required by the configurable policy below. A missing parent
may permit a direct-device fallback, while a cyclic chain must remain
unresolved.

### Propagation

Carry notices through the synchronization flow:

```text
resolve_mount_location
    -> SMSConfigurationMember
    -> SelectedDevice
    -> SMSDeviceMetadataEnricher
    -> RefreshResult
```

Both mount-location entry points must use the same policy and diagnostics:

- configuration membership resolution in
  [`sms_configuration_membership.py`](../rdmo_sensorsearch/handlers/sms_configuration_membership.py);
- direct device resolution in
  [`sms_device.py`](../rdmo_sensorsearch/handlers/sms_device.py) and
  [`sms_device_enrichment.py`](../rdmo_sensorsearch/handlers/sms_device_enrichment.py).

### Logging

Log only anomalous resolution decisions. Suggested examples are:

```text
INFO Static-location tolerance fallback used:
configuration=43 device=338 mount_action=506
location_action=32 gap_seconds=60

WARNING Mount chain incomplete:
configuration=47 device=330 mount_action=585
missing_parent_type=platform missing_parent_id=55 policy=strict
```

Normal, fully resolved devices should not produce an additional log line.

## 3. Configurable incomplete-chain policy

### Configuration

Add the following setting to both SMS handler contracts:

```toml
incomplete_mount_chain_policy = "strict"
```

Supported values are:

- `strict`;
- `direct_device_offset`.

The code-level default must remain `strict`. Configuration loading should fail
with a clear path-specific message for any other value.

### Strict policy

When the full mount chain can be resolved, sum every `offset_z` action through
the configuration root. When it cannot be resolved, leave 2.53 empty.

### Direct-device-offset policy

When resolution fails specifically because the referenced parent mount action
is missing, use the numeric `offset_z` from the direct device mount action. Do
not invent or add an unavailable parent offset.

For configuration 47/device 330 this produces `-0.1` instead of an empty 2.53
answer. Add the `direct_device_offset_fallback_used` notice so the value's
provenance remains visible.

The fallback must not be used when:

- the direct `offset_z` is missing or nonnumeric;
- the chain is cyclic;
- the device mount action cannot be identified; or
- another structural error prevents determining the direct-device offset.

The existing `_offset_z()` helper currently treats an invalid or missing value
as zero. Split numeric parsing from complete-chain summation so that the direct
fallback never turns missing data into a false `0` value.

### Recommended deployment setting

Keep `strict` as the library default, but explicitly configure the Earth Sensor
deployment after accepting the reviewer-requested fallback:

```toml
[handlers.SensorManagementSystemDeviceHandler.defaults]
static_location_end_tolerance_seconds = 120
incomplete_mount_chain_policy = "direct_device_offset"

[handlers.SensorManagementSystemConfigurationHandler.defaults]
static_location_end_tolerance_seconds = 120
incomplete_mount_chain_policy = "direct_device_offset"
```

## 4. Verification plan

### Resolver unit tests

Add tests covering:

- an exact static-location match taking precedence over a fallback;
- configuration 43's 60-second mismatch;
- the exact tolerance boundary;
- rejection immediately outside the tolerance;
- rejection of a non-overlapping stale location;
- deterministic selection between multiple candidates;
- station height coming only from static-location `attributes.z`;
- no addition of device or platform offsets to question 2.52;
- complete mount chains under both policies;
- missing parents under `strict`;
- missing parents under `direct_device_offset`;
- preservation of negative direct offsets;
- rejection of missing or invalid direct offsets;
- rejection of cycles under both policies; and
- the expected diagnostic codes for every fallback or failure.

### Handler integration tests

Exercise both:

1. selecting an SMS configuration and materializing its device details;
2. refreshing an already materialized individual SMS device.

Both paths must produce identical 2.52, 2.53, and 2.54 values for the same SMS
actions and policy.

### Configuration tests

Test valid, zero, negative, and invalid-type tolerance values; both supported
policy names; an invalid policy name; and propagation of both settings into
the instantiated configuration and device handlers.

### Repository verification

Run the focused resolver and handler tests, the complete test suite,
pre-commit checks, and a wheel build.

## 5. Refresh and reviewer feedback

### User-visible refresh notices

Add nonfatal notices to `RefreshResult`, separately from `errors`. Notices must
not change an otherwise successful refresh to `partial` or `failed`.

Aggregate notices by reason in the refresh message, for example:

```text
Success: KIT Cfg(47) was refreshed. 29 devices were refreshed.
Location metadata: direct device offset fallback used for 4 devices;
static location unavailable for 2 devices.
```

Keep individual configuration, device, action, and missing-parent IDs in the
application log. This keeps the RDMO message readable and within its existing
1,000-character limit.

Test that notices preserve a successful status, errors still produce partial
or failed status, notice counts combine across configuration refreshes, and
formatted messages remain within the length limit.

### Suggested reviewer response after implementation

The response should explain that two independent cases were found:

1. configuration 43 has a one-minute timestamp difference between its static
   location and device-mount end, which is handled by the new bounded
   tolerance;
2. device 330 in configuration 47 refers to a parent platform without a
   matching platform-mount action, so its direct `offset_z` is used only under
   the explicitly configured fallback policy.

Ask the reviewer to repeat at least these checks:

| Configuration/device | Expected 2.52 | Expected 2.53 | Expected 2.54 |
| --- | ---: | ---: | --- |
| Configuration 43, device 338 | `594` | `5` | `St. Martin in Passeier` |
| Configuration 47, device 330 | `235` | `-0.1` | `TEAMx KITcube main site Bozen/Bolzano` |

## Configuration-period finding

> **Superseded:** The period recommendation below records the earlier design.
> After adopting `earth-sensor+original.xml` as the source of truth, question
> 2.013 again represents the backend configuration or mission period. See
> [Configuration-period baseline and optional membership filtering](configuration-period-reassessment.md)
> for the current plan.

The reviewer catalog contains the start and end questions but no action that
applies those values to synchronization.

### Elements present in the reviewer catalog

The configuration page includes the time-period question set:

```text
https://rdmo.nfdi4earth.de/terms/questions/configurations/time-period
```

That set contains only:

```text
https://rdmo.nfdi4earth.de/terms/questions/configurations/time-period/start
https://rdmo.nfdi4earth.de/terms/questions/configurations/time-period/end
```

Their attributes are:

```text
https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-start-datetime
https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configurations-end-datetime
```

In [`earth-sensor+original.xml`](../xml/earth-sensor+original.xml), the start
question has `is_optional=False`, while the end question has
`is_optional=True`.

The catalog also contains a regular configuration refresh question:

```text
Question:  https://rdmo.nfdi4earth.de/terms/questions/configurations-general/refresh
Attribute: https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-configuration
```

That is a backend refresh control. It is not the date-range action.

### Missing elements

The reviewer catalog does not contain:

```text
Question:
https://rdmo.nfdi4earth.de/terms/questions/configurations/time-period/apply

Attribute:
https://rdmo.nfdi4earth.de/terms/domain/configuration-set/apply-date-range
```

The TOML file defines an action for that exact attribute, but the plugin also
checks whether the attribute is actually present in the active catalog. This
makes date filtering opt-in by catalog structure and keeps older catalogs
backward-compatible.

The resulting behavior is:

| Catalog structure | Synchronization behavior |
| --- | --- |
| Apply trigger present | Start/end are user inputs and device synchronization uses the requested range. |
| Apply trigger absent | Configuration selection imports members immediately without an interview date filter. |
| Start/end present but apply trigger absent | The fields can be edited but do not control synchronization. |

The reviewer catalog is in the third state.

### Why the period is no longer populated automatically

The start and end attributes are synchronization inputs owned by the user. The
SMS and O2A mission handlers explicitly remove them from backend-mapped output,
and reconciliation excludes them from synchronization-owned values.

This prevents a refresh from replacing a user's filter. For example:

```text
User filter:             2025-06-01 to 2025-06-30
Backend campaign period: 2025-05-10 to 2025-08-10
```

If the backend period overwrote the filter, the next synchronization would
select devices for the full campaign instead of June.

The catalog help for configuration search currently says that the following
fields will be filled automatically. Because the date inputs are an exception,
that wording is ambiguous and should be corrected.

## Recommended catalog-period design

### User-entered filtering period

Keep the existing start and end attribute URIs unchanged. Add the apply
question to the existing time-period question set. It should:

- use the exact `apply-date-range` attribute URI;
- use a `yesno` widget;
- use the optionset
  `https://rdmo.nfdi4earth.de/terms/options/interview-page-refresh`;
- therefore use provider key `sensorsearch_interview_page_refresh`;
- be visible only when a backend configuration or mission is selected; and
- explain that the plugin resets the value after processing.

The resulting workflow is:

1. The user selects an SMS configuration or O2A mission.
2. The plugin synchronizes non-period configuration metadata.
3. The user enters a required start and an optional end.
4. The user activates **Apply date range**.
5. The plugin validates the range and rebuilds the selected-device collection.

If start/end already contain a valid period when another configuration is
selected, the selection-triggered synchronization may use that period. Editing
the free-text fields alone must continue to avoid backend requests.

Change the question-set help to make ownership explicit, for example:

> Date range used to select devices belonging to this configuration or
> mission. These values are entered by the user and are not overwritten with
> the period reported by SMS or O2A.

If a catalog intentionally remains without the apply question, make the start
field optional or remove the unused filter fields. A required field that does
not affect synchronization is misleading.

### Backend-reported period

If editors also want to display the original campaign or mission period, add
two separate synchronization-owned attributes, for example:

```text
https://rdmo.nfdi4earth.de/terms/domain/configuration-set/backend-start-datetime
https://rdmo.nfdi4earth.de/terms/domain/configuration-set/backend-end-datetime
```

Map them from:

| Backend | Start path | End path |
| --- | --- | --- |
| SMS | `data.attributes.start_date` | `data.attributes.end_date` |
| O2A Registry | `startDate` | `endDate` |

The exact new URI names should be agreed with the catalog editors before they
are published, but the existing input URIs do not need to change.

This keeps the two concepts unambiguous:

| Concept | Owner | Purpose |
| --- | --- | --- |
| Existing configuration start/end attributes | User | Filter configuration or mission members. |
| New backend-period attributes | Synchronization | Display the period reported by SMS or O2A. |

## Suggested implementation sequence

Implement the work in reviewable commits:

1. add mount-resolution policies, structured chain results, and config
   validation;
2. implement and test the bounded static-location fallback;
3. implement and test the incomplete-chain policy;
4. propagate and aggregate nonfatal notices;
5. update refresh feedback and documentation;
6. update the Earth Sensor catalog's explicit date-range workflow separately
   from the mount-resolution code;
7. add backend-reported period fields only after their new catalog URIs have
   been agreed.
