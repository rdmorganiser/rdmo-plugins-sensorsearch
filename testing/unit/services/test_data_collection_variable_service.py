from rdmo_sensorsearch.services.data_collection_variables import (
    DataCollectionVariablePlan,
    ExistingDataCollectionVariable,
    ParameterUnitPair,
    plan_data_collection_variable_reconciliation,
    variable_unit_marker,
)


def test_plan_adds_missing_pairs_after_highest_index_and_deletes_stale_generated_rows():
    manual = ExistingDataCollectionVariable(set_index=0, name="Pressure", unit="hPa")
    stale_parameter = ParameterUnitPair(name="Wind", unit="m/s")
    stale = ExistingDataCollectionVariable(
        set_index=2,
        name=stale_parameter.name,
        unit=stale_parameter.unit,
        external_id=variable_unit_marker(stale_parameter),
    )
    temperature = ParameterUnitPair(name="Temperature", unit="°C")

    plan = plan_data_collection_variable_reconciliation(
        parameters_to_add=(
            ParameterUnitPair(name=" pressure ", unit="HPA"),
            temperature,
            temperature,
        ),
        desired_parameters=(temperature,),
        existing_variables=(manual, stale),
    )

    assert len(plan.create) == 1
    assert plan.create[0].set_index == 3
    assert plan.create[0].parameter == temperature
    assert plan.create[0].external_id == variable_unit_marker(temperature)
    assert plan.delete_set_indexes == (2,)


def test_plan_retains_generated_rows_still_desired_by_any_selected_device():
    temperature = ParameterUnitPair(name="Temperature", unit="°C")
    existing = ExistingDataCollectionVariable(
        set_index=4,
        name=temperature.name,
        unit=temperature.unit,
        external_id=variable_unit_marker(temperature),
    )

    plan = plan_data_collection_variable_reconciliation(
        parameters_to_add=(),
        desired_parameters=(temperature,),
        existing_variables=(existing,),
    )

    assert plan == DataCollectionVariablePlan(create=(), delete_set_indexes=())
    assert plan.has_changes is False


def test_variable_marker_is_stable_across_whitespace_and_case():
    assert variable_unit_marker(ParameterUnitPair("Temperature", "°C")) == variable_unit_marker(
        ParameterUnitPair(" temperature ", "°c")
    )


def test_plan_never_deletes_manual_rows_that_are_not_desired():
    manual = ExistingDataCollectionVariable(
        set_index=1,
        name="Operator note",
        unit="",
        external_id=None,
    )

    plan = plan_data_collection_variable_reconciliation(
        parameters_to_add=(),
        desired_parameters=(),
        existing_variables=(manual,),
    )

    assert plan.delete_set_indexes == ()
