import logging

from rdmo.domain.models import Attribute
from rdmo.options.providers import Provider
from rdmo.projects.models import Value

from rdmo_sensorsearch.config import load_config

logger = logging.getLogger(__name__)


class ProjectConfigurationSensorsProvider(Provider):
    """
    Provides project-local sensor options that were materialized from a selected configuration.
    """

    search = False
    refresh = True

    config_key = "ProjectConfigurationSensorsProvider"

    def get_options(self, project, search=None, user=None, site=None):
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
            options.append({"id": option_id, "text": value.text})

        return options

    def _get_source_attribute_uri(self, catalog_uri: str) -> str | None:
        configuration = load_config()
        catalogs = configuration.get(self.config_key, {}).get("catalogs", [])

        for catalog in catalogs:
            if catalog.get("catalog_uri") == catalog_uri:
                return catalog.get("source_attribute_uri")

        return None
