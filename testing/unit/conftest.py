"""Minimal host settings for adapter unit tests, without installing Django."""

import sys
from types import ModuleType, SimpleNamespace

django = sys.modules.setdefault("django", ModuleType("django"))
django_conf = sys.modules.setdefault("django.conf", ModuleType("django.conf"))
django_conf.settings = getattr(django_conf, "settings", SimpleNamespace())
django.conf = django_conf

rdmo = sys.modules.setdefault("rdmo", ModuleType("rdmo"))
rdmo.__version__ = getattr(rdmo, "__version__", "test")
rdmo_options = sys.modules.setdefault("rdmo.options", ModuleType("rdmo.options"))
rdmo_providers = sys.modules.setdefault("rdmo.options.providers", ModuleType("rdmo.options.providers"))
rdmo_providers.Provider = object
rdmo.options = rdmo_options
rdmo_options.providers = rdmo_providers
