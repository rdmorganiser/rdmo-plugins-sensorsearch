"""Dictionary handling is confined to parsing; builders receive typed values."""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from string import Formatter
from types import MappingProxyType
from typing import Any, TypeVar, get_type_hints
from urllib.parse import urlsplit

from rdmo_sensorsearch.config_models.backend_settings import (
    GIPPBackendSettings,
    O2ABackendSettings,
    O2AItemEndpoints,
    O2AMissionEndpoints,
    SMSBackendSettings,
    SMSConfigurationEndpoints,
    SMSDeviceEndpoints,
)
from rdmo_sensorsearch.config_models.contracts import NON_NEGATIVE_INTEGER_SETTINGS, POSITIVE_INTEGER_SETTINGS
from rdmo_sensorsearch.config_models.models import AuthConfig, BackendDefinition
from rdmo_sensorsearch.config_models.validation import (
    ConfigValidationError,
    boolean,
    integer,
    non_negative_integer,
    nonempty_string,
    positive_integer,
    reject_unknown_keys,
    require_mapping,
    string,
    string_sequence,
    table_sequence,
    validate_id_prefix,
)

T = TypeVar("T")
BACKEND_SETTINGS_TYPES = {"sms": SMSBackendSettings, "o2a": O2ABackendSettings, "gipp": GIPPBackendSettings}


def parse_settings(cls: type[T], value: Any, path: str) -> T:
    data = require_mapping(value, path)
    reject_unknown_keys(data, {f.name for f in fields(cls)}, path)
    hints = get_type_hints(cls)
    parsed = {}
    for key, item in data.items():
        item_path = f"{path}.{key}"
        hint = hints[key]
        if is_dataclass(hint):
            parsed[key] = parse_settings(hint, item, item_path)
        elif hint is bool:
            parsed[key] = boolean(item, item_path)
        elif hint is int:
            validate = (
                positive_integer
                if key in POSITIVE_INTEGER_SETTINGS
                else non_negative_integer
                if key in NON_NEGATIVE_INTEGER_SETTINGS
                else integer
            )
            parsed[key] = validate(item, item_path)
        elif hint == tuple[str, ...]:
            parsed[key] = string_sequence(item, item_path)
        else:
            parsed[key] = string(item, item_path, allow_empty=key == "sorts")
        if key == "incomplete_mount_chain_policy" and item not in {"strict", "direct_device_offset"}:
            raise ConfigValidationError(item_path, "must be one of: direct_device_offset, strict")
    try:
        return cls(**parsed)
    except TypeError as exc:
        raise ConfigValidationError(path, f"missing required setting(s): {exc}") from exc


def validate_url(value: str, path: str) -> None:
    try:
        parts = urlsplit(value)
        valid = parts.scheme in {"http", "https"} and parts.hostname and parts.port != 0
    except ValueError:
        valid = False
    if not valid:
        raise ConfigValidationError(path, "expected an absolute HTTP(S) URL")


def endpoint_placeholders(settings: object, name: str) -> set[str]:
    """Match the keyword arguments actually supplied by each existing API call."""
    allowed = {"base_url"}
    if isinstance(settings, SMSBackendSettings):
        if name in {"device_query_url", "configuration_query_url"}:
            allowed |= {"query", "page_size"}
    elif isinstance(settings, O2ABackendSettings):
        if name == "mission_query_url":
            allowed |= {"query", "where", "sorts", "offset", "hits"}
    elif isinstance(settings, SMSDeviceEndpoints):
        allowed.add("id")
        if name == "contact_url":
            allowed |= {"page_size", "page_number"}
    elif isinstance(settings, SMSConfigurationEndpoints):
        allowed.add("id")
        if name in {"device_mount_actions_url", "platform_mount_actions_url", "static_location_actions_url"}:
            allowed |= {"page_size", "page_number"}
    elif isinstance(settings, O2AItemEndpoints):
        if name != "units_url":
            allowed.add("id")
        if name in {"item_api_link_template", "item_frontend_link_template"}:
            allowed.add("base_url_origin")
    elif isinstance(settings, O2AMissionEndpoints):
        allowed.add("id")
        if name == "mission_items_url":
            allowed |= {"offset", "page_size"}
        if name in {"api_link_template", "frontend_link_template"}:
            allowed.add("base_url_origin")
    elif isinstance(settings, GIPPBackendSettings) and name == "json_url":
        allowed.add("id")
    return allowed


