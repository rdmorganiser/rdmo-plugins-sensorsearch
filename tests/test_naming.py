import pytest

from rdmo_sensorsearch.naming import (
    canonical_configuration_label,
    canonical_device_label,
    configuration_short_label,
    configuration_tab_label,
    device_detail_tab_label,
)


@pytest.mark.parametrize(
    ("external_id", "expected"),
    [
        ("gfzcfg:12", "GFZ Cfg(12)"),
        ("kitcfg:49", "KIT Cfg(49)"),
        ("ufzcfg:310", "UFZ Cfg(310)"),
        ("o2amission:30", "O2A M(30)"),
    ],
)
def test_configuration_short_label(external_id, expected):
    assert configuration_short_label(external_id) == expected


@pytest.mark.parametrize("external_id", [None, "", "manual", "sensor:327", "cfg:49"])
def test_configuration_short_label_rejects_unknown_external_ids(external_id):
    assert configuration_short_label(external_id) is None


@pytest.mark.parametrize(
    ("external_id", "legacy_label", "expected"),
    [
        (
            "kitcfg:49",
            "KIT Configuration(49): Energy Balance",
            "KIT Cfg(49): Energy Balance",
        ),
        (
            "o2amission:30",
            "O2A Mission(30): HYDREX",
            "O2A M(30): HYDREX",
        ),
    ],
)
def test_canonical_configuration_label(external_id, legacy_label, expected):
    assert canonical_configuration_label(legacy_label, external_id) == expected


@pytest.mark.parametrize(
    ("current_label", "external_id", "source_label", "expected"),
    [
        (
            "o2a-test",
            "o2amission:30",
            "O2A M(30): HYDREX",
            "O2A M(30): o2a-test",
        ),
        (
            "O2A M(30): o2a-test",
            "o2amission:30",
            "O2A M(30): HYDREX",
            "O2A M(30): o2a-test",
        ),
        (
            "O2A M(30): o2a-test",
            "kitcfg:49",
            "KIT Cfg(49): Energy Balance",
            "KIT Cfg(49): o2a-test",
        ),
        (
            "KIT Cfg(49): Energy Balance",
            None,
            "",
            "Energy Balance",
        ),
        (
            "",
            "o2amission:30",
            "O2A Mission(30): HYDREX",
            "O2A M(30): HYDREX",
        ),
        (
            "manual",
            None,
            "",
            "manual",
        ),
    ],
)
def test_configuration_tab_label(current_label, external_id, source_label, expected):
    assert configuration_tab_label(current_label, external_id, source_label) == expected


@pytest.mark.parametrize(
    ("external_id", "legacy_label", "expected"),
    [
        (
            "kitsms:327",
            "KIT Sensors:(327): SMT100",
            "KIT Sensor(327): SMT100",
        ),
        (
            "o2aregistry:3581",
            "O2A REGISTRY: HydroFIA",
            "O2A Item(3581): HydroFIA",
        ),
        (
            "gfzgipp:1",
            "GIPP: BASE_X2-26115",
            "GFZ GIPP Instrument(1): BASE_X2-26115",
        ),
        (
            "kitsms:327",
            "KIT Sensor(327) Config(49): SMT100",
            "KIT Cfg(49) KIT Sensor(327): SMT100",
        ),
        (
            "o2aregistry:4152",
            "O2A Item(4152) Mission(30): SST_CTD_519",
            "O2A M(30) O2A Item(4152): SST_CTD_519",
        ),
        (
            "kitsms:327",
            "Cfg(49) KIT Sensor(327): SMT100",
            "KIT Cfg(49) KIT Sensor(327): SMT100",
        ),
        (
            "kitsms:327",
            "KIT Cfg(49) KIT Sensor(327): SMT100",
            "KIT Cfg(49) KIT Sensor(327): SMT100",
        ),
    ],
)
def test_canonical_device_label(external_id, legacy_label, expected):
    assert canonical_device_label(legacy_label, external_id) == expected


def test_device_detail_tab_label_prefixes_manual_device_with_configuration():
    assert (
        device_detail_tab_label(
            "KIT Cfg(49)",
            "KIT Sensor(565): Parsivel Disdrometer 2019A (s/n: 450399 (2019A))",
        )
        == "KIT Cfg(49) KIT Sensor(565): Parsivel Disdrometer 2019A (s/n: 450399 (2019A))"
    )


def test_device_detail_tab_label_uses_o2a_item_external_id_for_legacy_provider_text():
    assert device_detail_tab_label(
        "s1",
        "O2A REGISTRY: ###HydroFIA Total Alkalinity analyzer "
        "(s/n: TA-0317-001, id: station:svluwobs:fb_731101:hydrofia_0317-001)",
        "o2aregistry:3581",
    ) == (
        "s1 O2A Item(3581): ###HydroFIA Total Alkalinity analyzer "
        "(s/n: TA-0317-001, id: station:svluwobs:fb_731101:hydrofia_0317-001)"
    )


def test_device_detail_tab_label_keeps_canonical_o2a_item_name():
    assert (
        device_detail_tab_label(
            "s1",
            "O2A Item(3581): HydroFIA",
            "o2aregistry:3581",
        )
        == "s1 O2A Item(3581): HydroFIA"
    )


@pytest.mark.parametrize(
    ("configuration_label", "device_label", "expected"),
    [
        (
            "KIT Cfg(49)",
            "KIT Cfg(49) KIT Sensor(327): SMT100 soil moisture/temperature (s/n: SMTEB23)",
            "KIT Cfg(49) KIT Sensor(327): SMT100 soil moisture/temperature (s/n: SMTEB23)",
        ),
        (
            "O2A M(30)",
            "O2A M(30) O2A Item(4152): SST_CTD_519 (s/n: 519)",
            "O2A M(30) O2A Item(4152): SST_CTD_519 (s/n: 519)",
        ),
        (
            "s1",
            "Chromium Controller (s/n: 12290)",
            "s1 Chromium Controller (s/n: 12290)",
        ),
    ],
)
def test_device_detail_tab_label_uses_configuration_first(configuration_label, device_label, expected):
    assert device_detail_tab_label(configuration_label, device_label) == expected
