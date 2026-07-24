import sys
from pathlib import Path
from urllib.parse import urlsplit

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


ROOT = Path(__file__).parents[1]
CONFIG_PATHS = (ROOT / "sensorsearch.toml", ROOT / "rdmo_sensorsearch" / "config.toml")
EARTH_SENSOR_CATALOG_URI = "https://rdmo.nfdi4earth.de/terms/questions/earth-sensor-with-refresh-feature-v1"


def _load_config(path):
    with path.open("rb") as config_file:
        return tomllib.load(config_file)


def _backend(config, section, id_prefix):
    entries = config[section]
    if isinstance(entries, dict):
        entries = entries["backends"]
    return next(backend for backend in entries if backend["id_prefix"] == id_prefix)


def test_gfz_sms_handlers_and_providers_use_the_same_current_host():
    for path in CONFIG_PATHS:
        config = _load_config(path)
        handler_urls = (
            _backend(config["handlers"], "SensorManagementSystemHandler", "gfzsms")["base_url"],
            _backend(config["handlers"], "SensorManagementSystemConfigurationsHandler", "gfzcfg")["base_url"],
        )
        provider_urls = (
            _backend(config["SensorsProvider"]["providers"], "SensorManagementSystemProvider", "gfzsms")["base_url"],
            _backend(
                config["ConfigurationsProvider"]["providers"],
                "SensorManagementSystemConfigurationsProvider",
                "gfzcfg",
            )["base_url"],
        )

        assert {urlsplit(url).hostname for url in (*handler_urls, *provider_urls)} == {"sensors.gfz.de"}


def test_data_collection_variable_sync_is_explicitly_catalog_scoped():
    for path in CONFIG_PATHS:
        config = _load_config(path)
        catalog_configs = config["DataCollectionVariableSync"]["catalogs"]

        assert catalog_configs
        assert all(catalog_config.get("catalog_uri") or catalog_config.get("catalog_uris") for catalog_config in catalog_configs)
        assert any(
            EARTH_SENSOR_CATALOG_URI
            in ([catalog_config["catalog_uri"]] if catalog_config.get("catalog_uri") else catalog_config["catalog_uris"])
            for catalog_config in catalog_configs
        )
