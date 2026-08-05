import logging
from dataclasses import dataclass
from hashlib import sha1

from django.db import transaction
from django.db.models import Q

from rdmo.domain.models import Attribute
from rdmo.projects.models import Value

from rdmo_sensorsearch.config import catalog_matches, load_config
from rdmo_sensorsearch.persistence.value_reconciliation import format_change_label, upsert_value_if_changed
from rdmo_sensorsearch.services.synchronization_context import mute_value_post_save
from rdmo_sensorsearch.workflows.device_details import DEVICE_COLLECTION_ATTRIBUTE_URI

logger = logging.getLogger(__name__)


DATA_COLLECTION_DEVICES_ATTRIBUTE_URI = "https://rdmorganiser.github.io/terms/domain/project/dataset/collaboration_tools"
DEVICE_PARAMETER_NAME_ATTRIBUTE_URI = "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/preservation/parameter/name"
DEVICE_PARAMETER_UNIT_ATTRIBUTE_URI = "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/preservation/parameter/unit"
DATA_COLLECTION_VARIABLE_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/project/dataset/metadata/dc-variable"
DATA_COLLECTION_UNIT_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/project/dataset/metadata/dc-unit"
AUTO_VARIABLE_EXTERNAL_ID_PREFIX = "sensorsearch:dc-variable:"


@dataclass(frozen=True)
class ParameterUnitPair:
    name: str
    unit: str


@dataclass(frozen=True)
class DataCollectionVariableSyncSettings:
    devices_attribute_uri: str
    device_collection_attribute_uri: str
    parameter_name_attribute_uri: str
    parameter_unit_attribute_uri: str
    variable_attribute_uri: str
    unit_attribute_uri: str


def get_data_collection_variable_sync_settings(catalog_uri: str) -> DataCollectionVariableSyncSettings | None:
    for catalog_config in load_config().get("DataCollectionVariableSync", {}).get("catalogs", []):
        if not catalog_matches(catalog_config, catalog_uri):
            continue
        return DataCollectionVariableSyncSettings(
            devices_attribute_uri=catalog_config.get(
                "devices_attribute_uri",
                DATA_COLLECTION_DEVICES_ATTRIBUTE_URI,
            ),
            device_collection_attribute_uri=catalog_config.get(
                "device_collection_attribute_uri",
                DEVICE_COLLECTION_ATTRIBUTE_URI,
            ),
            parameter_name_attribute_uri=catalog_config.get(
                "parameter_name_attribute_uri",
                DEVICE_PARAMETER_NAME_ATTRIBUTE_URI,
            ),
            parameter_unit_attribute_uri=catalog_config.get(
                "parameter_unit_attribute_uri",
                DEVICE_PARAMETER_UNIT_ATTRIBUTE_URI,
            ),
            variable_attribute_uri=catalog_config.get(
                "variable_attribute_uri",
                DATA_COLLECTION_VARIABLE_ATTRIBUTE_URI,
            ),
            unit_attribute_uri=catalog_config.get(
                "unit_attribute_uri",
                DATA_COLLECTION_UNIT_ATTRIBUTE_URI,
            ),
        )
    return None


def reconcile_data_collection_variables_for_selected_device(
    instance: Value,
    settings: DataCollectionVariableSyncSettings,
) -> None:
    if instance.attribute.uri != settings.devices_attribute_uri:
        return

    device_external_id = instance.external_id
    if not device_external_id:
        logger.debug("Skipping data collection variable sync without device external_id for value %s", instance.pk)
        remove_stale_generated_data_collection_variables(instance, settings)
        return

    attribute_by_uri = _attribute_by_uri(
        [
            settings.device_collection_attribute_uri,
            settings.parameter_name_attribute_uri,
            settings.parameter_unit_attribute_uri,
            settings.variable_attribute_uri,
            settings.unit_attribute_uri,
        ]
    )
    if len(attribute_by_uri) < 5:
        logger.warning("Skipping data collection variable sync because one or more attributes are missing")
        return

    parameters = _parameters_for_device(
        instance,
        device_external_id,
        device_collection_attribute=attribute_by_uri[settings.device_collection_attribute_uri],
        parameter_name_attribute=attribute_by_uri[settings.parameter_name_attribute_uri],
        parameter_unit_attribute=attribute_by_uri[settings.parameter_unit_attribute_uri],
    )
    if not parameters:
        logger.debug("No parameters found for selected data collection device %s", device_external_id)
        remove_stale_generated_data_collection_variables(instance, settings)
        return

    _append_missing_data_collection_parameters(
        instance,
        parameters,
        variable_attribute=attribute_by_uri[settings.variable_attribute_uri],
        unit_attribute=attribute_by_uri[settings.unit_attribute_uri],
    )
    remove_stale_generated_data_collection_variables(instance, settings)


