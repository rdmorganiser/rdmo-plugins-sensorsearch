"""O2A item enrichment and search, independent of catalog mappings."""

from urllib.parse import quote, urlsplit

from rdmo_sensorsearch.config_models.backend_settings import O2ABackendSettings
from rdmo_sensorsearch.contracts import BackendFailure, BackendResult, BackendSuccess, DeviceMetadata, SearchRecord
from rdmo_sensorsearch.transport import JSONFetcher, request_json


class O2AItemAPI:
    def __init__(self, base_url: str, settings: O2ABackendSettings, fetch: JSONFetcher):
        self.base_url = settings.api_url.format(base_url=base_url)
        self.search_url = settings.item_search_url.format(base_url=base_url)
        self.settings = settings.item
        self.fetch = fetch

    def get_device(self, device_id: str) -> BackendResult[DeviceMetadata]:
        responses = {}
        errors = []
        for endpoint, template in (
            ("item", self.settings.item_url),
            ("contacts", self.settings.contacts_url),
            ("parameters", self.settings.parameters_url),
            ("units", self.settings.units_url),
        ):
            response = request_json(self.fetch, template.format(base_url=self.base_url, id=device_id), None)
            if isinstance(response, BackendFailure):
                errors.extend(f"O2A {endpoint} request for item {device_id} failed: {error}" for error in response.errors)
                continue
            payload = response.value
            if not isinstance(payload, dict):
                errors.append(f"Unexpected O2A {endpoint} payload for item {device_id}: {type(payload).__name__}")
            elif endpoint == "item" and not payload:
                errors.append(f"O2A item request for item {device_id} returned no data.")
            elif endpoint != "item" and (
                not isinstance(payload.get("records", []), list)
                or any(not isinstance(record, dict) for record in payload.get("records", []))
            ):
                errors.append(f"Malformed O2A {endpoint} records for item {device_id}.")
            else:
                responses[endpoint] = payload
        if errors:
            return BackendFailure(tuple(errors))

        data = responses["item"]
        data["contacts"] = [
            {key: contact[key] for key in ("firstName", "lastName", "email") if key in contact}
            for record in responses["contacts"].get("records", [])
            if isinstance(contact := record.get("contact"), dict) and contact
        ]
        unit_records = responses["units"].get("records", [])
        if any(isinstance(unit.get("@uuid"), (list, dict)) for unit in unit_records):
            return BackendFailure((f"Malformed O2A unit identifier for item {device_id}.",))
        units = {unit["@uuid"]: unit.get("code") for unit in unit_records if "@uuid" in unit}
        if any(isinstance(parameter.get("unit"), list) for parameter in responses["parameters"].get("records", [])):
            return BackendFailure((f"Malformed O2A parameter unit for item {device_id}.",))
        data["parameters"] = [
            {
                "name": parameter.get("name", ""),
                "unit": parameter["unit"].get("code", "")
                if isinstance(parameter.get("unit"), dict)
                else units.get(parameter.get("unit"), ""),
            }
            for parameter in responses["parameters"].get("records", [])
        ]
        origin = urlsplit(self.base_url)
        values = {"base_url": self.base_url, "base_url_origin": f"{origin.scheme}://{origin.netloc}", "id": device_id}
        if not isinstance(data.get("links", {}), dict):
            return BackendFailure((f"Malformed O2A item links for item {device_id}.",))
        links = data.setdefault("links", {})
        links["api"] = self.settings.item_api_link_template.format(**values)
        links["frontend"] = self.settings.item_frontend_link_template.format(**values)
        return BackendSuccess(DeviceMetadata(data, frontend_link=links["frontend"]))

    def search_devices(self, query: str, limit: int) -> BackendResult[tuple[SearchRecord, ...]]:
        query = "".join(character for character in query if character.isalnum() or character.isspace())
        expression = f"(title:({query}*)^2 OR id:(/{query}/)^20 OR ({query}*)^0) AND (states.itemState:(public devicestore)^0)"
        response = request_json(self.fetch, f"{self.search_url}?hits={limit}&q={quote(expression)}", None)
        if isinstance(response, BackendFailure):
            return response
        payload = response.value
        if not isinstance(payload, dict) or not isinstance(payload.get("records", []), list):
            return BackendFailure(("Unexpected O2A item search payload.",))
        records = []
        for record in payload.get("records", [])[:limit]:
            if not isinstance(record, dict) or any(record.get(key) is None for key in ("uniqueId", "id", "title")):
                return BackendFailure(("Malformed O2A item search record.",))
            metadata = record.get("metadata") or {}
            if not isinstance(metadata, dict):
                return BackendFailure(("Malformed O2A item search metadata.",))
            records.append(
                SearchRecord(
                    str(record["uniqueId"]),
                    {"title": record["title"], "registry_id": record["id"], "serial": metadata.get("serial")},
                )
            )
        return BackendSuccess(tuple(records))
