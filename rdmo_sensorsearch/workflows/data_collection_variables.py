from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction

from rdmo.projects.models import Value

from rdmo_sensorsearch.config import load_config_model
from rdmo_sensorsearch.persistence.data_collection_variables import RDMODataCollectionVariableStore
from rdmo_sensorsearch.services.data_collection_variables import (
    ParameterUnitPair,
    plan_data_collection_variable_reconciliation,
)
from rdmo_sensorsearch.services.synchronization_context import mute_value_sync

logger = logging.getLogger(__name__)

DATA_COLLECTION_DEVICES_ATTRIBUTE_URI = "https://rdmorganiser.github.io/terms/domain/project/dataset/collaboration_tools"
DEVICE_COLLECTION_ATTRIBUTE_URI = "https://rdmo-sandbox.gfz-potsdam.de/terms/domain/moses/instruments/id"
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
    for catalog in load_config_model().data_collection_variable_sync.catalogs:
        if catalog.scope.matches(catalog_uri):
            settings = catalog.settings
            return DataCollectionVariableSyncSettings(
                devices_attribute_uri=settings.devices_attribute_uri,
                device_collection_attribute_uri=settings.device_collection_attribute_uri,
                parameter_name_attribute_uri=settings.parameter_name_attribute_uri,
                parameter_unit_attribute_uri=settings.parameter_unit_attribute_uri,
                variable_attribute_uri=settings.variable_attribute_uri,
                unit_attribute_uri=settings.unit_attribute_uri,
            )
    return None


def reconcile_data_collection_variables_for_selected_device(
    instance: Value,
    settings: DataCollectionVariableSyncSettings,
) -> None:
    _reconcile_data_collection_variables(
        project=instance.project,
        attribute_uri=instance.attribute.uri,
        set_prefix=instance.set_prefix or "",
        set_index=instance.set_index,
        external_id=instance.external_id or "",
        value_id=instance.pk,
        settings=settings,
        add_instance_device=True,
    )


def remove_stale_generated_data_collection_variables(
    instance: Value,
    settings: DataCollectionVariableSyncSettings,
) -> None:
    remove_stale_generated_data_collection_variables_for_deleted_device(
        project=instance.project,
        attribute_uri=instance.attribute.uri,
        set_prefix=instance.set_prefix or "",
        set_index=instance.set_index,
        external_id=instance.external_id or "",
        settings=settings,
    )


def remove_stale_generated_data_collection_variables_for_deleted_device(
    *,
    project,
    attribute_uri: str,
    set_prefix: str,
    set_index: int,
    external_id: str,
    settings: DataCollectionVariableSyncSettings,
) -> None:
    _reconcile_data_collection_variables(
        project=project,
        attribute_uri=attribute_uri,
        set_prefix=set_prefix,
        set_index=set_index,
        external_id=external_id,
        value_id=None,
        settings=settings,
        add_instance_device=False,
    )


def _reconcile_data_collection_variables(
    *,
    project,
    attribute_uri: str,
    set_prefix: str,
    set_index: int,
    external_id: str,
    value_id: int | None,
    settings: DataCollectionVariableSyncSettings,
    add_instance_device: bool,
) -> None:
    if attribute_uri != settings.devices_attribute_uri:
        return

    store = RDMODataCollectionVariableStore.resolve(
        project=project,
        set_prefix=set_prefix,
        set_index=set_index,
        device_collection_attribute_uri=settings.device_collection_attribute_uri,
        parameter_name_attribute_uri=settings.parameter_name_attribute_uri,
        parameter_unit_attribute_uri=settings.parameter_unit_attribute_uri,
        variable_attribute_uri=settings.variable_attribute_uri,
        unit_attribute_uri=settings.unit_attribute_uri,
    )
    if store is None:
        logger.warning("Skipping data collection variable synchronization because one or more attributes are missing")
        return

    selected_ids = store.selected_device_external_ids(settings.devices_attribute_uri)
    requested_ids = set(selected_ids)
    if add_instance_device and external_id:
        requested_ids.add(external_id)
    parameters_by_device = store.parameters_by_device(requested_ids)
    parameters_to_add: tuple[ParameterUnitPair, ...] = ()
    if add_instance_device and external_id:
        parameters_to_add = parameters_by_device[external_id]
        if not parameters_to_add:
            logger.debug("No parameters found for selected data collection device %s", external_id)
    elif add_instance_device:
        logger.debug("Skipping parameter creation without device external_id for value %s", value_id)

    desired_parameters = tuple(
        parameter for device_external_id in selected_ids for parameter in parameters_by_device[device_external_id]
    )
    plan = plan_data_collection_variable_reconciliation(
        parameters_to_add=parameters_to_add,
        desired_parameters=desired_parameters,
        existing_variables=store.existing_variables(),
    )
    if not plan.has_changes:
        return

    with transaction.atomic(), mute_value_sync():
        store.apply(plan)
