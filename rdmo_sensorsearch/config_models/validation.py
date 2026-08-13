from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from rdmo_sensorsearch.config_models.contracts import PROVIDER_HANDLER_NAMES
from rdmo_sensorsearch.config_models.models import PluginConfig


class ConfigValidationError(ValueError):
    def __init__(self, path: str, message: str):
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


def validate_prefix_contract(config: PluginConfig) -> None:
    handler_prefixes: dict[str, set[str]] = {name: set(handler.id_prefixes) for name, handler in config.handlers.items()}
    all_handler_prefixes = [prefix for prefixes in handler_prefixes.values() for prefix in prefixes]
    reject_duplicate_prefixes(all_handler_prefixes, "handlers")

    provider_instances = (*config.device_search.providers, *config.configuration_search.providers)
    provider_prefixes = [provider.id_prefix for provider in provider_instances if provider.id_prefix]
    reject_duplicate_prefixes(provider_prefixes, "providers")
    for provider in provider_instances:
        prefix = provider.id_prefix
        handler_name = PROVIDER_HANDLER_NAMES[provider.provider_name]
        if prefix not in handler_prefixes.get(handler_name, set()):
            raise ConfigValidationError(
                f"providers.{provider.provider_name}",
                f"id_prefix {prefix!r} has no matching {handler_name}",
            )

    sms_device_prefixes = handler_prefixes.get("SensorManagementSystemDeviceHandler", set())
    sms_configuration = config.handlers.get("SensorManagementSystemConfigurationHandler")
    if sms_configuration:
        for index, backend in enumerate(sms_configuration.backends):
            merged = merge(sms_configuration.backend_defaults, backend)
            device_prefix = merged.get("device_id_prefix")
            if device_prefix not in sms_device_prefixes:
                raise ConfigValidationError(
                    f"handlers.SensorManagementSystemConfigurationHandler.backends[{index}].device_id_prefix",
                    f"{device_prefix!r} has no matching SMS device handler backend",
                )

    mission_handler = config.handlers.get("O2ARegistryMissionHandler")
    item_prefixes = handler_prefixes.get("O2ARegistryItemHandler", set())
    if mission_handler:
        item_prefix = mission_handler.defaults.get("item_id_prefix")
        if item_prefix not in item_prefixes:
            raise ConfigValidationError(
                "handlers.O2ARegistryMissionHandler.defaults.item_id_prefix",
                f"{item_prefix!r} has no matching O2A item handler",
            )


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


def reject_duplicate_prefixes(prefixes: Sequence[str], path: str) -> None:
    seen = set()
    for prefix in prefixes:
        if prefix in seen:
            raise ConfigValidationError(path, f"duplicate id_prefix {prefix!r}")
        seen.add(prefix)


def validate_id_prefix(value: Any, path: str) -> str:
    prefix = nonempty_string(value, path)
    if ":" in prefix or "||" in prefix:
        raise ConfigValidationError(path, "must not contain ':' or '||'")
    return prefix


def reject_unknown_keys(data: Mapping[str, Any], allowed: set[str] | frozenset[str], path: str) -> None:
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise ConfigValidationError(path, f"unknown setting(s): {', '.join(unknown)}")


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


def freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(freeze(item) for item in value)
    return value
