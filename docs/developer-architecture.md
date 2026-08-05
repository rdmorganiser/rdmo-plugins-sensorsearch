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
| `config_models.py` | Parse and validate the complete TOML schema and its cross-references. | No |
| `providers/` | Turn user search text into backend options. | Only aggregate/project-aware adapters |
| `handlers/` | Fetch one selected backend record and return `HandlerResult`. | Only where interview context is required |
| `services/` | Hold backend-neutral domain data, deterministic decisions, and synchronization context state. | No |
| `persistence/` | Query and mutate RDMO values through workflow-specific storage adapters. | Yes |
| `workflows/` | Coordinate complete synchronization use cases shared by handlers and signal adapters. | Yes |
| `signals/` | Adapt RDMO save/delete events and schedule workflows after commit. | Yes |

New decision logic should normally enter `services/`. Signal receivers should
remain transaction and framework adapters; they should not become the only
place where a synchronization rule can be tested.

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
   service and resolves SMS mount periods, height/depth, and site metadata.
6. `persistence/device_details.py` applies the plan through an
   `RDMODeviceDetailStore` inside the transaction controlled by the workflow,
   while recursive post-save processing is muted.

The planner deliberately receives small callbacks for handler resolution and
current-state checks. This keeps registry and database access outside the
service while making allocation, stale detection, routing failures, and refresh
decisions directly unit-testable.

The metadata fetch service propagates the current Python context into each
worker, passes an authentication token only to handlers that declare support,
and rejects handler results containing nested collections or post-actions.
Backend-specific enrichment remains an injected callback; the SMS adapter uses
it to add mount periods and resolved location values without making the generic
fetch service depend on SMS endpoints or Earth Sensor attribute URIs.
`handlers/sms_mounting.py` contains the deterministic mount-period selection
and mount-chain calculations shared by the bulk enricher and direct SMS device
handler. Network response handling stays in the two handler adapters.

## SMS configuration synchronization

`handlers/sms_configuration.py` remains the backend-record adapter, but no
longer owns all supporting algorithms. `handlers/jsonapi.py` performs bounded
JSON:API pagination and duplicate-page detection.
`handlers/sms_configuration_membership.py` selects the latest device mounts
overlapping the optional user period, resolves member metadata through injected
fetch callbacks, and produces typed `SMSConfigurationMember` values. It reuses
the time and mount-location calculations in `handlers/sms_mounting.py`.

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

`services/synchronization_context.py` owns the `ContextVar` that temporarily
mutes recursive value post-save handling. It is safe to nest the context
manager, and the previous state is restored even when a persistence operation
raises an exception. Persistence modules and workflow orchestrators may use
this context; they must not implement separate process-global mute flags.

Modules under `signals/` should represent event receivers and transaction
scheduling. Reusable workflows, collection layout, value mutation, and
context-state helpers do not belong there.

Configured handler bindings are owned by `handlers/catalog_registry.py`.
Signals, handlers, and workflows use that registry directly; lower-level
packages must not import signal adapters merely to resolve a handler. The
registry is initialized lazily so handler class imports cannot create a cycle
while configuration handlers import shared workflows.

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
5. keep API fetching and record-specific interpretation in `handlers/`;
6. add pure service tests and at least one adapter/handler regression test.

Avoid importing a signal module merely to obtain a domain dataclass. Shared
types such as `SelectedDevice` belong in `services/`, allowing handlers to use
them without depending on signal registration or Django save hooks.

## Current refactoring boundary

Device planning, bounded metadata fetching, SMS mount enrichment, device-block
persistence, device-detail orchestration, and data-collection variable
reconciliation have been extracted from the signal package. The SMS
configuration handler delegates pagination and membership resolution to focused
handler components. Signal receivers retain event adaptation and transaction
scheduling. Shared handler registration, refresh result types, collection
binding, value reconciliation, and recursive-signal context also live outside
the signal package. Architecture tests prevent handlers, services, and
workflows from acquiring reverse dependencies on signal adapters.

This is an internal module boundary, not a catalog migration. The Earth Sensor
question, attribute, page, option-set, and condition URIs stay unchanged.
