import pytest

from rdmo_sensorsearch.signals.refresh_types import (
    RefreshAction,
    RefreshError,
    RefreshKind,
    RefreshResult,
    combine_refresh_results,
    format_refresh_message,
)


def _refresh_action(kind):
    return RefreshAction(
        kind=kind,
        trigger_attribute_uri="trigger",
        configuration_search_attribute_uri="configuration-source",
        device_search_attribute_uri="device-source",
        status_attribute_uri="status",
        message_attribute_uri="message",
        timestamp_attribute_uri="timestamp",
    )


@pytest.mark.parametrize(
    ("kind", "expected_source"),
    (
        (RefreshKind.CONFIGURATION, "configuration-source"),
        (RefreshKind.DEVICE, "device-source"),
        (RefreshKind.ALL_CONFIGURATIONS, None),
        (RefreshKind.ALL_DEVICES, None),
    ),
)
def test_refresh_action_identifies_local_source(kind, expected_source):
    assert _refresh_action(kind).source_attribute_uri == expected_source


def test_refresh_action_lists_trigger_and_feedback_state_attributes():
    assert _refresh_action(RefreshKind.CONFIGURATION).state_attribute_uris == (
        "trigger",
        "status",
        "message",
        "timestamp",
    )


def test_refresh_action_can_define_inputs_for_a_destructive_collection_refresh():
    action = RefreshAction(
        kind=RefreshKind.CONFIGURATION,
        trigger_attribute_uri="apply",
        configuration_search_attribute_uri="configuration-source",
        device_search_attribute_uri="device-source",
        replace_existing_collections=True,
        require_configuration_period=True,
        input_attribute_uris=("start", "end"),
    )

    assert action.replace_existing_collections is True
    assert action.require_configuration_period is True
    assert action.input_attribute_uris == ("start", "end")


@pytest.mark.parametrize(
    ("result", "expected_status"),
    (
        (RefreshResult(2, 2), "success"),
        (RefreshResult(2, 1, (RefreshError("device:2", "unavailable"),)), "partial"),
        (RefreshResult(2, 0, (RefreshError("device:1", "unavailable"),)), "failed"),
    ),
)
def test_refresh_result_status(result, expected_status):
    assert result.status == expected_status


def test_combine_refresh_results_preserves_counts_and_errors():
    result = combine_refresh_results(
        (
            RefreshResult(1, 1, device_requested_count=3, device_refreshed_count=3),
            RefreshResult(
                1,
                0,
                (RefreshError("configuration:2", "not found"),),
                device_requested_count=2,
                device_refreshed_count=1,
            ),
        )
    )

    assert result.requested_count == 2
    assert result.refreshed_count == 1
    assert result.errors == (RefreshError("configuration:2", "not found"),)
    assert result.device_requested_count == 5
    assert result.device_refreshed_count == 4


def test_single_configuration_success_uses_its_label():
    message = format_refresh_message(
        RefreshKind.CONFIGURATION,
        RefreshResult(1, 1, device_requested_count=3, device_refreshed_count=3),
        "KIT Cfg(49): Energy Balance",
    )

    assert message == "Success: KIT Cfg(49): Energy Balance was refreshed. 3 devices were refreshed."


def test_single_configuration_success_uses_singular_device_count():
    message = format_refresh_message(
        RefreshKind.CONFIGURATION,
        RefreshResult(1, 1, device_requested_count=1, device_refreshed_count=1),
        "KIT Cfg(49): Energy Balance",
    )

    assert message == "Success: KIT Cfg(49): Energy Balance was refreshed. 1 device was refreshed."


def test_single_device_success_uses_its_label():
    message = format_refresh_message(
        RefreshKind.DEVICE,
        RefreshResult(1, 1),
        "KIT Cfg(49) KIT Sensor(327): SMT100 soil moisture/temperature (s/n: SMTEB23)",
    )

    assert message == ("Success: KIT Cfg(49) KIT Sensor(327): SMT100 soil moisture/temperature (s/n: SMTEB23) was refreshed.")


def test_bulk_success_uses_aggregate_count():
    message = format_refresh_message(RefreshKind.ALL_DEVICES, RefreshResult(18, 18))

    assert message == "Success: 18 of 18 devices refreshed."


def test_all_configurations_success_includes_aggregate_device_count():
    message = format_refresh_message(
        RefreshKind.ALL_CONFIGURATIONS,
        RefreshResult(4, 4, device_requested_count=27, device_refreshed_count=27),
    )

    assert message == "Success: 4 of 4 configurations refreshed. 27 devices were refreshed."


def test_all_configurations_success_uses_singular_device_count():
    message = format_refresh_message(
        RefreshKind.ALL_CONFIGURATIONS,
        RefreshResult(2, 2, device_requested_count=1, device_refreshed_count=1),
    )

    assert message == "Success: 2 of 2 configurations refreshed. 1 device was refreshed."


def test_all_configurations_success_without_targets_omits_device_count():
    message = format_refresh_message(
        RefreshKind.ALL_CONFIGURATIONS,
        RefreshResult(0, 0),
    )

    assert message == "Success: No configurations were available to refresh."


def test_partial_result_includes_backend_error():
    message = format_refresh_message(
        RefreshKind.ALL_CONFIGURATIONS,
        RefreshResult(
            3,
            2,
            (RefreshError("kitcfg:50", "request timed out"),),
            device_requested_count=5,
            device_refreshed_count=4,
        ),
    )

    assert message == ("Partial: 2 of 3 configurations refreshed. 4 devices were refreshed. kitcfg:50: request timed out")


def test_failed_all_configurations_refresh_includes_zero_device_count_before_errors():
    message = format_refresh_message(
        RefreshKind.ALL_CONFIGURATIONS,
        RefreshResult(
            1,
            0,
            (RefreshError("ufzcfg:310", "unauthorized"),),
            device_requested_count=1,
            device_refreshed_count=0,
        ),
    )

    assert message == ("Failed: 0 of 1 configurations refreshed. 0 devices were refreshed. ufzcfg:310: unauthorized")
