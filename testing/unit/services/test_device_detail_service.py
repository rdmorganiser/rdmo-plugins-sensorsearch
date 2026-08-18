from types import SimpleNamespace

from rdmo_sensorsearch.services.device_details import (
    DeviceBlockReference,
    SelectedDevice,
    base_device_text,
    compose_device_block_key,
    configuration_key_from_device_block,
    parse_device_block_key,
    parse_external_id,
    plan_device_detail_reconciliation,
    unique_selected_devices,
)


def _device(external_id: str, text: str | None = None) -> SelectedDevice:
    return SelectedDevice(text=text or external_id, external_id=external_id)


def test_device_identity_helpers_define_the_materialized_block_format():
    block_key = compose_device_block_key("kitcfg:27", "kitsms:324")

    assert block_key == "kitcfg:27||kitsms:324"
    assert parse_device_block_key(block_key) == ("kitcfg:27", "kitsms:324")
    assert configuration_key_from_device_block(block_key) == "kitcfg:27"
    assert configuration_key_from_device_block("kitsms:324") is None
    assert parse_external_id("kitsms:324") == ("kitsms", "324")
    assert parse_external_id("324") == (None, "324")
    assert base_device_text("KIT Sensor: Temperature probe") == "Temperature probe"


def test_selected_devices_are_deduplicated_by_external_id_in_source_order():
    first = _device("kitsms:1", "first")
    duplicate = _device("kitsms:1", "duplicate")
    second = _device("kitsms:2", "second")

    assert unique_selected_devices((first, duplicate, _device(""), second)) == (first, second)


def test_planner_separates_existing_new_stale_and_unroutable_devices():
    existing_key = "kitcfg:27||kitsms:1"
    stale = DeviceBlockReference(set_index=7)
    bindings = {
        "kitsms:1": SimpleNamespace(name="existing"),
        "kitsms:2": SimpleNamespace(name="new"),
    }
    metadata_reads = []
    refresh_reads = []

    def metadata_is_current(device, block_key, set_index, binding):
        metadata_reads.append((device.external_id, block_key, set_index, binding.name))
        return True

    def refresh_is_required(set_index):
        refresh_reads.append(set_index)
        return False

    plan = plan_device_detail_reconciliation(
        selected_devices=(
            _device("kitsms:1"),
            _device("kitsms:2"),
            _device("unknown:3"),
            _device("kitsms:2", "duplicate"),
        ),
        configuration_key="kitcfg:27",
        configuration_external_id="kitcfg:27",
        set_prefix="configuration-row",
        existing_blocks={
            existing_key: DeviceBlockReference(set_index=2),
            "kitcfg:27||kitsms:old": stale,
        },
        next_set_index=8,
        resolve_handler=bindings.get,
        metadata_is_current=metadata_is_current,
        refresh_is_required=refresh_is_required,
    )

    assert plan.stale_blocks == (stale,)
    assert [(block.device.external_id, block.set_index) for block in plan.blocks] == [
        ("kitsms:1", 2),
        ("kitsms:2", 8),
    ]
    assert plan.blocks[0].needs_metadata_write is False
    assert plan.blocks[0].needs_refresh is False
    assert plan.blocks[1].needs_metadata_write is True
    assert plan.blocks[1].needs_refresh is True
    assert plan.blocks[1].set_prefix == "configuration-row"
    assert plan.blocks[1].configuration_external_id == "kitcfg:27"
    assert [(failure.external_id, failure.message) for failure in plan.failures] == [
        ("unknown:3", "No matching device handler is configured.")
    ]
    assert metadata_reads == [("kitsms:1", existing_key, 2, "existing")]
    assert refresh_reads == [2]


def test_force_refresh_skips_the_existing_refresh_state_read():
    refresh_reads = []
    block_key = "o2amission:9||o2aregistry:4"

    plan = plan_device_detail_reconciliation(
        selected_devices=(_device("o2aregistry:4"),),
        configuration_key="o2amission:9",
        configuration_external_id="o2amission:9",
        set_prefix="",
        existing_blocks={block_key: DeviceBlockReference(set_index=3)},
        next_set_index=4,
        resolve_handler=lambda _external_id: object(),
        metadata_is_current=lambda *_args: True,
        refresh_is_required=lambda set_index: refresh_reads.append(set_index) or False,
        force_refresh=True,
    )

    assert plan.blocks[0].needs_metadata_write is False
    assert plan.blocks[0].needs_refresh is True
    assert refresh_reads == []


def test_unroutable_selected_device_keeps_its_existing_block_out_of_stale_cleanup():
    block = DeviceBlockReference(set_index=5)

    plan = plan_device_detail_reconciliation(
        selected_devices=(_device("unknown:3"),),
        configuration_key="cfg:1",
        configuration_external_id="cfg:1",
        set_prefix="",
        existing_blocks={"cfg:1||unknown:3": block},
        next_set_index=6,
        resolve_handler=lambda _external_id: None,
        metadata_is_current=lambda *_args: False,
        refresh_is_required=lambda _set_index: True,
    )

    assert plan.blocks == ()
    assert plan.stale_blocks == ()
    assert len(plan.failures) == 1