def remove_stale_generated_data_collection_variables(
    instance: Value,
    settings: DataCollectionVariableSyncSettings,
) -> None:
    if instance.attribute.uri != settings.devices_attribute_uri:
        return

    attribute_by_uri = _attribute_by_uri(
        [
            settings.device_collection_attribute_uri,
            settings.parameter_name_attribute_uri,
            settings.parameter_unit_attribute_uri,
            settings.variable_attribute_uri,
            settings.unit_attribute_uri,
        ]
    )
    if len(attribute_by_uri) < 5:
        logger.warning("Skipping stale data collection variable cleanup because one or more attributes are missing")
        return

    desired_markers = _desired_data_collection_variable_markers(
        instance,
        settings=settings,
        device_collection_attribute=attribute_by_uri[settings.device_collection_attribute_uri],
        parameter_name_attribute=attribute_by_uri[settings.parameter_name_attribute_uri],
        parameter_unit_attribute=attribute_by_uri[settings.parameter_unit_attribute_uri],
    )
    _delete_stale_auto_data_collection_parameters(
        instance,
        desired_markers,
        variable_attribute=attribute_by_uri[settings.variable_attribute_uri],
        unit_attribute=attribute_by_uri[settings.unit_attribute_uri],
    )


def _attribute_by_uri(attribute_uris: list[str]) -> dict[str, Attribute]:
    attributes = Attribute.objects.filter(uri__in=attribute_uris)
    return {attribute.uri: attribute for attribute in attributes}


def _parameters_for_device(
    instance: Value,
    device_external_id: str,
    device_collection_attribute: Attribute,
    parameter_name_attribute: Attribute,
    parameter_unit_attribute: Attribute,
) -> list[ParameterUnitPair]:
    device_blocks = list(
        Value.objects.filter(
            project=instance.project,
            snapshot=None,
            attribute=device_collection_attribute,
            set_collection=True,
        )
        .filter(Q(external_id=device_external_id) | Q(external_id__endswith=f"||{device_external_id}"))
        .order_by("set_prefix", "set_index", "id")
    )
    if not device_blocks:
        logger.debug("No materialized device detail block found for %s", device_external_id)
        return []

    parameters: list[ParameterUnitPair] = []
    for block in device_blocks:
        source_prefix = str(block.set_index)
        names_by_index = _values_by_set_index(instance, parameter_name_attribute, source_prefix)
        units_by_index = _values_by_set_index(instance, parameter_unit_attribute, source_prefix)

        for set_index in sorted(set(names_by_index) | set(units_by_index)):
            name = names_by_index.get(set_index, "")
            unit = units_by_index.get(set_index, "")
            if not name and not unit:
                continue
            parameters.append(ParameterUnitPair(name=name, unit=unit))

    return parameters


def _values_by_set_index(instance: Value, attribute: Attribute, set_prefix: str) -> dict[int, str]:
    values = (
        Value.objects.filter(
            project=instance.project,
            snapshot=None,
            attribute=attribute,
            set_collection=True,
            set_prefix=set_prefix,
        )
        .exclude(text__isnull=True)
        .order_by("set_index", "id")
    )
    return {value.set_index: value.text or "" for value in values if value.text or value.text == ""}


def _append_missing_data_collection_parameters(
    instance: Value,
    parameters: list[ParameterUnitPair],
    variable_attribute: Attribute,
    unit_attribute: Attribute,
) -> None:
    target_prefix = str(instance.set_index)
    existing_pairs = _existing_data_collection_pairs(instance, variable_attribute, unit_attribute, target_prefix)
    next_index = _next_data_collection_variable_index(instance, variable_attribute, unit_attribute, target_prefix)

    with transaction.atomic(), mute_value_post_save():
        for parameter in parameters:
            pair = (_normalize(parameter.name), _normalize(parameter.unit))
            if pair in existing_pairs:
                continue

            _upsert_data_collection_parameter(
                instance,
                variable_attribute,
                target_prefix,
                next_index,
                parameter.name,
                external_id=_variable_unit_marker(parameter),
            )
            _upsert_data_collection_parameter(
                instance,
                unit_attribute,
                target_prefix,
                next_index,
                parameter.unit,
                external_id=_variable_unit_marker(parameter),
            )
            existing_pairs.add(pair)
            next_index += 1


def _existing_data_collection_pairs(
    instance: Value,
    variable_attribute: Attribute,
    unit_attribute: Attribute,
    target_prefix: str,
) -> set[tuple[str, str]]:
    names_by_index = _values_by_set_index(instance, variable_attribute, target_prefix)
    units_by_index = _values_by_set_index(instance, unit_attribute, target_prefix)
    return {
        (_normalize(names_by_index.get(set_index, "")), _normalize(units_by_index.get(set_index, "")))
        for set_index in set(names_by_index) | set(units_by_index)
    }


