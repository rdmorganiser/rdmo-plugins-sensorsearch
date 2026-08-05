from datetime import datetime
from datetime import timezone as dt_timezone

from rdmo_sensorsearch.handlers.sms_mounting import (
    format_sms_timepoint,
    resolve_mount_location,
    select_latest_device_mount_action,
    select_latest_device_mount_period,
)


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
