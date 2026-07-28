import re

_DEVICE_FIRST_MEMBERSHIP_PATTERN = re.compile(
    r"^(?P<identity>.+?\([^()\n]*\)) "
    r"(?P<relationship>Config|Cfg|Mission|M)\((?P<relationship_id>[^()\n]*)\): "
    r"(?P<description>.+)$"
)
_CONFIGURATION_FIRST_MEMBERSHIP_PATTERN = re.compile(
    r"^(?:(?P<relationship_acronym>[A-Za-z0-9._-]+) )?"
    r"(?P<relationship>Config|Cfg|Mission|M)\((?P<relationship_id>[^()\n]*)\) "
    r"(?P<identity>.+?\([^()\n]*\)): "
    r"(?P<description>.+)$"
)
_CONFIGURATION_TAB_PREFIX_PATTERN = re.compile(r"^[^:\n]+ (?:Cfg|M)\([^()\n]+\)(?::\s*)?")


def configuration_short_label(external_id: str | None) -> str | None:
    """Return a compact backend-aware label for a configuration or mission."""
    if not external_id or ":" not in external_id:
        return None

    id_prefix, identifier = external_id.split(":", 1)
    id_prefix = id_prefix.strip()
    identifier = identifier.strip()
    if not id_prefix or not identifier:
        return None

    normalized_prefix = id_prefix.casefold()
    if normalized_prefix.endswith("cfg"):
        acronym = id_prefix[:-3]
        kind = "Cfg"
    elif normalized_prefix.endswith("mission"):
        acronym = id_prefix[:-7]
        kind = "M"
    else:
        return None

    acronym = acronym.strip().upper()
    if not acronym:
        return None
    return f"{acronym} {kind}({identifier})"


def canonical_configuration_label(configuration_label: str, external_id: str | None) -> str:
    short_label = configuration_short_label(external_id)
    if short_label is None:
        return configuration_label

    description = _label_description(configuration_label, external_id)
    return f"{short_label}: {description}" if description else short_label


def configuration_tab_label(
    current_label: str,
    configuration_external_id: str | None,
    configuration_label: str = "",
) -> str:
    """Combine a managed backend prefix with a user-editable collection-tab alias."""
    alias = _CONFIGURATION_TAB_PREFIX_PATTERN.sub("", current_label.strip(), count=1).strip()
    short_label = configuration_short_label(configuration_external_id)
    if short_label is None:
        return alias

    if alias:
        return f"{short_label}: {alias}"

    canonical_label = canonical_configuration_label(configuration_label, configuration_external_id)
    if canonical_label.startswith(f"{short_label}: "):
        backend_label = canonical_label.removeprefix(f"{short_label}: ").strip()
        if backend_label:
            return f"{short_label}: {backend_label}"
    return short_label


def canonical_device_label(device_label: str, external_id: str | None) -> str:
    membership = _match_device_membership(device_label)
    short_label = _device_short_label(external_id)

    if short_label is None:
        if membership is None:
            return device_label
        short_label = membership.group("identity")

    relationship_prefix = ""
    if membership is not None:
        relationship_kind = "Cfg" if membership.group("relationship") in {"Config", "Cfg"} else "M"
        relationship_acronym = _device_backend_acronym(external_id) or membership.groupdict().get("relationship_acronym")
        relationship_label = f"{relationship_kind}({membership.group('relationship_id')})"
        if relationship_acronym:
            relationship_label = f"{relationship_acronym} {relationship_label}"
        relationship_prefix = f"{relationship_label} "

    description = (
        membership.group("description").strip() if membership is not None else _label_description(device_label, external_id)
    )
    label = f"{relationship_prefix}{short_label}"
    return f"{label}: {description}" if description else label


def device_detail_tab_label(
    configuration_label: str,
    device_label: str,
    device_external_id: str | None = None,
) -> str:
    """Combine a configuration label and device label for an RDMO collection tab."""
    configuration_label = configuration_label.strip()
    device_label = _without_embedded_configuration(canonical_device_label(device_label.strip(), device_external_id))

    if configuration_label and device_label:
        return f"{configuration_label} {device_label}"
    return configuration_label or device_label


def _device_short_label(external_id: str | None) -> str | None:
    if not external_id or ":" not in external_id:
        return None

    id_prefix, identifier = external_id.split(":", 1)
    normalized_prefix = id_prefix.casefold()
    if not identifier:
        return None
    if normalized_prefix == "o2aregistry":
        entity = "O2A Item"
    elif normalized_prefix == "gfzgipp":
        entity = "GFZ GIPP Instrument"
    elif normalized_prefix.endswith("sms"):
        acronym = id_prefix[:-3].strip().upper()
        entity = f"{acronym} Sensor" if acronym else "SMS Sensor"
    else:
        return None
    return f"{entity}({identifier})"


def _device_backend_acronym(external_id: str | None) -> str | None:
    if not external_id or ":" not in external_id:
        return None

    id_prefix = external_id.split(":", 1)[0].strip()
    normalized_prefix = id_prefix.casefold()
    if normalized_prefix == "o2aregistry":
        return "O2A"
    if normalized_prefix == "gfzgipp":
        return "GFZ"
    if normalized_prefix.endswith("sms"):
        return id_prefix[:-3].strip().upper() or "SMS"
    return None


def _label_description(label: str, external_id: str | None) -> str:
    label = label.strip()
    if label == external_id:
        return ""
    if ": " in label:
        return label.split(": ", 1)[1].strip()
    return label


def _without_embedded_configuration(device_label: str) -> str:
    match = _match_device_membership(device_label)
    if match is None:
        return device_label
    return f"{match.group('identity')}: {match.group('description')}"


def _match_device_membership(device_label: str) -> re.Match[str] | None:
    return _DEVICE_FIRST_MEMBERSHIP_PATTERN.match(device_label) or _CONFIGURATION_FIRST_MEMBERSHIP_PATTERN.match(device_label)
