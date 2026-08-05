from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1

AUTO_VARIABLE_EXTERNAL_ID_PREFIX = "sensorsearch:dc-variable:"


@dataclass(frozen=True)
class ParameterUnitPair:
    name: str
    unit: str


@dataclass(frozen=True)
class ExistingDataCollectionVariable:
    set_index: int
    name: str
    unit: str
    external_id: str | None = None


@dataclass(frozen=True)
class PlannedDataCollectionVariable:
    set_index: int
    parameter: ParameterUnitPair
    external_id: str


@dataclass(frozen=True)
class DataCollectionVariablePlan:
    create: tuple[PlannedDataCollectionVariable, ...]
    delete_set_indexes: tuple[int, ...]

    @property
    def has_changes(self) -> bool:
        return bool(self.create or self.delete_set_indexes)


def plan_data_collection_variable_reconciliation(
    *,
    parameters_to_add: tuple[ParameterUnitPair, ...],
    desired_parameters: tuple[ParameterUnitPair, ...],
    existing_variables: tuple[ExistingDataCollectionVariable, ...],
) -> DataCollectionVariablePlan:
    """Plan generated variable creation and stale-row deletion without I/O."""

    existing_pairs = {_normalized_pair(entry.name, entry.unit) for entry in existing_variables}
    next_set_index = max((entry.set_index for entry in existing_variables), default=-1) + 1
    create = []
    for parameter in parameters_to_add:
        normalized_pair = _normalized_pair(parameter.name, parameter.unit)
        if normalized_pair in existing_pairs:
            continue
        create.append(
            PlannedDataCollectionVariable(
                set_index=next_set_index,
                parameter=parameter,
                external_id=variable_unit_marker(parameter),
            )
        )
        existing_pairs.add(normalized_pair)
        next_set_index += 1

    desired_markers = {variable_unit_marker(parameter) for parameter in desired_parameters}
    delete_set_indexes = tuple(
        sorted(
            entry.set_index
            for entry in existing_variables
            if is_auto_variable_marker(entry.external_id) and entry.external_id not in desired_markers
        )
    )
    return DataCollectionVariablePlan(
        create=tuple(create),
        delete_set_indexes=delete_set_indexes,
    )


def variable_unit_marker(parameter: ParameterUnitPair) -> str:
    normalized = f"{_normalize(parameter.name)}\0{_normalize(parameter.unit)}"
    digest = sha1(normalized.encode("utf-8")).hexdigest()
    return f"{AUTO_VARIABLE_EXTERNAL_ID_PREFIX}{digest}"


def is_auto_variable_marker(external_id: str | None) -> bool:
    return isinstance(external_id, str) and external_id.startswith(AUTO_VARIABLE_EXTERNAL_ID_PREFIX)


def _normalized_pair(name: str, unit: str) -> tuple[str, str]:
    return _normalize(name), _normalize(unit)


def _normalize(value: str) -> str:
    return value.strip().casefold()
