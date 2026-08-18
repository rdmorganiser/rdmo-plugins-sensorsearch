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

Each triggering request continues to occupy its web-server worker while the
post-commit synchronization runs. Requests execute concurrently while workers
are available; additional requests wait in the server or reverse-proxy queue.
Device detail materialization can create up to four temporary fetch threads per
active request, so deployments should size worker counts, upstream API limits,
and request timeouts together. Concurrent edits are not serialized by the
plugin; workflows reload committed values, but overlapping derived writes can
still complete in last-writer order.

The plugin parallelizes independent work in a few bounded places: aggregate
provider searches use up to four workers, and device detail materialization
uses up to four workers. Identical GET requests made during one metadata refresh
are deduplicated. These measures reduce repeated work but do not remove remote
API latency.

The request timeout is controlled by the Django setting
`SENSORSEARCH_REQUEST_TIMEOUT` and defaults to 10 seconds. A shorter
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

## Configuration periods and optional membership filtering

In the original Earth Sensor catalog, question set 2.013 is backend-owned when
a configuration or mission is selected. SMS `start_date`/`end_date` or O2A
`startDate`/`endDate` populate the two answers. Selection synchronizes all
current backend members; the catalog contains no apply-filter action.

O2A mission items inherit the backend mission period for their synchronized
instrument start and end answers. The Registry does not expose a historical
mount model.

SMS retains code for an optional, separately modeled membership filter. It is
inactive in the deployment TOML. A future catalog must add distinct filter
start/end attributes and an apply trigger, and its SMS mapping must explicitly
set `membership_filter_enabled = true`. Only that explicit action filters mount
actions by period overlap; ordinary configuration selection never defers.

## SMS location, height, and depth

SMS location enrichment uses three concepts:

- a configuration static-location action supplies the site label and station
  elevation `z`;
- device and platform mount actions supply relative `offset_z` values;
- the plugin follows the active mount chain only to determine the relative
  offset. It does not add an offset or a mount `z` to the station elevation.

This can fill the Earth Sensor fields for site name, station elevation AMSL,
and relative height or depth. A negative relative value is retained and can
represent, for example, a sensor one or two metres below the local surface.

Current limitations are important:

- the AMSL result requires a usable static-location `z` at the resolved time;
- an exact static-location action is preferred. A configured end-time tolerance
  can accept an overlapping action that ended shortly before the device mount;
  actions outside that bounded interval remain unavailable;
- a complete mount chain produces the sum of its `offset_z` values. Under the
  default `strict` policy, a missing parent leaves the relative height/depth
  empty;
- the optional `direct_device_offset` policy uses only the direct device
  action's numeric `offset_z` when its parent action is missing. It never
  invents a missing parent offset and is not used for cyclic chains or an
  invalid direct offset;
- missing or non-numeric offsets in a complete chain continue to contribute
  zero, because SMS does not provide a distinct value for the unavailable
  component. The direct-device fallback is stricter and will not turn such a
  value into a false zero;
- no spatial coordinate transformation is applied; the configured SMS
  static-location `z` is used directly as station elevation;
- the correctness of units and coordinate-system interpretation depends on the
  metadata supplied by SMS.

Location-resolution anomalies are nonfatal. Refresh feedback summarizes how
many devices used a tolerance or direct-offset fallback, or lacked optional
location data, while application logs retain the affected device/action IDs.
These notices do not change a successful refresh into a partial or failed one.
Users should still review the result and record explanatory comments for
exceptional installations.

## Ownership and manual answers

Fields in `attribute_mapping` are written when a backend response supplies a
value. Fields in `managed_attribute_uris` are explicitly owned by the handler
and may be cleared when no current value exists. Question set 2.013 is managed
for selected backend configurations and missions. Do not mark interpretations,
planning dates, comments, or future membership-filter inputs as managed.

Normal configuration refresh preserves existing device collections. Selecting
a backend configuration initially creates its backend-derived membership.

Generated data-collection variable rows are tracked separately from manual
rows. Cleanup removes generated rows that are no longer supported by selected
devices, while manually entered rows are retained.

## Failure and recovery

Remote timeouts, invalid records, expired authentication, and partial backend
data can produce incomplete synchronization. Where possible, include status,
message, and timestamp questions next to each refresh control. The user can
correct an authentication or backend problem and invoke the same action again.

Independent post-commit synchronization concerns are failure-isolated. An
unexpected exception is logged with the event, project, value, and concern, and
remaining concerns continue. The triggering RDMO save has already committed
and is not rolled back; there is no automatic retry queue.

The plugin supports RDMO's default database connection. Project and collection
copies use RDMO bulk operations and intentionally do not trigger external
metadata retrieval; copied answers retain the metadata already stored in the
source project or collection.

For a future SMS membership-filter extension, an invalid explicit period does
not apply a new device assignment. Typical validation failures are a missing
start, an unparsable datetime, or an end before the start.

Before changing mappings in a production catalog:

1. export the catalog and configuration;
2. test against a separate RDMO project with representative configurations;
3. include devices with no mount history, open-ended mounts, and nested platform
   mounts;
4. verify the baseline and any separately approved membership-filter extension;
5. test repeated refreshes to confirm user-owned answers remain unchanged.

## Logging and diagnosis

When a selection produces no metadata, check these items in order:

1. the option ID prefix has a matching provider backend and handler backend;
2. the current catalog URI matches a handler catalog entry or wildcard entry;
3. the search question uses the exact configured `search_attribute_uri`;
4. mapping target attributes exist in the catalog's relevant collection;
5. configuration, selected-device, and device collection indexes line up;
6. the remote record is accessible with the current authentication context;
7. for period filtering, the catalog contains the apply trigger and the saved
   input values form a valid period.

Application logs contain the technical request or synchronization error. The
interview feedback message should be the first user-facing diagnostic, but it
does not replace server logs for authentication and API failures.
