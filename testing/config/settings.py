"""Minimal RDMO settings used by the plugin's pytest-django tests."""

from pathlib import Path

from rdmo.core.settings import *  # noqa: F403

SECRET_KEY = "sensorsearch-tests"

TEST_BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_ROOT = TEST_BASE_DIR / "static_root"
MEDIA_ROOT = TEST_BASE_DIR / "media_root"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

INSTALLED_APPS = ["rdmo_sensorsearch", *INSTALLED_APPS]  # noqa: F405

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
