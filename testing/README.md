# Development and test assets

This directory contains material used to develop and verify the plugin; it is
not included in the plugin wheel.

- `unit/` contains framework-independent tests, run with
  `pytest -c testing/pytest-unit.ini`.
- `integration/django/` contains tests that use RDMO models and Django
  transactions, run with `pytest -c testing/pytest-django.ini` after
  installing the `django-test` extra.
- `catalogs/` contains the authoritative Earth Sensor catalog and the
  independently namespaced `plugin-dev` mirror.
- `fixtures/` contains test-only supporting data and the mirror TOML profile.
- `tools/` contains the generator for the mirror catalog and profile. Run
  `python testing/tools/generate_plugin_dev_assets.py` after changing the
  source catalog or production configuration.
- `config/` contains the minimal Django settings used by the integration
  suite.
- `performance/` contains synthetic fixtures and opt-in measurement helpers.
  The associated regression tests run in `integration/django/` with the normal
  Django suite and assert query counts, output parity, and callback behavior.
  Set `SENSORSEARCH_BENCHMARK_OUTPUT=/tmp/sensorsearch-benchmarks.ndjson` to
  additionally record five warm-ups and twenty measured samples per scenario.
  Use a fresh output path per run; results append. The full benchmark run also
  repeats metadata writes and 1,000-row deletes and can take several minutes.
  All backend responses are mocked and the database is isolated SQLite.

See [the performance review](../docs/performance-review.md) for the environment,
measurement boundaries, results, and remaining deployment checks.

## SMS owner and location interview verification

Automated SMS regressions mock backend responses and use the real catalog and
RDMO models. The interactive widget also needs a check in the target RDMO
installation after importing the updated catalog and deploying its mappings:

1. Select an SMS device with an Owner contact and configuration/static-location
   context. Open its device block on page 2.4: question 2.4.4 must show the
   configuration's site label and 2.4.6 must show the organisation name.
2. Reload the interview. Confirm the imported owner remains selected, the
   dropdown still offers ROR suggestions, and an arbitrary free-text name can
   be entered and saved.
3. Start with a ROR-backed owner matching the SMS name. Refresh and reload;
   confirm the label and ROR identifier remain intact. With a different manual
   name or several SMS institutions, refresh must retain existing names and
   append distinct names with `; `. The combined free-text answer must have
   no ROR identifier or static option attached.
4. Repeat the refresh, then remove Owner roles in a test backend. Confirm names
   are not duplicated or removed. A failed contact request must leave all
   existing metadata intact. Missing referenced contacts must produce owner
   feedback independently of any location feedback.
5. Import the same device through two configurations with different site
   labels. Refresh individual devices and all devices; check each block keeps
   its own site and manual owner answer. A standalone device without
   configuration context must not acquire either configuration's site.

Record the plugin/RDMO versions, catalog/profile used, device/configuration IDs,
and outcomes. These interactive checks are separate from the mocked regression
suite and require an actual interview deployment.
