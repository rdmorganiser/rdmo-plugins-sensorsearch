from rdmo_sensorsearch.handlers.jsonapi import (
    fetch_paginated_jsonapi_collection,
)

URL_TEMPLATE = "https://sms.example/backend/api/v1/items/{id}?page[size]={page_size}&page[number]={page_number}"


def test_jsonapi_pagination_follows_next_link_against_explicit_origin():
    requested_urls = []

    def fetch_page(url):
        requested_urls.append(url)
        if len(requested_urls) == 1:
            return {
                "data": [{"type": "item", "id": "1"}],
                "included": [],
                "links": {"next": {"href": "/backend/api/v1/items/49?page[number]=2"}},
            }
        return {"data": [], "included": []}

    result = fetch_paginated_jsonapi_collection(
        url_template=URL_TEMPLATE,
        base_url="https://sms.example/backend/api/v1",
        next_link_base_url="https://sms.example",
        object_id="49",
        page_size=100,
        max_pages=10,
        fetch_page=fetch_page,
    )

    assert [item["id"] for item in result["data"]] == ["1"]
    assert requested_urls[1] == "https://sms.example/backend/api/v1/items/49?page[number]=2"


def test_jsonapi_pagination_stops_repeated_pages():
    repeated_page = {"data": [{"type": "item", "id": "1"}], "included": []}

    result = fetch_paginated_jsonapi_collection(
        url_template=URL_TEMPLATE,
        base_url="https://sms.example/backend/api/v1",
        object_id="49",
        page_size=1,
        max_pages=10,
        fetch_page=lambda _url: repeated_page,
        error_label="SMS",
    )

    assert result == {"errors": ["SMS collection pagination returned the same page more than once."]}
