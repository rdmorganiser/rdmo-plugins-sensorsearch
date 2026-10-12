"""Public configuration boundary: immutable models and path-aware validation."""

from rdmo_sensorsearch.config_models.models import BackendDefinition, PluginConfig
from rdmo_sensorsearch.config_models.validation import ConfigValidationError

__all__ = ("BackendDefinition", "ConfigValidationError", "PluginConfig")
