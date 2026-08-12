<!--
SPDX-FileCopyrightText: 2026 RDMO Community and individual contributors
SPDX-License-Identifier: Apache-2.0
-->

# Sensor Search documentation for RDMO catalog editors

This documentation explains how an RDMO catalog and `sensorsearch.toml` work
together. It is intended for editors who want to reuse the Earth Sensor
catalog, adapt it to another catalog, or change which sensor registries and
metadata fields are synchronized.

The plugin supports four connected workflows:

1. searching remote devices and configurations or missions;
2. copying backend metadata into RDMO answers;
3. deriving project-local device choices from selected configurations;
4. refreshing metadata and synchronizing data-collection variables.

## Documentation map

- [Catalog editor guide](catalog-editor-guide.md) explains the building blocks
  and gives a safe sequence for adapting a catalog.
- [Configuration reference](configuration-reference.md) describes the TOML
  sections and how each setting relates to catalog elements.
- [Earth Sensor catalog map](earth-sensor-catalog.md) lists the concrete page,
  question, attribute, option-set, provider, and condition URIs from
  `xml/earth-sensor+refresh.xml`.
- [Operations and limitations](operations-and-limitations.md) describes runtime
  behavior, authentication, performance, and current backend limitations.
- [Developer architecture](developer-architecture.md) describes module
  responsibilities and the service boundary used for synchronization logic.
- [SMS location and configuration-period remediation plan](sms-location-and-configuration-period-plan.md)
  records the reviewer findings and the planned resolver, diagnostics,
  configuration, testing, feedback, and catalog-period changes.

The repository-level [`sensorsearch.toml`](../sensorsearch.toml) is the
authoritative deployment configuration and is packaged into the plugin wheel.
The Earth Sensor catalog used by this guide is
[`xml/earth-sensor+refresh.xml`](../xml/earth-sensor+refresh.xml).

## The central editing rule

Catalog and TOML configuration are joined by exact URIs. A question's visible
text is not used for synchronization. When a question or attribute URI changes,
update every corresponding TOML reference and optionset or condition reference.

The following identities must also remain distinct:

- device option IDs use prefixes such as `kitsms`, `gfzsms`, `ufzsms`, and
  `o2aregistry`;
- configuration option IDs use `kitcfg`, `gfzcfg`, `ufzcfg`, and `o2amission`;
- each configuration backend points to the matching device prefix so mounted
  devices can be materialized correctly.

## Recommended starting point

For a new catalog, first import and test the Earth Sensor example unchanged.
Then duplicate one complete workflow at a time. Start with search and a small
metadata mapping, add configuration membership next, and add refresh or
data-collection automation only after the collection attributes and indexes
are correct.
