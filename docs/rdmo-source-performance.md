# RDMO interview performance: incremental source changes

This document is a shared working guide for improving the RDMO request cycle
used by the Earth Sensor interview. It is intended for incremental work by the
plugin maintainers, Codex, and the upstream RDMO maintainer.

The changes described here are deliberately split into small upstream pull
requests. Each pull request must preserve the existing API responses and land
with its own regression tests and performance evidence. The combined changes
currently staged in the local RDMO checkout are a prototype and should not be
submitted as one patch.

## Objective

Reduce the server time spent loading interview navigation and resolving
conditions, especially for projects with many values and catalogs with many
questions, without changing:

- navigation, answer-tree, progress, or resolve response formats;
- condition semantics or collection/set scoping;
- permission and not-found behavior;
- snapshot behavior;
- verbose answer exports; or
- database schemas or stored project data.

The two primary requests are:

```text
GET  /api/v1/projects/projects/37/navigation/70/
POST /api/v1/projects/projects/37/resolve/
```

The resolve payload of interest is the batch generated while loading interview
page 351. The answer-tree changes also affect the answers and progress
endpoints, so those consumers are part of the regression scope even when their
performance is not the immediate target.

Catalog-only work, such as removing unnecessary per-device conditions, remains
in this plugin and is independent from the RDMO changes below.

## Current findings

### Request cost drivers

The investigation identified these costs in the RDMO source:

1. `AnswerTree` repeatedly scans every project value while computing individual
   question nodes.
2. The value queryset is evaluated once for the tree and queried again with
   `DISTINCT` to compute the available sets.
3. Condition evaluation accesses `Value.attribute` and `Value.option`, which can
   hydrate related objects when only their IDs are needed.
4. A batched resolve request can contain the same condition set and scope more
   than once, but each occurrence is evaluated independently.
5. The navigation action starts from the regular project queryset, including
   serializer-oriented prefetches and a correlated `last_changed` subquery that
   the action does not use.
6. The catalog element graph already prefetches element conditions, while the
   answer tree separately constructs an expensive catalog-wide condition
   queryset.

### Preliminary measurements

These timings came from the combined local prototype and are evidence that the
approach is worthwhile. They are not acceptance results for any individual
change and must be reproduced from a clean parent commit.

| Request | Before prototype | Combined prototype |
| --- | ---: | ---: |
| Navigation, warm request | approximately 0.87–1.20 s | approximately 0.447 s |
| Batched resolve | approximately 2.231 s | approximately 0.164 s |

The originally observed navigation request took close to five seconds in the
development deployment. Differences between that observation and the local
warm benchmark can come from cold caches, server configuration, database load,
logging, and network overhead. For that reason, SQL counts and response parity
are tracked alongside wall-clock timings.

### Prototype state on 2026-08-28

The local RDMO branch `2.5.2/fix/optimize-navigation` contains a staged prototype
in the following areas:

- condition resolution;
- answer-tree value lookup;
- project answer-tree queryset construction;
- project navigation and resolve actions; and
- focused answer-tree and viewset tests.

The prototype is useful as a reference, but two details need correction during
incremental implementation:

- Testing whether `catalog.descendants` is a list does **not** prove that every
  element's `conditions` relation was prefetched. The optimized condition path
  must inspect Django's prefetch cache and retain a safe fallback.
- `catalog.sections.all()` does not reuse the nested
  `catalog_sections__section` prefetch. Section lookup should use the ordered
  `catalog.elements` list after `prefetch_elements()`.

A focused prototype run produced 41 passing tests. One additional performance
test failed before reaching an assertion because Django Compressor attempted to
write generated assets into the read-only RDMO checkout. That test must be
rerun in a writable test environment; it is not recorded as a passing test.

## Compatibility contract

No public API or database migration is planned. The following behavior is the
contract against which each pull request is checked:

- Navigation JSON has the same section/page ordering, IDs, titles, visibility,
  counts, totals, and `first` values.
- Resolve POST returns one result for every input item, in the original input
  order, with unchanged boolean results.
- Resolve GET retains its current precedence across page, question set,
  question, option set, and direct-condition parameters.
- A condition remains true when any attached condition resolves true; an
  element without conditions remains visible.
- Parent-scope fallback for nested sets and the special handling of
  `set_collection=False` remain unchanged.
- Answer-tree counts and empty-state handling remain identical for text,
  option, file, and external-ID values.
- `verbose=value` continues to return complete value dictionaries and may load
  related attributes/options; reduced query projections are only used by paths
  that need scalar fields.
- Current values and snapshot values never become mixed.
- Existing permissions, 401/403/404 responses, and invalid section handling
  remain unchanged.

## Incremental upstream pull requests

Each pull request should start from the upstream branch containing all earlier
accepted increments. Do not build the review series by committing the existing
combined staged diff in place; reconstruct and validate one change at a time.

### PR 1: Use a navigation-specific project queryset

**Purpose:** remove work that occurs before the answer tree is built but is not
used by the navigation action.

Implementation:

