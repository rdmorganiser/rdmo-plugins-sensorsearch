"""Minimal host settings for adapter unit tests, without installing Django."""

import sys
from types import ModuleType, SimpleNamespace

django = sys.modules.setdefault("django", ModuleType("django"))
django_conf = sys.modules.setdefault("django.conf", ModuleType("django.conf"))
django_conf.settings = getattr(django_conf, "settings", SimpleNamespace())
django.conf = django_conf
