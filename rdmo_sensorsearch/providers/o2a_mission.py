import logging
from collections import defaultdict

from rdmo_sensorsearch.contracts import BackendFailure, ConfigurationSearch, SearchRecord
from rdmo_sensorsearch.providers.base import BaseRemoteSearchProvider

logger = logging.getLogger(__name__)


class O2ARegistryMissionProvider(BaseRemoteSearchProvider):
    """Format mission search records using the configured presentation template."""

    option_id = "{id_prefix}:{id}"
    option_text = "{prefix}({id}): {name}"

    def __init__(self, *, backend: ConfigurationSearch, id_prefix: str, text_prefix: str, base_url: str, max_hits: int):
        super().__init__(id_prefix=id_prefix, text_prefix=text_prefix, base_url=base_url, max_hits=max_hits)
        self.backend = backend

    def get_options(self, project, search=None, user=None, site=None):
        if search is None:
            return []
        response = self.backend.search_configurations(search, limit=self.max_hits, auth_token=getattr(self, "auth_token", None))
        if isinstance(response, BackendFailure):
            logger.debug("O2A mission search failed: %s", response.errors)
            return []
        return [
            {
                "id": self.option_id.format(id_prefix=self.id_prefix, id=record.identifier),
                "text": self._format_mission_text(record),
            }
            for record in response.value
        ]

    def _format_mission_text(self, record: SearchRecord) -> str:
        values = defaultdict(str, record.attributes)
        values.update(prefix=self.text_prefix, id=record.identifier)
        return self.option_text.format_map(values)
