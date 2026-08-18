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
