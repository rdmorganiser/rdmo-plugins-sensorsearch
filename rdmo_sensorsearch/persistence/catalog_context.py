"""Catalog-only memoization with an explicit, nestable workflow lifetime."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class CatalogContext:
    collection_counts: dict = field(default_factory=dict)
    page_attributes: dict = field(default_factory=dict)


_CATALOG_CONTEXT: ContextVar[CatalogContext | None] = ContextVar("sensorsearch_catalog_context", default=None)


def get_catalog_context() -> CatalogContext | None:
    return _CATALOG_CONTEXT.get()


@contextmanager
def workflow_catalog_context():
    if get_catalog_context() is not None:
        yield
        return
    token = _CATALOG_CONTEXT.set(CatalogContext())
    try:
        yield
    finally:
        _CATALOG_CONTEXT.reset(token)