def _next_data_collection_variable_index(
    instance: Value,
    variable_attribute: Attribute,
    unit_attribute: Attribute,
    target_prefix: str,
) -> int:
    indexes = list(
        Value.objects.filter(
            project=instance.project,
            snapshot=None,
            attribute__in=[variable_attribute, unit_attribute],
            set_collection=True,
            set_prefix=target_prefix,
        ).values_list("set_index", flat=True)
    )
    if not indexes:
        return 0
    return max(indexes) + 1


def _upsert_data_collection_parameter(
    instance: Value,
    attribute: Attribute,
    target_prefix: str,
    set_index: int,
    text: str,
    external_id: str,
) -> None:
    _, created, changed = upsert_value_if_changed(
        {
            "project": instance.project,
            "attribute": attribute,
            "snapshot": None,
            "set_collection": True,
            "set_prefix": target_prefix,
            "set_index": set_index,
        },
        {
            "text": text,
            "external_id": external_id,
        },
    )
    logger.info(
        "%s data collection variable value for attribute %s at set_prefix=%s set_index=%s: %r",
        format_change_label(created, changed),
        attribute.uri,
        target_prefix,
        set_index,
        text,
    )


def _normalize(value: str) -> str:
    return value.strip().casefold()


def _desired_data_collection_variable_markers(
    instance: Value,
    settings: DataCollectionVariableSyncSettings,
    device_collection_attribute: Attribute,
    parameter_name_attribute: Attribute,
    parameter_unit_attribute: Attribute,
) -> set[str]:
    markers: set[str] = set()
    for device_external_id in _selected_data_collection_device_external_ids(instance, settings.devices_attribute_uri):
        for parameter in _parameters_for_device(
            instance,
            device_external_id,
            device_collection_attribute,
            parameter_name_attribute,
            parameter_unit_attribute,
        ):
            markers.add(_variable_unit_marker(parameter))
    return markers


def _selected_data_collection_device_external_ids(
    instance: Value,
    devices_attribute_uri: str,
) -> list[str]:
    values = (
        Value.objects.filter(
            project=instance.project,
            snapshot=None,
            attribute__uri=devices_attribute_uri,
            set_collection=True,
            set_prefix=instance.set_prefix or "",
            set_index=instance.set_index,
        )
        .exclude(external_id__isnull=True)
        .exclude(external_id__exact="")
        .order_by("collection_index", "id")
    )

    device_external_ids: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value.external_id in seen:
            continue
        seen.add(value.external_id)
        device_external_ids.append(value.external_id)
    return device_external_ids


def _delete_stale_auto_data_collection_parameters(
    instance: Value,
    desired_markers: set[str],
    variable_attribute: Attribute,
    unit_attribute: Attribute,
) -> None:
    target_prefix = str(instance.set_index)
    variable_values = _values_by_set_index(instance, variable_attribute, target_prefix)
    unit_values = _values_by_set_index(instance, unit_attribute, target_prefix)
    marker_values = _external_ids_by_set_index(instance, [variable_attribute, unit_attribute], target_prefix)

    stale_indexes = []
    for set_index in sorted(set(variable_values) | set(unit_values) | set(marker_values)):
        marker = marker_values.get(set_index)
        if not _is_auto_variable_marker(marker):
            continue
        if marker in desired_markers:
            continue
        stale_indexes.append(set_index)

    if not stale_indexes:
        return

    with transaction.atomic(), mute_value_post_save():
        deleted, _ = Value.objects.filter(
            project=instance.project,
            snapshot=None,
            attribute__in=[variable_attribute, unit_attribute],
            set_collection=True,
            set_prefix=target_prefix,
            set_index__in=stale_indexes,
        ).delete()
        logger.info(
            "Deleted stale generated data collection variable rows at set_prefix=%s set_indexes=%s (%s rows)",
            target_prefix,
            stale_indexes,
            deleted,
        )


def _external_ids_by_set_index(instance: Value, attributes: list[Attribute], set_prefix: str) -> dict[int, str]:
    values = (
        Value.objects.filter(
            project=instance.project,
            snapshot=None,
            attribute__in=attributes,
            set_collection=True,
            set_prefix=set_prefix,
        )
        .exclude(external_id__isnull=True)
        .exclude(external_id__exact="")
        .order_by("set_index", "id")
    )

    markers: dict[int, str] = {}
    for value in values:
        if _is_auto_variable_marker(value.external_id):
            markers[value.set_index] = value.external_id
    return markers


def _variable_unit_marker(parameter: ParameterUnitPair) -> str:
    normalized = f"{_normalize(parameter.name)}\0{_normalize(parameter.unit)}"
    digest = sha1(normalized.encode("utf-8")).hexdigest()
    return f"{AUTO_VARIABLE_EXTERNAL_ID_PREFIX}{digest}"


def _is_auto_variable_marker(external_id: str | None) -> bool:
    return isinstance(external_id, str) and external_id.startswith(AUTO_VARIABLE_EXTERNAL_ID_PREFIX)
