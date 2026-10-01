from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urljoin

from rdmo_sensorsearch.contracts import BackendFailure, BackendResult, BackendSuccess

JSONFetcher = Callable[[str], BackendResult[object]]


def fetch_paginated_jsonapi_collection(
    *,
    url_template: str,
    base_url: str,
    object_id: str,
    page_size: int,
    max_pages: int,
    fetch_page: JSONFetcher,
    error_label: str = "JSON:API",
    next_link_base_url: str | None = None,
) -> BackendResult[dict]:
    """Fetch and combine a bounded JSON:API collection."""

    data: list[dict] = []
    included: dict[tuple[str | None, str | None], dict] = {}
    seen_pages: set[tuple[tuple[str | None, str | None], ...]] = set()
    page_number = 1
    pages_fetched = 0
    next_url = url_template.format(
        base_url=base_url,
        id=object_id,
        page_size=page_size,
        page_number=page_number,
    )

    while next_url and pages_fetched < max_pages:
        pages_fetched += 1
        response = fetch_page(next_url)
        if isinstance(response, BackendFailure):
            return response
        payload = response.value
        if not isinstance(payload, dict):
            return BackendFailure((f"Unexpected {error_label} collection payload: {type(payload).__name__}",))

        page_data = payload.get("data", [])
        if not isinstance(page_data, list):
            return BackendFailure((f"Unexpected {error_label} collection data: {type(page_data).__name__}",))

        signature = tuple((item.get("type"), item.get("id")) for item in page_data)
        if page_data and signature in seen_pages:
            return BackendFailure((f"{error_label} collection pagination returned the same page more than once.",))
        seen_pages.add(signature)
        data.extend(page_data)

        page_included = payload.get("included", [])
        if not isinstance(page_included, list):
            return BackendFailure((f"Unexpected {error_label} included data: {type(page_included).__name__}",))
        for item in page_included:
            included[(item.get("type"), item.get("id"))] = item

        links = payload.get("links", {})
        raw_next = links.get("next") if isinstance(links, dict) else None
        if isinstance(raw_next, dict):
            raw_next = raw_next.get("href")
        if isinstance(raw_next, str) and raw_next:
            next_url = urljoin(next_link_base_url or base_url, raw_next)
        elif len(page_data) >= page_size:
            page_number = pages_fetched + 1
            next_url = url_template.format(
                base_url=base_url,
                id=object_id,
                page_size=page_size,
                page_number=page_number,
            )
        else:
            next_url = None

    if next_url:
        return BackendFailure((f"{error_label} collection pagination exceeded {max_pages} pages.",))
    return BackendSuccess({"data": data, "included": list(included.values())})