- In `rdmo/projects/viewsets.py`, return a lightweight queryset when
  `self.action == "navigation"`.
- Retain `select_related("catalog", "visibility")`; catalog data is required by
  navigation and visibility may be required by object permissions.
- Do not prefetch snapshots, views, or memberships for navigation.
- Do not add the correlated `last_changed` annotation for navigation.
- After `project.catalog.prefetch_elements()`, resolve an optional section ID
  from `project.catalog.elements`. Do not query `catalog.sections` separately.
- Preserve the current `NotFound` result for an invalid or foreign section ID.

Tests and review evidence:

- Existing navigation permission tests for every role.
- Navigation with no section, a valid section, an invalid section, no sections,
  and sections without pages.
- Exact JSON comparison before and after the change.
- A dedicated navigation query-count assertion, including a request with a
  section ID.
- SQL trace showing that serializer prefetches and `last_changed` are absent.

Rollback boundary: reverting this pull request restores only queryset and
section lookup behavior; it has no dependency on the later value changes.

### PR 2: Resolve conditions using scalar foreign-key IDs

**Purpose:** avoid loading `Attribute` and `Option` objects when condition
evaluation only needs identity or presence.

Implementation:

- In `Condition.resolve`, match source values with
  `value.attribute_id == condition.source_id`.
- In equality checks, compare `value.option_id` with
  `condition.target_option_id`.
- In not-empty checks, use `option_id` presence instead of accessing `option`.
- Keep the plain-iterable fallback so callers can continue to pass querysets,
  lists, tuples, or generators.
- Do not alter text, numeric, contains, empty/not-empty, or parent-scope logic.

Tests and review evidence:

- Characterization tests for every relation type with text and option targets.
- Values with `attribute_id=None` and `option_id=None`.
- `set_collection` values of `True`, `False`, and `None`.
- Nested `set_prefix` fallback and multiple collection indexes.
- The same results for a queryset and a materialized list.
- Query capture proving that evaluation does not fetch an attribute or option
  per value.

Rollback boundary: this is a self-contained model-level optimization and
introduces no new helper type.

### PR 3: Index values for resolve requests and reuse duplicate results

**Purpose:** replace repeated scans of the project's values and avoid resolving
identical entries more than once within one POST request.

Implementation:

- Introduce an internal `ValueIndex` that materializes its input once, remains
  iterable, and groups values by `attribute_id`.
- Let `Condition.resolve` use `for_attribute(source_id)` when the input provides
  it and retain the iterable fallback from PR 2.
- In resolve GET and POST, load only the scalar fields needed by conditions:
  attribute ID, set prefix/index, set-collection flag, text, and option ID,
  together with required model identity fields.
- Remove the model's default ordering for these resolve-only queries because
  condition results do not depend on value order.
- In resolve POST, memoize by
  `(sorted condition IDs, set_prefix, set_index)`.
- Preserve output order and append a result for every submitted input item,
  including duplicates.

Tests and review evidence:

- `ValueIndex` preserves iteration order and returns all values for an
  attribute; a missing attribute returns an empty immutable iterable.
- Resolve GET/POST response parity with the parent commit.
- Repeated identical entries call `Condition.resolve` once.
- Entries with different condition sets or scopes are not combined.
- Multiple elements with the same condition set can reuse a result because
  condition evaluation is OR-based and element identity does not affect it.
- Empty condition sets, missing element IDs, invalid input, and permission
  responses preserve current behavior.
- Query count is independent of the number of duplicate resolve entries.

Rollback boundary: the helper and both resolve uses revert together; the answer
tree does not use the helper until PR 4.

### PR 4: Index values inside the answer tree

**Purpose:** change answer-tree value work from repeated full scans to one
materialization pass followed by indexed lookups.

Implementation:

- Wrap answer-tree values in the `ValueIndex` introduced in PR 3.
- Build the set map during that pass instead of calling the queryset's separate
  `compute_sets()`/`DISTINCT` query.
- Build a composite lookup keyed by
  `(attribute_id, set_prefix, set_index)` for question values.
- Preserve the queryset's effective order: attribute, set prefix, set index,
  and collection index.
- For non-verbose trees, select only the fields used by set computation,
  condition resolution, collection ordering, and empty-state calculation.
- Compute non-verbose empty state from scalar `text`, `option_id`, `file`, and
  `external_id` fields.
- For `verbose=value`, keep complete model fields with related attribute and
  option objects so `Value.as_dict` remains unchanged.
- Preserve values whose attribute is null; they must not be accidentally
  assigned to a real question.

Tests and review evidence:

- The indexed set map equals `ValueQuerySet.compute_sets()` for fixture data.
- Exact answer-tree equality between the old and new implementations for
  navigation, progress, default answers, and verbose answers.
- Non-collection pages, collection pages, nested question sets, empty sets,
  multiple collection values, and null attributes.
- Current and snapshot answer trees.
- Empty-state coverage for text, option, file, external ID, and an unsaved empty
  placeholder value.
- A query-count assertion showing removal of the extra set query and no deferred
  field queries.

