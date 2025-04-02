import logging
from rdmo.options.providers import Provider

logger = logging.getLogger(__name__)


class BaseSensorProvider(Provider):
    """
    A common base class for sensor providers.

    Subclasses should override the class attributes:
    - id_prefix
    - text_prefix
    - max_hits
    - base_url

    These can also be overridden per instance via init args.
    """

    id_prefix: str = None
    text_prefix: str = None
    max_hits: int = 10

    def __init__(
        self,
        id_prefix: str = None,
        text_prefix: str = None,
        base_url: str = None,
        max_hits: int = None
    ):
        if id_prefix is not None:
            self.id_prefix = id_prefix
        if text_prefix is not None:
            self.text_prefix = text_prefix
        if base_url is not None:
            self.base_url = base_url
        else:
            self._base_url = None
        if max_hits is not None:
            self.max_hits = max_hits


    @property
    def id_prefix(self) -> str:
        value = getattr(type(self), "id_prefix", None)
        if value is None:
            raise NotImplementedError(f"{type(self).__name__} must define `id_prefix`")
        return value

    @property
    def text_prefix(self) -> str:
        value = getattr(type(self), "text_prefix", None)
        if value is None:
            raise NotImplementedError(f"{type(self).__name__} must define `text_prefix`")
        return value

    @property
    def base_url(self) -> str:
        value = self._base_url or getattr(type(self), "base_url", None)
        if value is None:
            raise NotImplementedError(f"{type(self).__name__} must define `base_url` or pass it to the constructor")
        return value

    @base_url.setter
    def base_url(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("base_url must be a string")
        self._base_url = value

