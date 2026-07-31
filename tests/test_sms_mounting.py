from datetime import datetime
from datetime import timezone as dt_timezone

from rdmo_sensorsearch.handlers.sms_mounting import (
    resolve_mount_location,
    select_latest_device_mount_action,
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


def test_configuration_height_plus_device_offset_matches_tower_example():
    device_action = _action("647", device_id="607", offset_z=50)

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [],
        [_static_location("14")],
        now=datetime(2026, 7, 30, tzinfo=dt_timezone.utc),
    )

    assert mount_location.height_amsl == 160
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

    assert mount_location.height_amsl == 95.6
    assert mount_location.vertical_surface_offset == -0.4
    assert mount_location.site_name == ""


def test_explicit_mount_height_overrides_configuration_height():
    device_action = _action("652", device_id="49", offset_z=0, z=140)

    mount_location = resolve_mount_location(
        device_action,
        [device_action],
        [],
        [_static_location("14", z=110)],
    )

    assert mount_location.height_amsl == 140
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

    assert mount_location.height_amsl == 108
    assert mount_location.vertical_surface_offset == 8


def test_nearest_explicit_parent_height_anchors_child_offset():
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

    assert mount_location.height_amsl == 118
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

    assert mount_location.height_amsl == 202
    assert mount_location.site_name == "New site"


def test_missing_parent_does_not_publish_partial_offset_or_derived_height():
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

    assert mount_location.height_amsl is None
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

    assert mount_location.height_amsl is None
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
