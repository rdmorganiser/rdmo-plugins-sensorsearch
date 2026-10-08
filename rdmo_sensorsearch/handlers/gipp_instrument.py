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


class GIPPInstrumentHandler(BackendRecordHandler):
    """Map GIPP metadata into catalog attributes."""

    def __init__(self, *, backend: DeviceMetadataSource, id_prefix: str, base_url: str, attribute_mapping: Mapping[str, str]):
        super().__init__(id_prefix=id_prefix, base_url=base_url, attribute_mapping=attribute_mapping)
        self.backend = backend

    def handle(self, backend_id: str, *, context: HandlerExecutionContext, auth_token: str | None = None) -> HandlerOutcome:
        response = self.backend.get_device(backend_id, auth_token=auth_token)
        if isinstance(response, BackendFailure):
            return HandlerFailure(response.errors)
        return HandlerResult(
            mapped_values=evaluate_jmespath_mapping(self.attribute_mapping, response.value.document), notices=response.notices
        )
