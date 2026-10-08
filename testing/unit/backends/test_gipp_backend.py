from rdmo_sensorsearch.backends.gipp.backend import GIPPBackend
from rdmo_sensorsearch.config_models.backend_settings import GIPPBackendSettings
from rdmo_sensorsearch.contracts import BackendFailure, BackendSuccess, SearchRecord
from testing.transport_helpers import raising_fetch


def test_gipp_search_matches_all_fields_skips_malformed_entries_and_limits_results():
    calls = []

    def fetch(url, auth_token=None):
        calls.append((url, auth_token))
        return [
            None,
            {"Instrument": None},
            {"Instrument": {"id": 1}},
            {"Instrument": {"id": 2, "code": "Probe", "program": "MOSES"}},
            {"Instrument": {"id": 3, "code": "Probe2", "program": "MOSES"}},
        ]

    backend = GIPPBackend(base_url="https://gipp.gfz.de/instruments", settings=GIPPBackendSettings(), fetch=raising_fetch(fetch))
    assert backend.search_devices("moses", limit=1, auth_token="secret") == BackendSuccess(
        (SearchRecord("2", {"id": 2, "code": "Probe", "program": "MOSES"}),)
    )
    assert calls == [("https://gipp.gfz.de/instruments/index.json?limit=10000&program=MOSES", None)]


def test_gipp_metadata_preserves_mapping_document_and_ownership():
    calls = []
    payload = {
        "Instrument": {"code": "Probe", "serialNo": "ABC"},
        "Instrumentcategory": {"manufacturer": "Institute"},
        "Person": {"surname": "Doe", "givenname": "Ada"},
    }

    def fetch(url, auth_token=None):
        calls.append((url, auth_token))
        return payload

    backend = GIPPBackend(base_url="https://gipp.gfz.de/instruments", settings=GIPPBackendSettings(), fetch=raising_fetch(fetch))
    result = backend.get_device("1", auth_token="secret")
    assert result.value.document == payload
    result.value.document["Instrument"]["code"] = "Changed"
    assert payload["Instrument"]["code"] == "Probe"
    assert calls == [("https://gipp.gfz.de/instruments/rest/1.json", None)]


def test_gipp_malformed_search_is_a_failure():
    backend = GIPPBackend(
        base_url="https://gipp.example", settings=GIPPBackendSettings(), fetch=raising_fetch(lambda *args, **kwargs: {})
    )
    assert backend.search_devices("probe", limit=1) == BackendFailure(("Unexpected GIPP instruments payload.",))
