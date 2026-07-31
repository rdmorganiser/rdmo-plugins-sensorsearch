import logging

from rdmo.domain.models import Attribute
from rdmo.options.providers import Provider
from rdmo.projects.models import Value

from rdmo_sensorsearch.config import catalog_matches, load_config
from rdmo_sensorsearch.naming import canonical_device_label

logger = logging.getLogger(__name__)


class BaseProjectAttributeOptionsProvider(Provider):
    """
    Provides project-local options from values stored in a catalog-specific source attribute.
    """

    search = False
    refresh = True

    config_section_name: str | None = None

    def get_options(self, project, search=None, user=None, site=None):
        if self.config_section_name is None:
            raise NotImplementedError(f"{type(self).__name__} must define `config_section_name`")

        if project is None or project.catalog is None:
            return []

        source_attribute_uri = self._get_source_attribute_uri(project.catalog.uri)
        if source_attribute_uri is None:
            logger.debug("No source attribute configured for catalog %s", project.catalog.uri)
            return []

        try:
            attribute = Attribute.objects.get(uri=source_attribute_uri)
        except Attribute.DoesNotExist:
            logger.warning("Configured project sensor source attribute does not exist: %s", source_attribute_uri)
            return []

        values = (
            Value.objects.filter(project=project, attribute=attribute)
            .filter(snapshot=None)
            .exclude(text__isnull=True)
            .exclude(text__exact="")
            .order_by("set_prefix", "set_index", "collection_index", "id")
        )

        seen = set()
        options = []
        for value in values:
            option_id = value.external_id or value.text
            if option_id in seen:
                continue

            seen.add(option_id)
            options.append(
                {
                    "id": option_id,
                    "text": canonical_device_label(value.text, value.external_id),
                }
            )

        return options

    def _get_source_attribute_uri(self, catalog_uri: str) -> str | None:
        catalog = self._get_catalog_config(catalog_uri)
        return catalog.get("source_attribute_uri") if catalog else None

    def _get_catalog_config(self, catalog_uri: str) -> dict | None:
        plugin_config = load_config()
        catalogs = plugin_config.get(self.config_section_name, {}).get("catalogs", [])

        for catalog in catalogs:
            if catalog_matches(catalog, catalog_uri):
                return catalog

        return None


class ProjectConfigurationSensorsProvider(BaseProjectAttributeOptionsProvider):
    """
    Provides project-local sensor options that were materialized from a selected configuration.
    """

    config_section_name = "ProjectConfigurationSensorsProvider"


class ProjectDataCollectionDevicesProvider(BaseProjectAttributeOptionsProvider):
    """
    Provides project-local device options for data collection questions.
    """

    config_section_name = "ProjectDataCollectionDevicesProvider"
