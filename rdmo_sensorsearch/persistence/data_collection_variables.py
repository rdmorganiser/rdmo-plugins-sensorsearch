from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from functools import reduce
from operator import or_

from django.db.models import Q

from rdmo.domain.models import Attribute
from rdmo.projects.models import Value

from rdmo_sensorsearch.persistence.value_reconciliation import format_change_label, upsert_value_if_changed
from rdmo_sensorsearch.services.data_collection_variables import (
    DataCollectionVariablePlan,
    ExistingDataCollectionVariable,
    ParameterUnitPair,
    is_auto_variable_marker,
)
from rdmo_sensorsearch.services.performance import measure_phase

logger = logging.getLogger(__name__)

# Bound SQL expression/parameter counts on all supported database backends.
DEVICE_LOOKUP_BATCH_SIZE = 100


@dataclass(frozen=True)
class DataCollectionVariableAttributes:
    device_collection: Attribute
    parameter_name: Attribute
    parameter_unit: Attribute
    variable: Attribute
    unit: Attribute


class RDMODataCollectionVariableStore:
    def __init__(
        self,
        project,
        set_prefix: str,
        set_index: int,
        attributes: DataCollectionVariableAttributes,
    ):
        self.project = project
        self.set_prefix = set_prefix or ""
        self.set_index = set_index
        self.attributes = attributes
        self.target_prefix = str(set_index)

    @classmethod
    def resolve(
        cls,
        *,
        project,
        set_prefix: str,
        set_index: int,
        device_collection_attribute_uri: str,
        parameter_name_attribute_uri: str,
        parameter_unit_attribute_uri: str,
        variable_attribute_uri: str,
        unit_attribute_uri: str,
    ) -> RDMODataCollectionVariableStore | None:
        attribute_uris = (
            device_collection_attribute_uri,
            parameter_name_attribute_uri,
            parameter_unit_attribute_uri,
            variable_attribute_uri,
            unit_attribute_uri,
        )
        attributes = {attribute.uri: attribute for attribute in Attribute.objects.filter(uri__in=attribute_uris)}
        if len(attributes) < len(set(attribute_uris)):
            return None
        return cls(
            project,
            set_prefix,
            set_index,
            DataCollectionVariableAttributes(
                device_collection=attributes[device_collection_attribute_uri],
                parameter_name=attributes[parameter_name_attribute_uri],
                parameter_unit=attributes[parameter_unit_attribute_uri],
                variable=attributes[variable_attribute_uri],
                unit=attributes[unit_attribute_uri],
            ),
        )

    def parameters_for_device(self, device_external_id: str) -> tuple[ParameterUnitPair, ...]:
        return self.parameters_by_device((device_external_id,))[device_external_id]

    @measure_phase("variables.load_parameters")
    def parameters_by_device(self, external_ids: Iterable[str]) -> dict[str, tuple[ParameterUnitPair, ...]]:
        requested = tuple(dict.fromkeys(external_ids))
        if not requested:
            return {}
        blocks_by_device = defaultdict(list)
        prefixes = set()
        for offset in range(0, len(requested), DEVICE_LOOKUP_BATCH_SIZE):
            batch = requested[offset : offset + DEVICE_LOOKUP_BATCH_SIZE]
            # Let the database evaluate each match: Python suffix matching
            # would change LIKE/collation semantics (notably on SQLite).
            matches = {
                f"device_match_{i}": Q(external_id=device_id) | Q(external_id__endswith=f"||{device_id}")
                for i, device_id in enumerate(batch)
            }
            device_blocks = (
                Value.objects.filter(
                    project=self.project,
                    snapshot=None,
                    attribute=self.attributes.device_collection,
                    set_collection=True,
                )
                .filter(reduce(or_, matches.values()))
                .annotate(**matches)
                .order_by(
                    "set_prefix",
                    "set_index",
                    "id",
                )
                .values_list("set_index", *matches)
            )
            for index, *matched in device_blocks:
                for device_id, is_match in zip(batch, matched, strict=True):
                    if is_match:
                        blocks_by_device[device_id].append(str(index))
                        prefixes.add(str(index))

        values_by_scope = defaultdict(dict)
        ordered_prefixes = sorted(prefixes)
        for offset in range(0, len(ordered_prefixes), 500):
            values = (
                Value.objects.filter(
                    project=self.project,
                    snapshot=None,
                    set_collection=True,
                    set_prefix__in=ordered_prefixes[offset : offset + 500],
                    attribute__in=(self.attributes.parameter_name, self.attributes.parameter_unit),
                )
                .exclude(text__isnull=True)
                .order_by("set_index", "id")
                .values_list(
                    "attribute_id",
                    "set_prefix",
                    "set_index",
                    "text",
                )
            )
            for attribute_id, prefix, index, text in values:
                values_by_scope[(attribute_id, prefix)][index] = text

        parameters_by_prefix = {}
        for source_prefix in prefixes:
            names_by_index = values_by_scope[(self.attributes.parameter_name.id, source_prefix)]
            units_by_index = values_by_scope[(self.attributes.parameter_unit.id, source_prefix)]
            parameters = []
            for set_index in sorted(set(names_by_index) | set(units_by_index)):
                name = names_by_index.get(set_index, "")
                unit = units_by_index.get(set_index, "")
                if name or unit:
                    parameters.append(ParameterUnitPair(name=name, unit=unit))
            parameters_by_prefix[source_prefix] = tuple(parameters)
        return {
            device_id: tuple(parameter for prefix in blocks_by_device[device_id] for parameter in parameters_by_prefix[prefix])
            for device_id in requested
        }

    def selected_device_external_ids(self, devices_attribute_uri: str) -> tuple[str, ...]:
        values = (
            Value.objects.filter(
                project=self.project,
                snapshot=None,
                attribute__uri=devices_attribute_uri,
                set_collection=True,
                set_prefix=self.set_prefix,
                set_index=self.set_index,
            )
            .exclude(external_id__isnull=True)
            .exclude(external_id__exact="")
            .order_by("collection_index", "id")
        )
        external_ids = []
        seen = set()
        for value in values:
            if value.external_id in seen:
                continue
            seen.add(value.external_id)
            external_ids.append(value.external_id)
        return tuple(external_ids)

    def existing_variables(self) -> tuple[ExistingDataCollectionVariable, ...]:
        names_by_index, units_by_index, markers_by_index = {}, {}, {}
        values = (
            Value.objects.filter(
                project=self.project,
                snapshot=None,
                set_collection=True,
                set_prefix=self.target_prefix,
                attribute__in=(self.attributes.variable, self.attributes.unit),
            )
            .order_by("set_index", "id")
            .values_list("attribute_id", "set_index", "text", "external_id")
        )
        for attribute_id, index, text, external_id in values:
            if text is not None:
                if attribute_id == self.attributes.variable.id:
                    names_by_index[index] = text
                if attribute_id == self.attributes.unit.id:
                    units_by_index[index] = text
            if external_id and is_auto_variable_marker(external_id):
                markers_by_index[index] = external_id
        return tuple(
            ExistingDataCollectionVariable(
                set_index=set_index,
                name=names_by_index.get(set_index, ""),
                unit=units_by_index.get(set_index, ""),
                external_id=markers_by_index.get(set_index),
            )
            for set_index in sorted(set(names_by_index) | set(units_by_index) | set(markers_by_index))
        )

    def apply(self, plan: DataCollectionVariablePlan) -> None:
        for planned in plan.create:
            self._upsert(self.attributes.variable, planned.set_index, planned.parameter.name, planned.external_id)
            self._upsert(self.attributes.unit, planned.set_index, planned.parameter.unit, planned.external_id)

        if plan.delete_set_indexes:
            deleted, _ = Value.objects.filter(
                project=self.project,
                snapshot=None,
                attribute__in=[self.attributes.variable, self.attributes.unit],
                set_collection=True,
                set_prefix=self.target_prefix,
                set_index__in=plan.delete_set_indexes,
            ).delete()
            logger.info(
                "Deleted stale generated data collection variable rows at set_prefix=%s set_indexes=%s (%s rows)",
                self.target_prefix,
                list(plan.delete_set_indexes),
                deleted,
            )

    def _values_by_set_index(self, attribute: Attribute, set_prefix: str) -> dict[int, str]:
        values = (
            Value.objects.filter(
                project=self.project,
                snapshot=None,
                attribute=attribute,
                set_collection=True,
                set_prefix=set_prefix,
            )
            .exclude(text__isnull=True)
            .order_by("set_index", "id")
        )
        return {value.set_index: value.text or "" for value in values if value.text or value.text == ""}

    def _external_ids_by_set_index(self) -> dict[int, str]:
        values = (
            Value.objects.filter(
                project=self.project,
                snapshot=None,
                attribute__in=[self.attributes.variable, self.attributes.unit],
                set_collection=True,
                set_prefix=self.target_prefix,
            )
            .exclude(external_id__isnull=True)
            .exclude(external_id__exact="")
            .order_by("set_index", "id")
        )
        markers = {}
        for value in values:
            if is_auto_variable_marker(value.external_id):
                markers[value.set_index] = value.external_id
        return markers

    def _upsert(self, attribute: Attribute, set_index: int, text: str, external_id: str) -> None:
        _, created, changed = upsert_value_if_changed(
            {
                "project": self.project,
                "attribute": attribute,
                "snapshot": None,
                "set_collection": True,
                "set_prefix": self.target_prefix,
                "set_index": set_index,
            },
            {"text": text, "external_id": external_id},
        )
        logger.info(
            "%s data collection variable value for attribute %s at set_prefix=%s set_index=%s: %r",
            format_change_label(created, changed),
            attribute.uri,
            self.target_prefix,
            set_index,
            text,
        )
