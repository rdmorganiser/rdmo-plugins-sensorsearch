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
