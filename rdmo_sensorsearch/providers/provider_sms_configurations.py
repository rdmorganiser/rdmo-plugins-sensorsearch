import logging
from urllib.parse import quote

from rdmo_sensorsearch.client import fetch_json
from rdmo_sensorsearch.providers.base import BaseSensorProvider

logger = logging.getLogger(__name__)


class SensorManagementSystemConfigurationsProvider(BaseSensorProvider):
    """
    Searches a Sensor Management System (SMS) API for configurations.

    The SMS API exposes configurations as first-class resources. This provider
    searches them by label and returns one option per matching configuration.
    """

    # Match the SMS frontend configuration search more closely. `q` performs
    # the free-text search; the other flags keep the result set aligned with
    # the public UI behavior.
    query_url = (
        "{base_url}?page[size]={page_size}&page[number]=1&include=created_by.contact"
        "&filter=[]&q={query}&sort=label&hide_archived=false"
    )

    option_id = "{id_prefix}:{id}"
    option_text = "{prefix}({id}): {label}{project}{pid}"

    def get_options(self, project, search=None, user=None, site=None):
        if search is None:
            return []

        query = quote(search)
        url = self.query_url.format(base_url=self.base_url, query=query, page_size=self.max_hits)
        json_fetched = fetch_json(url)

        json_data = json_fetched.get("data", [])
        if not json_data:
            logger.debug("Empty response from SMS configurations API for %s", search)
            return []

        return [
            {
                "id": self.option_id.format(id_prefix=self.id_prefix, id=configuration["id"]),
                "text": self._format_configuration_text(configuration["id"], configuration["attributes"]),
            }
            for configuration in json_data[:self.max_hits]
        ]

    def _format_configuration_text(self, configuration_id: str, attrs: dict) -> str:
        project = f" [{attrs['project']}]" if attrs.get("project") else ""
        persistent_identifier = attrs.get("persistent_identifier")
        pid = f" ({persistent_identifier})" if persistent_identifier else ""
        return self.option_text.format(
            prefix=self.text_prefix,
            id=configuration_id,
            label=attrs.get("label", ""),
            project=project,
            pid=pid,
        )
