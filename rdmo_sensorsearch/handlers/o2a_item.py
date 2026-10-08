from collections.abc import Mapping

from rdmo_sensorsearch.contracts import (
    BackendFailure,
    DeviceMetadataSource,
    HandlerExecutionContext,
    HandlerFailure,
    HandlerOutcome,
    HandlerResult,
)
from rdmo_sensorsearch.handlers.base import BackendRecordHandler
from rdmo_sensorsearch.handlers.parser import evaluate_jmespath_mapping


class O2ARegistryItemHandler(BackendRecordHandler):
    """Map normalized O2A item metadata into the configured catalog."""

    materialize_device_details = True
    device_link_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/device-link"

    def __init__(self, *, backend: DeviceMetadataSource, id_prefix: str, base_url: str, attribute_mapping: Mapping[str, str]):
        super().__init__(id_prefix=id_prefix, base_url=base_url, attribute_mapping=attribute_mapping)
        self.backend = backend

    def handle(self, backend_id: str, *, context: HandlerExecutionContext, auth_token: str | None = None) -> HandlerOutcome:
        response = self.backend.get_device(backend_id, auth_token=auth_token)
        if isinstance(response, BackendFailure):
            return HandlerFailure(response.errors)
        mapped_values = evaluate_jmespath_mapping(self.attribute_mapping, response.value.document)
        uri = getattr(self, "device_link_attribute_uri", None)
        if uri and response.value.frontend_link:
            mapped_values[uri] = response.value.frontend_link
        return HandlerResult(mapped_values=mapped_values, notices=response.notices)
