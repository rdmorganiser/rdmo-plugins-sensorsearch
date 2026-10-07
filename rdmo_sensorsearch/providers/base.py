import logging

from rdmo.options.providers import Provider

logger = logging.getLogger(__name__)


class BaseRemoteSearchProvider(Provider):
    """Remote search provider configured explicitly by typed backend assembly."""

    backend_name: str
    backend_type: str
    resource_kind: str

    def __init__(
        self,
        *,
        id_prefix: str,
        text_prefix: str,
        base_url: str,
        max_hits: int,
    ):
        self._id_prefix = id_prefix
        self._text_prefix = text_prefix
        self.base_url = base_url
        self._max_hits = max_hits

    @property
    def id_prefix(self) -> str:
        return self._id_prefix

    @property
    def text_prefix(self) -> str:
        return self._text_prefix

    @property
    def base_url(self) -> str:
        return self._base_url

    @base_url.setter
    def base_url(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("base_url must be a string")
        self._base_url = value

    @property
    def max_hits(self) -> int:
        return self._max_hits

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}:id={self.id_prefix}, "
            f"text={self.text_prefix},max_hits={self.max_hits}, base_url={self.base_url}"
        )
