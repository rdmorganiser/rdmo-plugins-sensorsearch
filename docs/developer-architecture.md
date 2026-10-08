<!--
SPDX-FileCopyrightText: 2026 RDMO Community and individual contributors
SPDX-License-Identifier: Apache-2.0
-->

# Developer architecture

[Documentation index](index.md) · [Configuration reference](configuration-reference.md) · [Operations and limitations](operations-and-limitations.md)

This page describes the internal boundaries to preserve when extending the
plugin. Catalog URIs remain the external contract: refactoring Python modules
must not rename them.

## Module responsibilities

| Area | Responsibility | May depend on Django models? |
| --- | --- | --- |
| `config_models/` | Define, parse, and validate the complete TOML schema and its cross-references. | No |
| `backends/` | Fetch and normalize external records through injected transport capabilities. | No |
| `providers/` | Turn user search text into backend options. | Only aggregate/project-aware adapters |
| `handlers/` | Fetch one selected backend record using immutable context and return data/effects. | No |
| `services/` | Hold backend-neutral domain data, deterministic decisions, and synchronization context state. | No |
| `persistence/` | Query and mutate RDMO values through workflow-specific storage adapters. | Yes |
| `workflows/` | Coordinate complete synchronization use cases shared by handlers and signal adapters. | Yes |
| `signals/` | Adapt RDMO save/delete events and schedule workflows after commit. | Yes |

New decision logic should normally enter `services/`. Signal receivers should
remain transaction and framework adapters; they should not become the only
place where a synchronization rule can be tested.

`contracts.py` owns the immutable data shared between these layers: handler
results and execution context, collection assignments, selected devices,
configuration periods, device settings, and notices. It imports only the
standard library. Consumers import these types directly rather than depending
on their former implementation packages. Scalar reconciliation accepts the
small `ScalarScopeResolver` protocol declared there.

Every handler returns `HandlerOutcome`: either `HandlerResult` with mapped
values, collections, effects, and notices, or `HandlerFailure` with an ordered
tuple of error messages. Consumers report failures before enrichment,
persistence, or effect execution. Handler error dictionaries are unsupported.
SMS, O2A, and GIPP adapters return `BackendFailure`; handlers translate it into
`HandlerFailure` before applying catalog mappings.

Device-profile selection is a pure service receiving an explicit `PluginConfig`.
Workflows load deployment configuration before calling it, so services do not
acquire an indirect Django dependency through the configuration loader.

## Configuration model

`rdmo_sensorsearch.config_models` remains the public import path for
`PluginConfig`, `BackendDefinition`, and `ConfigValidationError`. Section and
settings types live in their explicit submodules. Its
implementation is grouped by responsibility:

- `contracts.py` contains supported provider/handler names, defaults, and
  allowed TOML settings;
- `models.py` contains the immutable section dataclasses;
- `parsing.py` converts TOML mappings into those models;
- `validation.py` contains primitive validation helpers and cross-reference
  checks such as provider-to-handler prefix matching.

These modules must remain independent of Django and RDMO models so deployment
configuration can be validated in isolation.

## Device-detail synchronization

Device-detail materialization now has an explicit planning boundary:

1. `signals/receivers.py` adapts RDMO save/delete events and schedules the
   device-detail workflow after the surrounding transaction commits.
2. `workflows/device_details.py` reads the configuration context, existing
   RDMO device blocks, and registered handler bindings.
3. `services/device_details.py` deduplicates selected devices and produces a
   `DeviceDetailReconciliationPlan` containing retained/new blocks, stale
   blocks, and routing failures.
4. `services/device_metadata.py` invokes only the handlers marked for refresh,
   using a bounded worker pool, and converts handler responses into structured
   payloads or per-device errors.
5. `handlers/sms_device_enrichment.py` is injected into that generic fetch
   service and applies mount metadata returned by injected backend capabilities.
6. `persistence/device_details.py` applies the plan through an
   `RDMODeviceDetailStore` inside the transaction controlled by the workflow,
   while recursive post-save processing is muted.

The planner deliberately receives small callbacks for handler resolution and
current-state checks. This keeps registry and database access outside the
service while making allocation, stale detection, routing failures, and refresh
decisions directly unit-testable.

The metadata fetch service propagates the current Python context into each
worker, passes an optional authentication token to every handler,
and rejects handler results containing nested collections or effects.
Backend-specific enrichment remains an injected callback; the catalog adapter
uses it to add mount periods and resolved location values without making the generic
fetch service depend on SMS endpoints or Earth Sensor attribute URIs.
`backends/sms/mounting.py` contains the deterministic mount-period selection
and mount-chain calculations shared by backend period/location capabilities.
Network response handling stays in the SMS backend.

