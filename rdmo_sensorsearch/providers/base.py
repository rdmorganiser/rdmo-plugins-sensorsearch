import logging

from rdmo.options.providers import Provider

logger = logging.getLogger(__name__)


class BaseSensorProvider(Provider):
    """
    A common base class for sensor providers.

    Subclasses must define the following class attributes:
    - id_prefix
    - text_prefix
    - base_url
    - max_hits

    These can be optionally overridden at instantiation.
    """

    def __init__(
        self,
        id_prefix: str | None = None,
        text_prefix: str | None = None,
        base_url: str | None = None,
        max_hits: int | None = None,
    ):
        self._id_prefix = id_prefix
        self._text_prefix = text_prefix
        self._base_url = base_url
        self._max_hits = max_hits
        self.results = []

    @property
    def id_prefix(self) -> str:
        value = self._id_prefix or getattr(type(self), "id_prefix", None)
        if value is None:
            raise NotImplementedError(f"{type(self).__name__} must define `id_prefix`")
        return value

    @property
    def text_prefix(self) -> str:
        value = self._text_prefix or getattr(type(self), "text_prefix", None)
        if value is None:
            raise NotImplementedError(f"{type(self).__name__} must define `text_prefix`")
        return value

    @property
    def base_url(self) -> str:
        value = self._base_url or getattr(type(self), "base_url", None)
        if value is None:
            raise NotImplementedError(f"{type(self).__name__} must define `base_url`")
        return value

    @base_url.setter
    def base_url(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("base_url must be a string")
        self._base_url = value

    @property
    def max_hits(self) -> int:
        value = self._max_hits if self._max_hits is not None else getattr(type(self), "max_hits", None)
        if value is None:
            raise NotImplementedError(f"{type(self).__name__} must define `max_hits`")
        return value

