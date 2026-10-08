import logging

from rdmo.options.providers import Provider

logger = logging.getLogger(__name__)


class BaseRemoteSearchProvider(Provider):
    """Remote search provider configured explicitly by typed backend assembly."""

    backend_name: str
    backend_type: str
    resource_kind: str
    auth_token: str | None = None

    def __init__(
        self,
        *,
        id_prefix: str,
        text_prefix: str,
        max_hits: int,
    ):
        self._id_prefix = id_prefix
        self._text_prefix = text_prefix
        self._max_hits = max_hits

    @property
    def id_prefix(self) -> str:
        return self._id_prefix

    @property
    def text_prefix(self) -> str:
        return self._text_prefix

    @property
    def max_hits(self) -> int:
        return self._max_hits

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}:id={self.id_prefix}, text={self.text_prefix},max_hits={self.max_hits}"
