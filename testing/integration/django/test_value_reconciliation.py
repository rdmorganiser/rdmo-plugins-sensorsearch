"""Reconciliation helpers use real framework imports without accessing the database."""

from copy import deepcopy

import pytest

from rdmo_sensorsearch.persistence.value_reconciliation import deduplicate_collection_values


def test_collection_values_are_deduplicated_by_external_id_in_input_order():
    first = {"external_id": "ufzsms:483", "text": "First label"}
    second = {"external_id": "kitsms:483", "text": "Second label"}
    spaced_id = {"external_id": " ufzsms:483 ", "text": "Distinct unnormalized ID"}
    duplicate = {"external_id": "ufzsms:483", "text": "Duplicate label"}
    second_duplicate = {"external_id": "kitsms:483", "text": "Second duplicate label"}
    manual = {"external_id": "", "text": "Manual value"}
    source = (first, manual, second, duplicate, spaced_id, second_duplicate)
    before = deepcopy(source)

    result = deduplicate_collection_values(source)

    expected = (first, manual, second, spaced_id)
    assert result == expected
    assert all(actual is original for actual, original in zip(result, expected, strict=True))
    assert source == before


@pytest.mark.parametrize(
    "id_fields", [{}, {"external_id": ""}, {"external_id": None}, {"external_id": 0}, {"external_id": False}]
)
def test_collection_values_without_truthy_external_ids_are_all_preserved(id_fields):
    manual = {**id_fields, "text": "Manual value"}
    source = (manual, dict(manual), manual)
    before = deepcopy(source)

    result = deduplicate_collection_values(source)

    assert result == source
    assert all(actual is original for actual, original in zip(result, source, strict=True))
    assert source == before


def test_deduplicating_empty_collection_returns_an_empty_tuple():
    assert deduplicate_collection_values(()) == ()
