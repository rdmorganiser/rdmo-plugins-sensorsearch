from datetime import datetime
from datetime import timezone as dt_timezone

import pytest

from rdmo_sensorsearch.handlers.sms_mounting import (
    MountLocationNoticeCode,
    format_sms_timepoint,
    resolve_mount_location,
    select_latest_device_mount_action,
    select_latest_device_mount_period,
)


def _notice_codes(mount_location):
    return {notice.code for notice in mount_location.notices}


def _action(
    action_id,
    *,
    action_type="device_mount_action",
    device_id=None,
    platform_id=None,
    parent_device_id=None,
    parent_platform_id=None,
    configuration_id="27",
    begin_date="2025-01-01T00:00:00Z",
    end_date=None,
    offset_z=0,
    z=None,
    serial_number=None,
):
    relationships = {
        "configuration": {"data": {"type": "configuration", "id": configuration_id}},
        "device": {"data": {"type": "device", "id": device_id}} if device_id else {"data": None},
        "platform": {"data": {"type": "platform", "id": platform_id}} if platform_id else {"data": None},
        "parent_device": ({"data": {"type": "device", "id": parent_device_id}} if parent_device_id else {"data": None}),
        "parent_platform": ({"data": {"type": "platform", "id": parent_platform_id}} if parent_platform_id else {"data": None}),
    }
    return {
        "type": action_type,
        "id": str(action_id),
        "attributes": {
            "begin_date": begin_date,
            "end_date": end_date,
            "offset_z": offset_z,
            "z": z,
            "serial_number": serial_number,
        },
        "relationships": relationships,
    }


def _static_location(
    action_id,
    *,
    begin_date="1972-12-01T00:00:00Z",
    end_date=None,
    z=110,
    label="Wettermast_CN",
):
    return {
        "type": "configuration_static_location_action",
        "id": str(action_id),
        "attributes": {
            "begin_date": begin_date,
            "end_date": end_date,
            "z": z,
            "label": label,
        },
    }


def test_station_height_is_not_combined_with_device_offset():
    device_action = _action("647", device_id="607", offset_z=50)

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [],
        [_static_location("14")],
        now=datetime(2026, 7, 30, tzinfo=dt_timezone.utc),
    )

    assert mount_location.station_height_amsl == 110
    assert mount_location.vertical_surface_offset == 50
    assert mount_location.site_name == "Wettermast_CN"


def test_negative_offset_is_preserved_as_depth_below_surface():
    device_action = _action("742", device_id="324", configuration_id="88", offset_z=-0.4)

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [],
        [_static_location("66", z=96, label="")],
    )

    assert mount_location.station_height_amsl == 96
    assert mount_location.vertical_surface_offset == -0.4
    assert mount_location.site_name == ""


def test_mount_height_does_not_override_station_height():
    device_action = _action("652", device_id="49", offset_z=0, z=140)

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [],
        [_static_location("14", z=110)],
    )

    assert mount_location.station_height_amsl == 110
    assert mount_location.vertical_surface_offset == 0


def test_mount_height_is_not_used_when_static_location_has_no_height():
    device_action = _action("652", device_id="49", offset_z=0, z=140)

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [],
        [_static_location("14", z=None)],
    )

    assert mount_location.station_height_amsl is None
    assert mount_location.vertical_surface_offset == 0


def test_nested_platform_offsets_are_summed_to_configuration_root():
    platform_action = _action(
        "platform-1",
        action_type="platform_mount_action",
        platform_id="tower",
        offset_z=10,
    )
    device_action = _action(
        "device-1",
        device_id="sensor",
        parent_platform_id="tower",
        offset_z=-2,
    )

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [platform_action],
        [_static_location("location-1", z=100)],
    )

    assert mount_location.station_height_amsl == 100
    assert mount_location.vertical_surface_offset == 8


def test_parent_mount_height_does_not_override_station_height():
    platform_action = _action(
        "platform-1",
        action_type="platform_mount_action",
        platform_id="tower",
        offset_z=10,
        z=120,
    )
    device_action = _action(
        "device-1",
        device_id="sensor",
        parent_platform_id="tower",
        offset_z=-2,
    )

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [platform_action],
        [_static_location("location-1", z=100)],
    )

    assert mount_location.station_height_amsl == 100
    assert mount_location.vertical_surface_offset == 8


