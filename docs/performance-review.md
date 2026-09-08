# SensorSearch performance review

This review covers plugin base commit `733dfb3` and the performance changes in
this working tree. RDMO was tested from the local
`2.5.2/fix/optimize-answer-tree` branch at `391d7ff49`, associated with
[upstream PR #1752](https://github.com/rdmorganiser/rdmo/pull/1752).
The upstream conclusions below come from that local source checkout.

The plugin changes reduce repeated persisted-state reads and irrelevant signal
work. They preserve synchronous commit-time synchronization, existing data
ownership, normal model saves/deletes, and public provider interfaces. There is
no database migration, background queue, or automatic event coalescing.

## Corrections to the original draft

| Area | Verified finding |
| --- | --- |
| Unrelated saves | Previously resolved authentication and scheduled a Value reload before discovering no applicable stages. The early gate now rejects them first. |
| Ordinary deletes | Previously normally loaded project/catalog and attribute twice: once for immutable context and once in the callback. Unrelated deletes now stop before context construction. |
| Project deletion | Base commit `733dfb3` already skips plugin synchronization for project-instance and project-queryset deletion. This is not a new optimization. |
| Collection deletion | Django still dispatches one delete signal per Value. The existing commit test proved one callback for one event, not coalescing across events. |
| Device-state planning | Fully populated existing blocks previously required five checks per device, plus two root/index queries. Short-circuiting, missing blocks, and forced refresh change that count. |
| Variable parameters | Previously one root query per selected device plus two parameter queries per matching block. The event's selected device could be loaded twice. |
| Collection layout | Two distinct-count queries validate exactly one collection Question or QuestionSet. The validation must be retained, including ambiguity errors. |
| Scalar scopes | The plugin constructs AnswerTree lookup state and calls set-resolution methods; it does not compute a complete answer tree. Setup is reused per mapped result, potentially rebuilt once per refreshed device. |
| Catalog prefetch | Repeated calls on the same prefetched model instance need not repeat SQL. Repeated Python traversal is a separate cost. |
| HTTP | URL-and-token deduplication and a bounded four-worker device fetch pool already existed. Cache scope is the active deduplication context, not a persistent HTTP cache. |
| Timing | Concurrent HTTP durations and nested phases overlap. Subtracting cumulative HTTP and SQL time from workflow wall time does not measure Python time. |
| Writes | `mute_value_sync()` suppresses this plugin's synchronization only. RDMO save timestamps and other signal/file behavior still matter for bulk-write proposals. |
| Compaction | Renumbering currently issues four updates per existing index, including nested-prefix moves. This is a separate deletion hotspot. |

The numeric examples in the original draft were illustrations, not measurements.
Near-constant query targets apply to planning/read phases, not entire metadata
creation or refresh operations.

## Implemented changes

### Device-state planning

`RDMODeviceDetailStore.load_planning_state()` loads roots and required scalar
state in two queries (only the root query is needed when no roots exist). URI
identity is resolved by a join in the scalar query. The detached state supplies
pure planner callbacks and is discarded before persistence.

The lookup preserves any-matching-row semantics for duplicate identity and
completeness values. Roots retain `(set_index, id)` ordering; allocation includes
blank/invalid roots and other configurations in the same prefix. Current Values,
collection flags, parent scopes, and the existing instrument-start child scope
are distinguished explicitly. Legacy store methods remain available for callers
and as the benchmark parity oracle.

### Data-collection variables

`parameters_by_device(external_ids)` batches root lookups and loads names/units
together. Database expressions evaluate both exact and suffix matches. This is
necessary to preserve backend collation and LIKE behavior: SQLite suffix matching
can ignore ASCII case where Python string comparisons do not.

Root requests are bounded to 100 IDs per batch and parameter reads to 500 child
prefixes per batch. The 1–100-device fixture uses two queries; larger workloads
scale with batches. Input duplicates, project-wide device matching, block order,
blank parameters, and latest-ID precedence are preserved.

The workflow loads the union of current selections and the event's device once,
while retaining the difference between parameters eligible for addition and
parameters needed to retain existing variables. `parameters_for_device()` remains
a compatibility wrapper. Existing variable text, units and generated markers
are loaded in one query, preserving manual-variable protection.

### Signal routing and catalog reuse

An immutable, configuration-derived URI registry includes handler search inputs,
configuration roots, selected devices, variable inputs, refresh triggers,
refresh sources, and refresh inputs. Exact and unscoped catalog rules are covered.

Loaded foreign-key relations are reused. An unrelated unloaded attribute needs
one targeted URI query; catalog lookup occurs only for candidate attributes.
Unrelated events perform no authentication lookup and schedule no callback.
No process-wide database-ID cache is introduced. Configuration reset clears both
routing and handler registries; use it for controlled reloads, or restart workers.
It is not an atomic live-reconfiguration protocol across concurrent workers.

Save callbacks still reload committed Values. Delete callbacks recheck current
catalog applicability. If early routing raises, the receiver retains the former
robust callback path rather than failing a normal save due to the new gate.

A nestable workflow catalog context reuses page attribute sets and collection
layout counts, including invalid-layout results. It stores no project Values,
constructs project-bound bindings separately, and is discarded on normal or
exceptional exit. Direct device reconciliation and handler-result application
also establish a context. The four meaningful-value checks now use one OR query
with the original empty/null predicates.

### Catalog repair

The individual device refresh trigger and its status, timestamp and message
fields are always visible, as selected during review. Their backend-device
condition and definition were removed from the authoritative source catalog.
Regeneration confirmed that the development mirror already matched the desired
output. This resolves the four pre-existing catalog consistency/visibility test
failures without changing the tests' intended contract.

## Measurement and regression coverage

The test environment is Python 3.10.21, Django 5.2.17, and an isolated SQLite
in-memory database using the supplied RDMO source. No deployment database or real
backend is used. SQL counts are deterministic assertions; timings are local
comparisons, not deployment latency promises.

Results are recorded in `performance-results.json`; the table below is generated
from the final benchmark run. Baseline comparisons use the original read paths
against identical fixture state, not an entire older plugin deployment.

Validation: **238 unit tests passed; 59 integration tests passed.** Ruff checks
and `git diff --check` passed. The integration run reports 22 existing Django
URLField scheme deprecation warnings.

| Read phase (100 devices) | Original SELECTTs | Bulk SELECTTs | Original median | Bulk median |
| --- | ---: | ---: | ---: | ---: |
| Device planning | 502 | 2 | 278.52 ms | 3.08 ms |
| Parameter loading | 300 | 2 | 223.39 ms | 19.87 ms |

| Current workflow (100 devices) | SELECTTs | Median | p95 |
| --- | ---: | ---: | ---: |
| Unchanged | 3 | 3.93 ms | 5.78 ms |
| Forced refresh, identical metadata | 1407 | 3973.17 ms | 4084.73 ms |
| Reset and initial creation | 1710 | 2795.03 ms | 2984.59 ms |

Unchanged synchronization makes no HTTP calls or writes. Forced refresh
executes 101 mocked HTTP requests but makes no Value writes when metadata is
identical. It still performs 100 scalar-scope setups; their median cumulative
time is 3153.49 ms. This identifies repeated
scope setup and reconciliation reads as follow-up targets even before bulk
writes are considered.

Deletion measurements preserve the existing behavior: 1,000 relevant deleted
Values schedule and execute 1,000 callbacks. Unrelated and whole-project
deletion schedule none. These are routing fixtures, not production benchmarks.

The synthetic matrix covers:

- Existing device planning and parameter loading at 1, 10, 50 and 100 devices.
- Device creation, unchanged synchronization, forced refresh, failure isolation,
  HTTP deduplication and cleanup at the same sizes. The synthetic handler creates
  seven Values per device; this is fixture amplification, not a production ratio.
- Scalar scope setup with 100, 1,000, 5,000 and 10,000 project Values.
- Deleting 1, 10, 100 and 1,000 unrelated/relevant Values and whole projects.
  The relevant-delete fixture measures routing/callback overhead; it deliberately
  has no configured backend stages and does not establish production scope costs.
- Both collection layouts, missing/ambiguous bindings, nested prefixes,
  duplicate rows, snapshots, config reload, muted signals, and savepoint rollback.

`services.performance.capture_performance()` is opt-in and shares a thread-safe
record with copied worker contexts. It records receiver/auth/callback/stage
activity, HTTP requested/executed/cache reuse, scalar setup, loading and fetch
phases. Stage exceptions are counted before the workflow catches them. Value
creation/save/delete counts describe signal activity; queryset updates such as
compaction do not emit save signals. SQL statement counts come from the benchmark
execution wrapper, not those signal counters.

Capture must surround the outermost commit boundary (including its callbacks):

```python
with capture_performance() as record:
    with transaction.atomic():
        value.save()
metrics = record.as_dict()
```

Records contain no tokens, URLs, or answer text. Timing totals overlap; compare
fetch-batch wall time separately from cumulative HTTP execution time. SQL capture
uses the main connection; metadata worker threads perform no ORM work.

## Reproduction

First select the module's configured Python environment. In this checkout:

```sh
.venv/bin/python -m pytest -c testing/pytest-unit.ini -q
.venv/bin/python -m pytest -c testing/pytest-django.ini -q
```

To record benchmarks, set `SENSORSEARCH_BENCHMARK_OUTPUT` to a new NDJSON output
path when running the Django suite. Each scenario records a first invocation,
five unmeasured warm-ups and twenty measured samples; peak allocated memory is
measured separately to avoid distorting timing samples. The first invocation is
not necessarily process-cold because imports and configuration can already be
warm. Each output line includes SQL counts/time, cumulative phases and counters,
median/p95 wall time, and peak memory. Output appends: use a new path per run.

Mutating benchmark scenarios restore their data using a rollback boundary.
Initial-device timing includes cleanup/reset and rollback; use the creation
assertions for row amplification and do not interpret this as pure fetch time.
Existing signal tests and rollback-isolated delete benchmarks explicitly execute
commit callbacks, because pytest-django normally wraps tests in a transaction.

## Remaining architectural investigations

These are intentionally separate from the implemented optimizations:

1. **Coalescing:** collect actual interview request traces and distinguish
   callbacks from scopes doing useful work. RDMO's set-delete endpoint deletes
   its root and descendants in separate calls, without an explicit enclosing
   transaction there. Any batching proposal needs an explicit operation boundary,
   savepoint/rollback behavior, and compatibility review. Do not manipulate
   private connection callback queues or defer work to request end implicitly.
2. **Scalar scope reuse:** measure repeated setup across refreshed devices after
   the read improvements. Retain AnswerTree set semantics until a narrower index
   or broader lifetime is proven safe across generated writes.
3. **Amplification and writes:** inventory production rows by ownership, find
   stale/duplicate data, and profile compaction and normal saves. Do not remove
   persisted fields or batch writes without a separate data/side-effect contract.
4. **Indexes:** inspect slow SQL with representative cardinality and query plans
   after batching. No plugin-specific core index is justified by these SQLite
   microbenchmarks alone.
5. **Deployment validation:** measure real backend latency and project-device
   option requests, then smoke-test the interview's navigation, selected-device
   edits, refresh controls, nested collections, and generated variables. Real
   backend and browser checks were not performed in this isolated test run.

Each optimization can be reviewed and reverted independently of the upstream
RDMO branch. Preserve the unrelated lockfile and existing staged review when
preparing commits; this implementation does not automatically commit or publish.