Rollback boundary: answer-tree and `Project.get_answer_tree()` changes revert
together; resolve behavior from PR 3 remains usable.

### PR 5: Reuse conditions already prefetched with catalog elements

**Purpose:** avoid the catalog-wide annotated condition query during
navigation, answers, and progress when the caller has already prefetched the
element graph.

Implementation:

- Inspect pages, question sets, and questions in `catalog.descendants`.
- Use their attached condition objects only when `conditions` exists in each
  relevant element's `_prefetched_objects_cache`.
- If any relevant relation is not confirmed as prefetched, fall back to the
  existing `catalog.conditions.in_bulk()` path.
- Deduplicate the optimized condition map by primary key.
- Do not call `.conditions.all()` merely to determine whether a prefetch exists;
  doing so can introduce one query per element.
- Keep `select_related("source", "target_option")` in the existing catalog
  condition prefetch so scalar condition evaluation has all condition metadata.

Tests and review evidence:

- A prefetched catalog uses the element condition objects and does not evaluate
  the catalog-wide annotated queryset.
- A non-prefetched or partially prefetched catalog uses the fallback and
  produces the same answer tree.
- A condition attached to several elements is represented once by ID.
- Catalogs with no conditions and with conditions on pages, nested question
  sets, and questions.
- Exact query counts prove that neither path creates an N+1 pattern.

Rollback boundary: this final change affects only how the answer tree obtains
condition objects; all earlier indexing improvements remain independent.

## Test matrix

Run the smallest relevant group while developing each pull request, then expand
before review:

1. Condition model and set-scope tests.
2. Answer-tree, navigation, and progress unit tests.
3. Project viewset navigation and resolve tests, including all permission
   parametrizations.
4. RDMO's performance/query-budget tests.
5. The complete RDMO test suite on the supported Python/Django matrix.
6. The sensorsearch plugin unit and Django integration suites against the RDMO
   branch.
7. An authenticated browser smoke test of project 37, interview page 351.

The browser smoke test should check:

- navigation titles, order, visibility, progress counts, and totals;
- manual devices and backend-linked devices;
- nested device collection rows;
- conditionally hidden pages, question sets, and questions;
- option-backed and text-backed conditions;
- per-device refresh controls and metadata refresh behavior; and
- browser/network errors during the complete request cycle.

## Benchmark procedure

Benchmark the parent commit and the candidate commit using the same application
configuration, database copy, authenticated user, and project. Disable debug
toolbar and unrelated verbose SQL logging.

For every relevant request:

1. Perform five warm-up requests.
2. Perform 20 measured sequential requests.
3. Record median and p95 wall time.
4. Record SQL query count and cumulative SQL time.
5. Store the HTTP status and a canonical JSON hash or exact JSON fixture.
6. Inspect the slowest SQL statements and check for repeated/deferred-field
   queries.

Use the real navigation URL and capture the exact resolve POST payload emitted
by page 351. Also benchmark answers and progress for PRs 4 and 5.

An increment is ready for review only when:

- response JSON and status codes are unchanged;
- focused and complete test suites pass;
- query counts do not increase;
- the targeted request's median improves; and
- p95 latency does not regress by more than 10%.

Timing results are comparative, not universal targets. If timing noise obscures
a small change, repeat the run and prioritize deterministic query-count and SQL
trace evidence.

## Per-PR review checklist

Copy this checklist into every upstream pull request:

```markdown
- [ ] Parent commit and test environment recorded
- [ ] Before/after response parity demonstrated
- [ ] New characterization/regression tests included
- [ ] Focused RDMO tests pass
- [ ] Complete RDMO test suite passes
- [ ] Supported Python/Django matrix passes
- [ ] Query count before/after recorded
- [ ] Median and p95 timing before/after recorded
- [ ] SQL trace checked for N+1/deferred-field queries
- [ ] Sensorsearch integration tests pass
- [ ] Earth Sensor interview smoke test passes
- [ ] No migration or public API change introduced
- [ ] Rollback is limited to this pull request
```

## Working log template

Use one table per pull request so later work does not rely on memory or timings
from a different code state:

| Field | Parent | Candidate |
| --- | --- | --- |
| Commit |  |  |
| Python / Django |  |  |
| Database |  |  |
| Endpoint / payload |  |  |
| Response hash |  |  |
| SQL queries |  |  |
| Cumulative SQL time |  |  |
| Median of 20 |  |  |
| p95 of 20 |  |  |
| Focused tests |  |  |
| Full suite |  |  |
| Notes / slow queries |  |  |

## Working-tree safety

- Preserve the current staged RDMO prototype until its useful details have been
  reconstructed or saved as a patch by the developer.
- Do not reset, overwrite, or mix the prototype with an incremental PR branch.
- Start each implementation from the appropriate clean upstream commit in a
  separate branch or worktree.
- Leave unrelated and untracked lockfiles untouched.
- Re-run the previously blocked asset-rendering performance test in a writable
  RDMO test checkout before claiming complete validation.
