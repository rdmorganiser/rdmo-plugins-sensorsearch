from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rdmo_sensorsearch.config_models.contracts import PROVIDER_HANDLER_NAMES
from rdmo_sensorsearch.config_models.models import PluginConfig


class ConfigValidationError(ValueError):
    def __init__(self, path: str, message: str):
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


def validate_backend_references(config: PluginConfig) -> None:
    from rdmo_sensorsearch.config_models.contracts import CONSUMER_CAPABILITIES

    bindings = set()
    for handler in config.handlers.values():
        seen = set()
        for instance in handler.instances:
            validate_reference(config, handler.handler_name, instance.backend, f"handlers.{handler.handler_name}.instances")
            if instance.backend in seen:
                raise ConfigValidationError(
                    f"handlers.{handler.handler_name}.instances", f"duplicate backend binding {instance.backend!r}"
                )
            seen.add(instance.backend)
            bindings.add((handler.handler_name, instance.backend))
    seen = set()
    for provider in (*config.device_search.providers, *config.configuration_search.providers):
        path = f"providers.{provider.provider_name}"
        validate_reference(config, provider.provider_name, provider.backend, path)
        key = (provider.provider_name, provider.backend)
        if key in seen:
            raise ConfigValidationError(path, f"duplicate backend binding {provider.backend!r}")
        seen.add(key)
        handler_name = PROVIDER_HANDLER_NAMES[provider.provider_name]
        if (handler_name, provider.backend) not in bindings:
            raise ConfigValidationError(path, f"backend {provider.backend!r} has no matching {handler_name}")
    for handler in config.handlers.values():
        if handler.handler_name in {"SensorManagementSystemConfigurationHandler", "O2ARegistryMissionHandler"}:
            device_handler = {"sms": "SensorManagementSystemDeviceHandler", "o2a": "O2ARegistryItemHandler"}[
                CONSUMER_CAPABILITIES[handler.handler_name][0]
            ]
            for instance in handler.instances:
                if (device_handler, instance.backend) not in bindings:
                    raise ConfigValidationError(
                        f"handlers.{handler.handler_name}.instances",
                        f"backend {instance.backend!r} has no matching {device_handler}",
                    )


def validate_reference(config: PluginConfig, consumer: str, backend_name: str, path: str) -> None:
    from rdmo_sensorsearch.config_models.contracts import CONSUMER_CAPABILITIES

    backend = config.backends.get(backend_name)
    if backend is None:
        raise ConfigValidationError(path, f"unknown backend {backend_name!r}")
    backend_type, resource = CONSUMER_CAPABILITIES[consumer]
    if backend.type != backend_type:
        raise ConfigValidationError(path, f"{consumer} requires {backend_type!r}, got {backend.type!r}")
    if resource == "configuration" and backend.device_id_prefix is None:
        raise ConfigValidationError(path, "configuration membership requires a device namespace")
    if (backend.device_id_prefix if resource == "device" else backend.configuration_id_prefix) is None:
        raise ConfigValidationError(path, f"backend {backend_name!r} has no {resource} namespace")


def validate_membership_filter_settings(settings: Mapping[str, Any], path: str) -> None:
    enabled = settings.get("membership_filter_enabled", False)
    start_uri = settings.get("membership_filter_start_attribute_uri")
    end_uri = settings.get("membership_filter_end_attribute_uri")
    if bool(start_uri) != bool(end_uri):
        raise ConfigValidationError(
            path,
            "membership_filter_start_attribute_uri and membership_filter_end_attribute_uri must be configured together",
        )
    if enabled and not start_uri:
        raise ConfigValidationError(
            path,
            "membership_filter_enabled requires membership filter start and end attribute URIs",
        )
    if start_uri and not enabled:
        raise ConfigValidationError(
            path,
            "membership filter attribute URIs require membership_filter_enabled = true",
        )


def validate_membership_settings(settings: Mapping[str, Any], path: str) -> None:
    if not settings.get("selected_devices_attribute_uri"):
        return
    require_string_settings(
        settings,
        {"selected_devices_page_uri", "configuration_collection_attribute_uri"},
        path,
    )


def require_string_settings(settings: Mapping[str, Any], required_keys: set[str], path: str) -> None:
    missing = sorted(key for key in required_keys if not isinstance(settings.get(key), str) or not settings[key].strip())
    if missing:
        raise ConfigValidationError(path, f"missing required setting(s): {', '.join(missing)}")


def validate_provider_name(name: Any, allowed_names: frozenset[str], path: str) -> None:
    if not isinstance(name, str) or name not in allowed_names:
        raise ConfigValidationError(path, f"unknown provider {name!r}; expected one of {sorted(allowed_names)}")


def validate_id_prefix(value: Any, path: str) -> str:
    prefix = nonempty_string(value, path)
    if ":" in prefix or "||" in prefix:
        raise ConfigValidationError(path, "must not contain ':' or '||'")
    return prefix


def reject_unknown_keys(data: Mapping[str, Any], allowed: set[str] | frozenset[str], path: str) -> None:
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        message = f"unknown setting(s): {', '.join(unknown)}"
        if path.startswith(("handlers.", "DeviceSearchProvider.", "ConfigurationSearchProvider.")) and set(unknown) & {
            "base_url",
            "id_prefix",
            "device_id_prefix",
            "item_id_prefix",
            "query_url",
        }:
            message += "; migrate connection settings to top-level [[backends]] (see docs/configuration-reference.md)"
        raise ConfigValidationError(path, message)


def require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigValidationError(path, f"expected a table, got {type(value).__name__}")
    if not all(isinstance(key, str) for key in value):
        raise ConfigValidationError(path, "table keys must be strings")
    return value


def table_sequence(value: Any, path: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise ConfigValidationError(path, f"expected an array of tables, got {type(value).__name__}")
    return tuple(require_mapping(item, f"{path}[{index}]") for index, item in enumerate(value))


def string(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ConfigValidationError(path, f"expected a string, got {type(value).__name__}")
    if not allow_empty and not value.strip():
        raise ConfigValidationError(path, "must not be empty")
    return value


def nonempty_string(value: Any, path: str) -> str:
    return string(value, path)


def optional_nonempty_string(value: Any, path: str) -> str | None:
    return None if value is None else nonempty_string(value, path)


def string_sequence(value: Any, path: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ConfigValidationError(path, f"expected an array of strings, got {type(value).__name__}")
    return tuple(nonempty_string(item, f"{path}[{index}]") for index, item in enumerate(value))


def boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigValidationError(path, f"expected a boolean, got {type(value).__name__}")
    return value


def integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigValidationError(path, f"expected an integer, got {type(value).__name__}")
    return value


def positive_integer(value: Any, path: str) -> int:
    value = integer(value, path)
    if value <= 0:
        raise ConfigValidationError(path, "must be greater than zero")
    return value


def non_negative_integer(value: Any, path: str) -> int:
    value = integer(value, path)
    if value < 0:
        raise ConfigValidationError(path, "must not be negative")
    return value


def merge(base: Mapping[str, Any] | None, override: Mapping[str, Any] | None) -> dict[str, Any]:
    merged = dict(base or {})
    merged.update(override or {})
    return merged