def test_historical_mount_uses_static_location_at_end_of_mount():
    device_action = _action(
        "device-1",
        device_id="sensor",
        begin_date="2025-01-01T00:00:00Z",
        end_date="2025-06-01T00:00:00Z",
        offset_z=2,
    )
    old_location = _static_location(
        "old",
        begin_date="2024-01-01T00:00:00Z",
        end_date="2025-03-01T00:00:00Z",
        z=100,
        label="Old site",
    )
    new_location = _static_location(
        "new",
        begin_date="2025-03-01T00:00:00Z",
        z=200,
        label="New site",
    )

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [],
        [old_location, new_location],
    )

    assert mount_location.station_height_amsl == 200
    assert mount_location.site_name == "New site"


def test_static_location_can_use_a_bounded_end_tolerance_for_configuration_43():
    device_action = _action(
        "506",
        device_id="338",
        configuration_id="43",
        begin_date="2025-05-10T12:00:00Z",
        end_date="2025-08-10T12:00:00Z",
        offset_z=5,
    )
    static_location = _static_location(
        "32",
        begin_date="2025-05-10T12:00:00Z",
        end_date="2025-08-10T11:59:00Z",
        z=594,
        label="St. Martin in Passeier",
    )

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [],
        [static_location],
        static_location_end_tolerance_seconds=120,
    )

    assert mount_location.station_height_amsl == 594
    assert mount_location.vertical_surface_offset == 5
    assert mount_location.site_name == "St. Martin in Passeier"
    assert MountLocationNoticeCode.STATIC_LOCATION_TOLERANCE_USED.value in _notice_codes(mount_location)


def test_exact_static_location_takes_precedence_over_tolerance_candidate():
    device_action = _action(
        "device-1",
        device_id="sensor",
        begin_date="2025-01-01T00:00:00Z",
        end_date="2025-06-01T00:00:00Z",
    )
    tolerance_candidate = _static_location(
        "tolerance",
        begin_date="2025-01-01T00:00:00Z",
        end_date="2025-05-31T23:59:00Z",
        z=100,
        label="Tolerance site",
    )
    exact = _static_location(
        "exact",
        begin_date="2025-05-31T23:59:30Z",
        end_date="2025-06-01T00:00:00Z",
        z=200,
        label="Exact site",
    )

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [],
        [tolerance_candidate, exact],
        static_location_end_tolerance_seconds=120,
    )

    assert mount_location.station_height_amsl == 200
    assert mount_location.site_name == "Exact site"
    assert MountLocationNoticeCode.STATIC_LOCATION_TOLERANCE_USED.value not in _notice_codes(mount_location)


def test_static_location_outside_end_tolerance_is_not_reused():
    device_action = _action(
        "device-1",
        device_id="sensor",
        begin_date="2025-01-01T00:00:00Z",
        end_date="2025-06-01T00:00:00Z",
    )
    static_location = _static_location(
        "old",
        begin_date="2025-01-01T00:00:00Z",
        end_date="2025-05-31T23:57:59Z",
        z=100,
        label="Old site",
    )

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [],
        [static_location],
        static_location_end_tolerance_seconds=120,
    )

    assert mount_location.station_height_amsl is None
    assert mount_location.site_name is None
    assert MountLocationNoticeCode.STATIC_LOCATION_NOT_ACTIVE.value in _notice_codes(mount_location)


def test_static_location_at_exact_end_tolerance_boundary_is_reused():
    device_action = _action(
        "device-1",
        device_id="sensor",
        begin_date="2025-01-01T00:00:00Z",
        end_date="2025-06-01T00:00:00Z",
    )
    static_location = _static_location(
        "boundary",
        begin_date="2025-01-01T00:00:00Z",
        end_date="2025-05-31T23:57:59.999999Z",
        z=123,
    )

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [],
        [static_location],
        static_location_end_tolerance_seconds=120,
    )

    assert mount_location.station_height_amsl == 123
    assert MountLocationNoticeCode.STATIC_LOCATION_TOLERANCE_USED.value in _notice_codes(mount_location)


