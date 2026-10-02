from types import SimpleNamespace

from django.utils import timezone

from rdmo.domain.models import Attribute
from rdmo.projects.models import Project, Value
from rdmo.questions.models import Catalog, Page, Question, Section

from rdmo_sensorsearch.contracts import SelectedDevice
from rdmo_sensorsearch.naming import device_detail_tab_label
from rdmo_sensorsearch.persistence.data_collection_variables import (
    DataCollectionVariableAttributes,
    RDMODataCollectionVariableStore,
)
from rdmo_sensorsearch.persistence.device_details import RDMODeviceDetailStore


def make_workload(count, *, prefix=""):
    attributes = {
        name: Attribute.objects.create(uri_prefix="https://performance.example", key=name)
        for name in ("root", "search", "link", "usage", "start", "end", "name", "unit", "variable", "variable-unit", "selected")
    }
    catalog = Catalog.objects.create(uri_prefix="https://performance.example", uri_path="catalog")
    section = Section.objects.create(uri_prefix="https://performance.example", uri_path="section")
    page = Page.objects.create(
        uri_prefix="https://performance.example",
        uri_path="page",
        is_collection=True,
        attribute=attributes["root"],
    )
    catalog.sections.add(section)
    section.pages.add(page)
    for name in ("search", "link", "usage"):
        question = Question.objects.create(
            uri_prefix="https://performance.example",
            uri_path=name,
            attribute=attributes[name],
        )
        page.questions.add(question)
    project = Project.objects.create(title="Performance fixture", catalog=catalog)
    devices = tuple(SelectedDevice(text=f"Sensor {i}", external_id=f"sms:{i}") for i in range(count))
    rows = []
    for index, device in enumerate(devices):
        common = {"set_prefix": prefix, "set_index": index}
        rows.extend(
            [
                dict(
                    attribute=attributes["root"],
                    set_collection=True,
                    external_id=f"cfg:1||{device.external_id}",
                    text=device_detail_tab_label("Configuration", device.text, device.external_id),
                    **common,
                ),
                dict(attribute=attributes["search"], external_id=device.external_id, text=device.text, **common),
                dict(attribute=attributes["link"], text="https://example.test/device", **common),
                dict(attribute=attributes["usage"], text="instrument", **common),
                {"attribute": attributes["start"], "text": "2026-01-01", "set_prefix": str(index), "set_index": 0},
                {
                    "attribute": attributes["name"],
                    "text": f"Parameter {index}",
                    "set_collection": True,
                    "set_prefix": str(index),
                    "set_index": 0,
                },
                {"attribute": attributes["unit"], "text": "K", "set_collection": True, "set_prefix": str(index), "set_index": 0},
                {
                    "attribute": attributes["selected"],
                    "external_id": device.external_id,
                    "text": device.text,
                    "set_collection": True,
                    "set_prefix": "dataset",
                    "set_index": 0,
                    "collection_index": index,
                },
            ]
        )
    insert_values(project, rows)
    return SimpleNamespace(
        project=project,
        catalog=catalog,
        page=page,
        attributes=attributes,
        devices=devices,
        binding=SimpleNamespace(search_attribute_uri=attributes["search"].uri),
        store=RDMODeviceDetailStore(project, attributes["root"], prefix),
        variables=RDMODataCollectionVariableStore(
            project,
            "dataset",
            0,
            DataCollectionVariableAttributes(
                attributes["root"],
                attributes["name"],
                attributes["unit"],
                attributes["variable"],
                attributes["variable-unit"],
            ),
        ),
    )


def insert_values(project, rows):
    now = timezone.now()
    return Value.objects.bulk_create(
        [Value(project=project, created=now, updated=now, **{"set_collection": False, **row}) for row in rows]
    )