def validate_endpoints(settings: object, path: str, base_url: str) -> None:
    sample = {
        "base_url": base_url,
        "base_url_origin": "https://example.com",
        "id": "1",
        "page_size": 10,
        "page_number": 1,
        "offset": 0,
        "hits": 10,
        "query": "example",
        "where": "example",
        "sorts": "",
    }
    for field in fields(settings):
        value = getattr(settings, field.name)
        item_path = f"{path}.{field.name}"
        if is_dataclass(value):
            validate_endpoints(value, item_path, base_url)
        elif value is not None and (field.name.endswith("url") or field.name.endswith("link_template")):
            try:
                names = [name for _, name, _, _ in Formatter().parse(value) if name is not None]
                if any(name not in endpoint_placeholders(settings, field.name) for name in names):
                    raise ValueError("unsupported placeholder")
                rendered = value.format(**sample)
            except (ValueError, KeyError, IndexError) as exc:
                raise ConfigValidationError(item_path, f"invalid URL template: {exc}") from exc
            validate_url(rendered, item_path)


def parse_backends(value: Any) -> Mapping[str, BackendDefinition]:
    definitions: dict[str, BackendDefinition] = {}
    namespaces = set()
    for index, entry in enumerate(table_sequence(value, "backends")):
        path = f"backends[{index}]"
        reject_unknown_keys(
            entry, {"name", "type", "base_url", "auth", "device_id_prefix", "configuration_id_prefix", "settings"}, path
        )
        name = nonempty_string(entry.get("name"), f"{path}.name")
        if name in definitions:
            raise ConfigValidationError(f"{path}.name", f"duplicate backend name {name!r}")
        kind = nonempty_string(entry.get("type"), f"{path}.type")
        if kind not in BACKEND_SETTINGS_TYPES:
            raise ConfigValidationError(f"{path}.type", f"unsupported backend type {kind!r}")
        base_url = nonempty_string(entry.get("base_url"), f"{path}.base_url").rstrip("/")
        validate_url(base_url, f"{path}.base_url")
        settings = parse_settings(BACKEND_SETTINGS_TYPES[kind], entry.get("settings", {}), f"{path}.settings")
        validate_endpoints(settings, f"{path}.settings", base_url)
        prefixes = {}
        for key in ("device_id_prefix", "configuration_id_prefix"):
            prefix = entry.get(key)
            if prefix is not None:
                prefix = validate_id_prefix(prefix, f"{path}.{key}")
                if prefix in namespaces:
                    raise ConfigValidationError(f"{path}.{key}", f"duplicate namespace {prefix!r}")
                namespaces.add(prefix)
            prefixes[key] = prefix
        if kind == "gipp" and prefixes["configuration_id_prefix"] is not None:
            raise ConfigValidationError(path, "GIPP has no configuration capability")
        if not any(prefixes.values()):
            raise ConfigValidationError(path, "at least one external-ID namespace is required")
        auth = None
        if kind == "sms":
            auth = parse_settings(AuthConfig, entry.get("auth", {}), f"{path}.auth")
            if auth.source != "sms_user_token":
                raise ConfigValidationError(f"{path}.auth.source", "only the existing sms_user_token source is supported")
        elif "auth" in entry:
            raise ConfigValidationError(f"{path}.auth", "authentication is currently supported only for SMS")
        definitions[name] = BackendDefinition(name=name, type=kind, base_url=base_url, settings=settings, auth=auth, **prefixes)
    return MappingProxyType(definitions)