def test_tolerance_does_not_reuse_a_location_that_does_not_overlap_the_mount():
    device_action = _action(
        "device-1",
        device_id="sensor",
        begin_date="2025-05-31T23:59:30Z",
        end_date="2025-06-01T00:00:00Z",
    )
    static_location = _static_location(
        "stale",
        begin_date="2025-01-01T00:00:00Z",
        end_date="2025-05-31T23:59:00Z",
        z=123,
    )

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [],
        [static_location],
        static_location_end_tolerance_seconds=120,
    )

    assert mount_location.station_height_amsl is None
    assert MountLocationNoticeCode.STATIC_LOCATION_NOT_ACTIVE.value in _notice_codes(mount_location)


def test_tolerance_selection_prefers_latest_start_when_end_gaps_match():
    device_action = _action(
        "device-1",
        device_id="sensor",
        begin_date="2025-01-01T00:00:00Z",
        end_date="2025-06-01T00:00:00Z",
    )
    earlier = _static_location(
        "earlier",
        begin_date="2025-01-01T00:00:00Z",
        end_date="2025-05-31T23:59:00Z",
        z=100,
    )
    later = _static_location(
        "later",
        begin_date="2025-02-01T00:00:00Z",
        end_date="2025-05-31T23:59:00Z",
        z=200,
    )

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [],
        [earlier, later],
        static_location_end_tolerance_seconds=120,
    )

    assert mount_location.station_height_amsl == 200


def test_missing_parent_keeps_station_height_but_not_partial_offset():
    device_action = _action(
        "device-1",
        device_id="sensor",
        parent_platform_id="private-platform",
        offset_z=-2,
    )

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [],
        [_static_location("location-1", z=100)],
    )

    assert mount_location.station_height_amsl == 100
    assert mount_location.vertical_surface_offset is None
    assert MountLocationNoticeCode.PARENT_MOUNT_ACTION_MISSING.value in _notice_codes(mount_location)


def test_direct_device_offset_policy_recovers_configuration_47_soil_sensor_depth():
    device_action = _action(
        "585",
        device_id="330",
        configuration_id="47",
        parent_platform_id="55",
        begin_date="2025-05-07T00:00:00Z",
        end_date="2025-08-10T12:00:00Z",
        offset_z=-0.1,
    )

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [],
        [_static_location("76", z=235, label="TEAMx KITcube main site Bozen/Bolzano")],
        incomplete_mount_chain_policy="direct_device_offset",
    )

    assert mount_location.station_height_amsl == 235
    assert mount_location.vertical_surface_offset == -0.1
    assert mount_location.site_name == "TEAMx KITcube main site Bozen/Bolzano"
    assert _notice_codes(mount_location) >= {
        MountLocationNoticeCode.PARENT_MOUNT_ACTION_MISSING.value,
        MountLocationNoticeCode.DIRECT_DEVICE_OFFSET_USED.value,
    }


def test_direct_device_offset_policy_does_not_turn_a_missing_offset_into_zero():
    device_action = _action(
        "device-1",
        device_id="sensor",
        parent_platform_id="missing-platform",
    )
    device_action["attributes"].pop("offset_z")

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [],
        [_static_location("location-1")],
        incomplete_mount_chain_policy="direct_device_offset",
    )

    assert mount_location.vertical_surface_offset is None
    assert MountLocationNoticeCode.DEVICE_OFFSET_MISSING.value in _notice_codes(mount_location)


def test_direct_device_offset_policy_rejects_a_nonnumeric_offset():
    device_action = _action(
        "device-1",
        device_id="sensor",
        parent_platform_id="missing-platform",
        offset_z="below",
    )

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [],
        [_static_location("location-1")],
        incomplete_mount_chain_policy="direct_device_offset",
    )

    assert mount_location.vertical_surface_offset is None
    assert MountLocationNoticeCode.DEVICE_OFFSET_INVALID.value in _notice_codes(mount_location)


