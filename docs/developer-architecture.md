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
| `services/` | Hold backend-neutral domain data and deterministic synchronization decisions. | No |
| `persistence/` | Query and mutate RDMO values through workflow-specific storage adapters. | Yes |
| `signals/` | Adapt RDMO save/delete events, control transactions, and orchestrate services, handlers, and persistence. | Yes |

New decision logic should normally enter `services/`. Signal receivers should
remain transaction and framework adapters; they should not become the only
place where a synchronization rule can be tested.

## Device-detail synchronization

Device-detail materialization now has an explicit planning boundary:

1. `signals/device_detail_sync.py` reads the configuration context, existing
   RDMO device blocks, and registered handler bindings.
2. `services/device_details.py` deduplicates selected devices and produces a
   `DeviceDetailReconciliationPlan` containing retained/new blocks, stale
   blocks, and routing failures.
3. `services/device_metadata.py` invokes only the handlers marked for refresh,
   using a bounded worker pool, and converts handler responses into structured
   payloads or per-device errors.
4. `persistence/device_details.py` applies the plan through an
   `RDMODeviceDetailStore` inside the transaction controlled by the signal,
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
4. keep Django transaction control in `signals/` and RDMO `Value` mutations in
   `persistence/`;
5. keep API fetching and record-specific interpretation in `handlers/`;
6. add pure service tests and at least one adapter/handler regression test.

Avoid importing a signal module merely to obtain a domain dataclass. Shared
types such as `SelectedDevice` belong in `services/`, allowing handlers to use
them without depending on signal registration or Django save hooks.

## Current refactoring boundary

Device planning, bounded metadata fetching, and device-block persistence have
been extracted from the larger `device_detail_sync.py` workflow. The signal
retains transaction control, configuration-context lookup, handler resolution,
and SMS-specific mount enrichment. Future extractions should keep the same
behavior and proceed in small tested slices.

This is an internal module boundary, not a catalog migration. The Earth Sensor
question, attribute, page, option-set, and condition URIs stay unchanged.
