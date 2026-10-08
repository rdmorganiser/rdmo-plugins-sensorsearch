import logging

from rdmo_sensorsearch.contracts import BackendFailure, DeviceSearch, SearchRecord
from rdmo_sensorsearch.providers.base import BaseRemoteSearchProvider

logger = logging.getLogger(__name__)


class O2ARegistryItemProvider(BaseRemoteSearchProvider):
    """Format O2A device search results as RDMO options."""

    def __init__(self, *, backend: DeviceSearch, id_prefix: str, text_prefix: str, max_hits: int):
        super().__init__(id_prefix=id_prefix, text_prefix=text_prefix, max_hits=max_hits)
        self.backend = backend

    def get_options(self, project, search=None, user=None, site=None):
        if search is None:
            return []
        response = self.backend.search_devices(search, limit=self.max_hits, auth_token=getattr(self, "auth_token", None))
        if isinstance(response, BackendFailure):
            logger.debug("O2A item search failed: %s", response.errors)
            return []
        return [self.parse_option(record) for record in response.value]

    def parse_option(self, record: SearchRecord) -> dict[str, str]:
        attrs = record.attributes
        serial = f"s/n: {attrs['serial']}, " if attrs.get("serial") else ""
        return {
            "id": f"{self.id_prefix}:{record.identifier}",
            "text": f"{self.text_prefix}({record.identifier}): {attrs['title']} ({serial}id: {attrs['registry_id']})",
        }
