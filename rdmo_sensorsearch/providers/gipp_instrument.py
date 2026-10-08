import logging

from rdmo_sensorsearch.contracts import BackendFailure, DeviceSearch
from rdmo_sensorsearch.providers.base import BaseRemoteSearchProvider

logger = logging.getLogger(__name__)


class GIPPInstrumentProvider(BaseRemoteSearchProvider):
    """Format GIPP search records as RDMO options."""

    option_id = "{prefix}:{id}"
    option_text = "{prefix}({id}): {code}"

    def __init__(self, *, backend: DeviceSearch, id_prefix: str, text_prefix: str, base_url: str, max_hits: int):
        super().__init__(id_prefix=id_prefix, text_prefix=text_prefix, base_url=base_url, max_hits=max_hits)
        self.backend = backend

    def get_options(self, project, search=None, user=None, site=None):
        if not search:
            return []
        response = self.backend.search_devices(search, limit=self.max_hits, auth_token=getattr(self, "auth_token", None))
        if isinstance(response, BackendFailure):
            logger.debug("GIPP search failed: %s", response.errors)
            return []
        return [
            {
                "id": self.option_id.format(prefix=self.id_prefix, id=record.identifier),
                "text": self.option_text.format(prefix=self.text_prefix, id=record.identifier, code=record.attributes["code"]),
            }
            for record in response.value
        ]
