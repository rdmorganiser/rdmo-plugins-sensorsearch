<!--
SPDX-FileCopyrightText: 2026 RDMO Community and individual contributors
SPDX-License-Identifier: Apache-2.0
-->

# Operations and limitations

[Documentation index](index.md) · [Catalog editor guide](catalog-editor-guide.md) · [Configuration reference](configuration-reference.md) · [Earth Sensor URI map](earth-sensor-catalog.md)

## Runtime behavior

Synchronization runs after RDMO saves the triggering answer and commits the
database transaction. It is not a background job. The user can therefore wait
for remote APIs and for multiple dependent records to be fetched before the
updated page is available.

The plugin parallelizes independent work in a few bounded places: aggregate
provider searches use up to four workers, and device detail materialization
uses up to four workers. Identical GET requests made during one metadata refresh
are deduplicated. These measures reduce repeated work but do not remove remote
API latency.

The request timeout is controlled by the Django setting
`SENSORS_SEARCH_PROVIDER_REQUEST_TIMEOUT` and defaults to 10 seconds. A shorter
timeout fails faster on an unavailable backend; a longer timeout may make an
interview save appear stalled.

## Performance expectations

Simple device selection usually needs one detail request. Configuration and
mission synchronization can require:

- the configuration or mission record;
- paginated membership or mount-action requests;
- one detail request per selected device;
- SMS static-location, platform-mount, and device-mount context;
- creation or update of several RDMO values per device.

Bulk refresh is consequently the slowest operation. Catalog editors should
label it as an intentional maintenance action rather than an ordinary interview
step. Large configurations, long mount histories, backend throttling, and an
authenticated SMS instance can increase the duration substantially.

SMS action endpoints are paginated. The implementation requests pages of 100
where needed and protects against unbounded pagination. O2A mission items are
also paginated according to the configured page size.

## Authentication

Public backends require no special setup. For an SMS instance that accepts the
logged-in RDMO user's access token, install
`rdmo_sensorsearch.auth.SensorSearchAuthContextMiddleware` after Django session
and authentication middleware. This makes the request context available to
post-save synchronization.

Authentication failures are reported as refresh errors where feedback fields
exist. Do not put access tokens into catalog XML or TOML configuration committed
to the repository.

## Date-range behavior

The configuration start and end fields are user inputs. Backend configuration
or mission dates do not overwrite them. Free-text editing does not trigger
synchronization; the explicit apply question does.

The presence of the exact Earth Sensor apply trigger attribute
`https://rdmo.nfdi4earth.de/terms/domain/configuration-set/apply-date-range` in
the current catalog determines the behavior:

| Catalog contains apply trigger | Selection behavior |
| --- | --- |
| Yes | Metadata is synchronized, while period-dependent device assignment is deferred to **Apply date range**. |
| No | All configuration or mission members are synchronized immediately without interview date filtering. |

For SMS, mount actions are tested for overlap with the requested period, so a
device can be included only when it was mounted during that range. An omitted
end is open-ended.

For O2A missions, the Registry API does not provide an equivalent historical
mount-action model. Mission items remain the source of membership. The
interview period is propagated to the synchronized mission-item deployment
periods, but it cannot reconstruct changing physical mounts in the way SMS can.

## SMS location, height, and depth

SMS location enrichment uses three concepts:

- a configuration static-location action supplies the site label and its
  vertical `z` anchor;
- device and platform mount actions supply relative `offset_z` values and can
  themselves contain an absolute `z` anchor;
- the plugin follows the active mount chain and adds the vertical offsets below
  the nearest usable anchor. If no mount action contains `z`, it uses the
  static-location `z` after resolving a complete chain.

This can fill the Earth Sensor fields for site name, AMSL height, and relative
height or depth. A negative relative value is retained and can represent, for
example, a sensor one or two metres below the local surface.

Current limitations are important:

- an absolute result requires either a usable `z` in the mount chain or both a
  complete mount chain and a usable static-location `z`;
- the relative height/depth result requires a complete mount chain and
  represents its accumulated `offset_z` values;
- missing or non-numeric offsets are treated as zero, so incomplete backend
  metadata can make a calculated value less accurate without producing an API
  error;
- the plugin adds `z` and `offset_z`; it does not implement a general spatial
  coordinate transformation;
- radial, polar, or otherwise rotated local coordinate systems are not
  converted into Cartesian vertical offsets;
- the correctness of units and coordinate-system interpretation depends on the
  metadata supplied by SMS.

Catalog help text should describe these fields as backend-derived only when the
SMS mount information is complete. Users should be able to review the result
and record explanatory comments for exceptional installations.

## Ownership and manual answers

Fields in `attribute_mapping` are written when a backend response supplies a
value. Fields in `managed_attribute_uris` are explicitly owned by the handler
and may be cleared when no current value exists. Do not mark user-entered
interpretations, planning dates, or comments as managed.

Normal configuration refresh preserves existing device collections. Applying
the date range uses authoritative replacement of configuration membership.
Catalog editors should explain this difference if users can manually add
devices to the selected set.

Generated data-collection variable rows are tracked separately from manual
rows. Cleanup removes generated rows that are no longer supported by selected
devices, while manually entered rows are retained.

## Failure and recovery

Remote timeouts, invalid records, expired authentication, and partial backend
data can produce incomplete synchronization. Where possible, include status,
message, and timestamp questions next to each refresh control. The user can
correct an invalid date range or authentication problem and invoke the same
action again.

An invalid explicit period does not apply a new device assignment. Typical
validation failures are a missing start, an unparsable datetime, or an end
before the start.

Before changing mappings in a production catalog:

1. export the catalog and configuration;
2. test against a separate RDMO project with representative configurations;
3. include devices with no mount history, open-ended mounts, and nested platform
   mounts;
4. verify both catalogs with and without the apply trigger if both are supported;
5. test repeated refreshes to confirm user-owned answers remain unchanged.

## Logging and diagnosis

When a selection produces no metadata, check these items in order:

1. the option ID prefix has a matching provider backend and handler backend;
2. the current catalog URI matches a handler catalog entry or wildcard entry;
3. the search question uses the exact configured `auto_complete_field_uri`;
4. mapping target attributes exist in the catalog's relevant collection;
5. configuration, selected-device, and device collection indexes line up;
6. the remote record is accessible with the current authentication context;
7. for period filtering, the catalog contains the apply trigger and the saved
   input values form a valid period.

Application logs contain the technical request or synchronization error. The
interview feedback message should be the first user-facing diagnostic, but it
does not replace server logs for authentication and API failures.
