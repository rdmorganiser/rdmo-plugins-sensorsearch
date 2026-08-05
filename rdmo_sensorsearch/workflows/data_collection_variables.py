from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction

from rdmo.projects.models import Value

from rdmo_sensorsearch.config import catalog_matches, load_config
from rdmo_sensorsearch.persistence.data_collection_variables import RDMODataCollectionVariableStore
from rdmo_sensorsearch.services.data_collection_variables import (
    ParameterUnitPair,
    plan_data_collection_variable_reconciliation,
)
from rdmo_sensorsearch.services.synchronization_context import mute_value_post_save
from rdmo_sensorsearch.workflows.device_details import DEVICE_COLLECTION_ATTRIBUTE_URI

logger = logging.getLogger(__name__)

DATA_COLLECTION_DEVICES_ATTRIBUTE_URI = "https://rdmorganiser.github.io/terms/domain/project/dataset/collaboration_tools"
DEVICE_PARAMETER_NAME_ATTRIBUTE_URI = "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/preservation/parameter/name"
DEVICE_PARAMETER_UNIT_ATTRIBUTE_URI = "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/preservation/parameter/unit"
DATA_COLLECTION_VARIABLE_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/project/dataset/metadata/dc-variable"
DATA_COLLECTION_UNIT_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/project/dataset/metadata/dc-unit"


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
            devices_attribute_uri=catalog_config.get("devices_attribute_uri", DATA_COLLECTION_DEVICES_ATTRIBUTE_URI),
            device_collection_attribute_uri=catalog_config.get(
                "device_collection_attribute_uri", DEVICE_COLLECTION_ATTRIBUTE_URI
            ),
            parameter_name_attribute_uri=catalog_config.get("parameter_name_attribute_uri", DEVICE_PARAMETER_NAME_ATTRIBUTE_URI),
            parameter_unit_attribute_uri=catalog_config.get("parameter_unit_attribute_uri", DEVICE_PARAMETER_UNIT_ATTRIBUTE_URI),
            variable_attribute_uri=catalog_config.get("variable_attribute_uri", DATA_COLLECTION_VARIABLE_ATTRIBUTE_URI),
            unit_attribute_uri=catalog_config.get("unit_attribute_uri", DATA_COLLECTION_UNIT_ATTRIBUTE_URI),
        )
    return None


def reconcile_data_collection_variables_for_selected_device(
    instance: Value,
    settings: DataCollectionVariableSyncSettings,
) -> None:
    _reconcile_data_collection_variables(instance, settings, add_instance_device=True)


def remove_stale_generated_data_collection_variables(
    instance: Value,
    settings: DataCollectionVariableSyncSettings,
) -> None:
    _reconcile_data_collection_variables(instance, settings, add_instance_device=False)


def _reconcile_data_collection_variables(
    instance: Value,
    settings: DataCollectionVariableSyncSettings,
    *,
    add_instance_device: bool,
) -> None:
    if instance.attribute.uri != settings.devices_attribute_uri:
        return

    store = RDMODataCollectionVariableStore.resolve(
        instance,
        device_collection_attribute_uri=settings.device_collection_attribute_uri,
        parameter_name_attribute_uri=settings.parameter_name_attribute_uri,
        parameter_unit_attribute_uri=settings.parameter_unit_attribute_uri,
        variable_attribute_uri=settings.variable_attribute_uri,
        unit_attribute_uri=settings.unit_attribute_uri,
    )
    if store is None:
        logger.warning("Skipping data collection variable synchronization because one or more attributes are missing")
        return

    parameters_to_add: tuple[ParameterUnitPair, ...] = ()
    if add_instance_device and instance.external_id:
        parameters_to_add = store.parameters_for_device(instance.external_id)
        if not parameters_to_add:
            logger.debug("No parameters found for selected data collection device %s", instance.external_id)
    elif add_instance_device:
        logger.debug("Skipping parameter creation without device external_id for value %s", instance.pk)

    desired_parameters = tuple(
        parameter
        for device_external_id in store.selected_device_external_ids(settings.devices_attribute_uri)
        for parameter in store.parameters_for_device(device_external_id)
    )
    plan = plan_data_collection_variable_reconciliation(
        parameters_to_add=parameters_to_add,
        desired_parameters=desired_parameters,
        existing_variables=store.existing_variables(),
    )
    if not plan.has_changes:
        return

    with transaction.atomic(), mute_value_post_save():
        store.apply(plan)