@pytest.mark.parametrize("policy", ("strict", "direct_device_offset"))
def test_complete_mount_chain_has_the_same_result_under_both_policies(policy):
    platform_action = _action(
        "platform-1",
        action_type="platform_mount_action",
        platform_id="tower",
        offset_z=3,
    )
    device_action = _action(
        "device-1",
        device_id="sensor",
        parent_platform_id="tower",
        offset_z=-0.5,
    )

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [platform_action],
        [_static_location("location-1")],
        incomplete_mount_chain_policy=policy,
    )

    assert mount_location.vertical_surface_offset == 2.5
    assert mount_location.notices == ()


@pytest.mark.parametrize("policy", ("strict", "direct_device_offset"))
def test_incomplete_chain_policy_does_not_hide_a_mount_chain_cycle(policy):
    device_action = _action(
        "device-action",
        device_id="sensor",
        parent_device_id="relay",
        offset_z=-0.1,
    )
    relay_action = _action(
        "relay-action",
        device_id="relay",
        parent_device_id="sensor",
        offset_z=2,
    )

    mount_location = resolve_mount_location(
        device_action,
        [device_action, relay_action],
        [],
        [_static_location("location-1")],
        incomplete_mount_chain_policy=policy,
    )

    assert mount_location.vertical_surface_offset is None
    assert MountLocationNoticeCode.MOUNT_CHAIN_CYCLE.value in _notice_codes(mount_location)
    assert MountLocationNoticeCode.DIRECT_DEVICE_OFFSET_USED.value not in _notice_codes(mount_location)


def test_expired_static_location_is_not_reused_during_dynamic_location_period():
    device_action = _action(
        "device-1",
        device_id="sensor",
        begin_date="2025-06-01T00:00:00Z",
        offset_z=-2,
    )
    expired_location = _static_location(
        "expired",
        begin_date="2024-01-01T00:00:00Z",
        end_date="2025-03-01T00:00:00Z",
        z=100,
        label="Former site",
    )

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [],
        [expired_location],
        now=datetime(2026, 7, 30, tzinfo=dt_timezone.utc),
    )

    assert mount_location.station_height_amsl is None
    assert mount_location.vertical_surface_offset == -2
    assert mount_location.site_name is None


def test_latest_device_mount_action_is_selected_for_configuration():
    older = _action(
        "old",
        device_id="sensor",
        begin_date="2024-01-01T00:00:00Z",
        end_date="2025-01-01T00:00:00Z",
    )
    newer = _action(
        "new",
        device_id="sensor",
        begin_date="2025-01-01T00:00:00Z",
    )
    other_configuration = _action(
        "other",
        device_id="sensor",
        configuration_id="99",
        begin_date="2026-01-01T00:00:00Z",
    )

    selected = select_latest_device_mount_action(
        [older, other_configuration, newer],
        configuration_id="27",
        device_id="sensor",
    )

    assert selected is newer


def test_latest_device_mount_period_ignores_invalid_and_nonmatching_actions():
    older = _action(
        "old",
        device_id="sensor",
        begin_date="2024-01-01T00:00:00Z",
        end_date="2024-06-01T00:00:00Z",
        serial_number=" ABC-1 ",
    )
    newer = _action(
        "new",
        device_id="sensor",
        begin_date="2025-01-01T02:30:00+02:00",
        serial_number="abc-1",
    )
    invalid = _action(
        "invalid",
        device_id="sensor",
        begin_date="not-a-date",
        serial_number="abc-1",
    )
    other_serial = _action(
        "other-serial",
        device_id="sensor",
        begin_date="2026-01-01T00:00:00Z",
        serial_number="xyz-9",
    )

    period = select_latest_device_mount_period(
        [older, invalid, other_serial, newer],
        configuration_id="27",
        device_id="sensor",
        serial_number="  AbC-1 ",
    )

    assert period is not None
    assert period.action is newer
    assert period.formatted() == ("2025-01-01 00:30", None)


def test_latest_device_mount_period_requires_matching_device_and_configuration():
    period = select_latest_device_mount_period(
        [_action("other", device_id="other-device", configuration_id="99")],
        configuration_id="27",
        device_id="sensor",
    )

    assert period is None


def test_sms_timepoint_format_treats_naive_values_as_utc():
    assert format_sms_timepoint(datetime(2025, 2, 3, 4, 5)) == "2025-02-03 04:05"
    assert format_sms_timepoint(None) is None