## SMS configuration synchronization

SMS search providers and the device handler receive capabilities assembled by
the existing factories. `backends/sms/` owns device/contact requests, owner
normalization, frontend links and direct mount lookups. Its transport is an
injected callable, with authentication passed per call. `BackendSuccess` and
`BackendFailure` distinguish empty successful metadata from failures; mapping
documents retain their existing JSON and `sms_owner_organizations` paths.
`backend_assembly.py` receives typed definitions and consumer profiles. Its
builder registry is keyed by the explicit backend type; consumer builders
request device, configuration, or search capabilities. SMS constructs an
injected adapter, as do O2A and GIPP. No runtime consumer reads `.raw`, calls the
removed mapping loader, or serializes configuration back into constructor
kwargs. The TOML was migrated once; persisted identifiers remain unchanged.

Typed assembly is the supported construction path for backend-specific
consumers. Providers require keyword-only `id_prefix`, `text_prefix`,
`max_hits`, and an injected capability backend; handlers require keyword-only
`id_prefix`, `attribute_mapping`, and an injected capability backend.
Handlers own a mutable copy of the supplied mapping. Constructors do
not accept arbitrary settings or fall back to class-level connection defaults.
Assembly assigns catalog settings after construction. Endpoint templates and
canonical typed SMS settings belong to backend adapters, without a second set
of runtime defaults. RDMO-facing aggregate and project-local providers retain their
framework entry points and normal construction behavior.

Backend definitions distinguish installation names from device/configuration
namespaces. Search filtering uses those declared relationships, not prefix
suffix conventions. Authentication remains request-specific. Catalog mappings,
labels, and workflow capability flags stay with consumers; endpoint templates
and SMS mount policies stay in backend-specific settings. Definition validation
precedes reference/capability checks, and configuration-only tooling imports no
Django or RDMO modules.

The configuration handler consumes typed configuration and membership results.
The SMS backend owns bounded JSON:API pagination, duplicate-page detection,
contact joins, membership selection, and mount/location calculations. Member
records carry backend-local IDs and normalized metadata; the handler supplies
configured prefixes, option labels, catalog mappings, collections and effects.
Static locations fetched for membership also supply configuration coordinates,
without a second request.

The bulk enricher is a catalog adapter over injected mount capabilities. Supplied
member metadata takes precedence and avoids requests. Direct refresh fails on
mount-request errors; bulk refresh requests best-effort resolution, logs typed
failure diagnostics and retains the previous partial-data policy. Authentication
and cache lifetime remain outside the backend; adapters have no mutable
request-specific state.

## Remote adapters and transport

All remote providers and handlers consume small protocols from `contracts.py`.
Metadata, membership, mounts, and static locations remain separate capabilities;
composition protocols describe consumers that need more than one.

`backends/o2a/` separates item and mission API mechanics. It owns contact joins,
unit lookup, bounded membership pagination, validation, and identity-derived
links. O2A handlers retain JMESPath mapping, datetime formats, member labels,
collection assignments, and refresh effects. Backend-specific mapping fields
remain in the metadata document. `backends/gipp/` owns instrument search and
metadata requests while its consumers apply configured presentation and mapping.
Both adapters ignore the optional SMS authentication token.

`client.py` returns decoded JSON or raises `TransportError` for HTTP, connection,
timeout, and JSON decoding failures. The neutral `transport.py` helper translates
only that exception into `BackendFailure` and copies successful documents before
normalization. Unexpected programming errors propagate.

The request cache keys responses and transport failures by URL and authentication
token. Concurrent waiters and later callers reuse the failure within the current
request or refresh scope; a fresh scope retries. Exceptions release waiters,
and successful empty JSON values remain cacheable. Cache lifetime and metrics
stay outside backend adapters.

## Data-collection variable synchronization

Data-collection variable generation follows the same three-layer pattern:

1. `workflows/data_collection_variables.py` resolves catalog settings and
   coordinates one reconciliation transaction;
2. `persistence/data_collection_variables.py` reads device parameters and
   existing RDMO variable rows, then applies planned creates and deletions;
3. `services/data_collection_variables.py` creates a deterministic
   `DataCollectionVariablePlan` without importing Django.

Generated rows retain their `sensorsearch:dc-variable:` marker. The planner
never deletes unmarked editor/user rows, normalizes name/unit pairs for
deduplication, and only removes generated rows no longer supplied by any
selected device.

## Shared reconciliation and signal context

`persistence/value_reconciliation.py` is the shared write engine for scalar,
list, and handler collection results. It uses
`persistence/collection_binding.py` to distinguish collection Questions from
collection QuestionSets and to calculate their RDMO value scopes.

