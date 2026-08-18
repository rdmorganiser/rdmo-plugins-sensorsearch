"""Canonical repository paths shared by tests and development tooling."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TESTING_ROOT = REPOSITORY_ROOT / "testing"
CATALOGS_ROOT = TESTING_ROOT / "catalogs"
FIXTURES_ROOT = TESTING_ROOT / "fixtures"
TOOLS_ROOT = TESTING_ROOT / "tools"
PRODUCTION_CONFIG_PATH = REPOSITORY_ROOT / "sensorsearch.toml"