`persistence/scope_resolver.py` is the only adapter that imports RDMO's
`AnswerTree`. It supports both the 2.5.1 constructor taking values and the API
introduced by RDMO PR #1752, which takes values in `compute()`. Constructor
signature inspection selects the API before initialization; actual failures
propagate without retrying a different constructor. One resolver indexes live
values once per reconciliation and caches scope lookups, retaining source-scope
fallback and excluding snapshots.

`services/synchronization_context.py` owns the `ContextVar` that temporarily
mutes recursive value save/delete synchronization. It is safe to nest the
context manager, and the previous state is restored even when a persistence
operation raises an exception. Persistence modules and workflow orchestrators
may use this context; they must not implement separate process-global mute
flags.

Modules under `signals/` should represent event receivers and transaction
scheduling. Reusable workflows, collection layout, value mutation, and
context-state helpers do not belong there.

`signals/receivers.py` registers one `post_save` and one `post_delete` adapter
for RDMO `Value`. Save events ignore Django's raw fixture-loading mode and pass
only the value ID into one post-commit callback; the workflow then reloads the
committed row. Delete events pass an immutable field snapshot because the row
no longer exists after commit. `workflows/value_events.py` routes each event
through the applicable synchronization concerns in a stable order. An
unexpected failure is logged per concern and does not suppress later concerns.

Configured handler bindings are owned by `handlers/catalog_registry.py`.
Signals, handlers, and workflows use that registry directly; lower-level
packages must not import signal adapters merely to resolve a handler. The
registry is initialized lazily. Handlers return declarative
`RefreshDeviceDetails` effects instead of importing workflows or capturing RDMO
models in callbacks. `workflows/backend_value_sync.py` interprets those effects
after its scalar/collection write transaction completes, supplying project,
scope, configuration identity and authentication. Persistence only writes data.
A storage failure prevents effects; a follow-up failure leaves the already
stored metadata intact and reports the existing failed-refresh result.

Device block external IDs use this internal identity format:

```text
<configuration external ID>||<device external ID>
```

Use `compose_device_block_key()` and `parse_device_block_key()` rather than
duplicating separator logic. Provider/handler prefixes must not contain `||`;
the TOML model validates that constraint.

## Safe extension pattern

When adding a synchronization feature:

1. model backend-neutral inputs and outputs with frozen dataclasses;
2. put deterministic selection, filtering, and planning in a service;
3. inject framework or network lookups through narrow callbacks or adapters;
4. keep Django transaction control in `workflows/` and RDMO `Value` mutations
   in `persistence/`;
5. keep API fetching and record-specific interpretation in backend adapters,
   with handlers applying catalog mappings and declaring effects;
6. add pure service tests and at least one adapter/handler regression test.

Avoid importing a signal module merely to obtain a domain dataclass. Shared
types such as `SelectedDevice` belong in `contracts.py`, allowing handlers to use
them without depending on signal registration or Django save hooks.

## Current refactoring boundary

Device planning, bounded metadata fetching, SMS mount enrichment, device-block
persistence, backend-value synchronization, metadata refresh,
configuration-tab updates, device-detail orchestration, and data-collection
variable reconciliation have been extracted from the signal package. The SMS
configuration handler consumes normalized membership and location results from
an injected SMS backend. Signal receivers retain event adaptation and transaction
scheduling. Shared handler registration, refresh result types, collection
binding, value reconciliation, and recursive-signal context also live outside
the signal package. Architecture tests prevent handlers, services, and
workflows from acquiring reverse dependencies on signal adapters.

Handlers expose `handle(backend_id, *, context, auth_token=None)` and never
receive RDMO model instances. Workflows prepare `HandlerExecutionContext`;
`persistence/handler_context.py` reads configuration roots and membership dates
from the exact live collection scope, selecting the newest matching row. Invalid
membership periods fail before backend fetching. The handler keeps backend
capability checks and receives only the validated period and configuration
reference.

Bulk metadata fetching receives catalog-specific device settings explicitly.
Its worker context has no configuration reference, so direct handlers do not
repeat mount lookups already owned by the injected bulk enricher. The small
value context used by scalar writes lives privately in persistence.

Architecture tests prohibit services from importing implementation layers or
the configuration loader, handlers from importing workflows/storage/frameworks,
and any runtime module other than the scope adapter from importing `AnswerTree`.
They also prohibit concrete backend and HTTP-client imports in all remote consumers,
and framework, consumer, or deployment-loader imports in backend adapters.
They inspect nested packages and relative imports as well as absolute imports.

This is an internal module boundary, not a catalog migration. The Earth Sensor
question, attribute, page, option-set, and condition URIs stay unchanged.
