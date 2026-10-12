from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from django.db.models import Q

from rdmo.projects.models import Value

from rdmo_sensorsearch.contracts import SelectedDevice
from rdmo_sensorsearch.naming import device_detail_tab_label
from rdmo_sensorsearch.persistence.catalog_context import get_catalog_context
from rdmo_sensorsearch.services.device_details import (
    DeviceBlockPlan,
    DeviceBlockReference,
    base_device_text,
    configuration_key_from_device_block,
    parse_device_block_key,
)
from rdmo_sensorsearch.services.device_metadata import DeviceFetchResult
from rdmo_sensorsearch.services.performance import measure_phase

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _DeviceBlockValueContext:
    """Value scope used only by the shared RDMO reconciliation writer."""

    project: Any
    set_prefix: str
    set_index: int
    attribute_id: int


@dataclass(frozen=True)
class DevicePlanningState:
    """Detached read snapshot; never reuse after applying a reconciliation plan."""

    root_uri: str
    scope_prefix: str
    blocks: dict[str, DeviceBlockReference]
    next_index: int
    rows: dict[tuple[str, str, int, bool], set[tuple[str, str]]]

    def existing_blocks(self, configuration_key: str) -> dict[str, DeviceBlockReference]:
        return {key: block for key, block in self.blocks.items() if parse_device_block_key(key)[0] == configuration_key}

    def block_metadata_is_current(self, device, block_key, set_index, handler_binding, configuration_label) -> bool:
        return (_device_root_text(configuration_label, device), block_key) in self.rows.get(
            (self.root_uri, self.scope_prefix, set_index, True), ()
        ) and (base_device_text(device.text), device.external_id) in self.rows.get(
            (handler_binding.search_attribute_uri, self.scope_prefix, set_index, False), ()
        )

    def block_needs_refresh(
        self, set_index, *, device_link_attribute_uri, usage_technology_attribute_uri, instrument_start_attribute_uri
    ) -> bool:
        scopes = (
            (device_link_attribute_uri, self.scope_prefix, set_index, False),
            (usage_technology_attribute_uri, self.scope_prefix, set_index, False),
            (instrument_start_attribute_uri, str(set_index), 0, False),
        )
        return not all(any(text for text, _ in self.rows.get(scope, ())) for scope in scopes)


class RDMODeviceDetailStore:
    """Persistence adapter for one project's materialized device blocks."""

    def __init__(
        self,
        project: Any,
        root_attribute: Any,
        scope_prefix: str = "",
        *,
        value_model: Any = Value,
    ):
        self.project = project
        self.root_attribute = root_attribute
        self.scope_prefix = scope_prefix or ""
        self.value_model = value_model

    @measure_phase("device.load_state")
    def load_planning_state(self, attribute_uris: Iterable[str]) -> DevicePlanningState:
        roots = list(
            self.value_model.objects.filter(
                project=self.project,
                snapshot=None,
                attribute=self.root_attribute,
                set_collection=True,
                set_prefix=self.scope_prefix,
            )
            .order_by("set_index", "id")
            .values_list("set_index", "text", "external_id")
        )
        rows = defaultdict(set)
        blocks = {}
        for set_index, text, external_id in roots:
            rows[(self.root_attribute.uri, self.scope_prefix, set_index, True)].add((text, external_id))
            configuration_key, device_id = parse_device_block_key(external_id or "")
            if configuration_key and device_id:
                blocks[external_id] = DeviceBlockReference(set_index=set_index)

        indexes = {index for index, _, _ in roots}
        if indexes:
            # Resolve URI identity in the same query as the required scalar state.
            scalars = (
                self.value_model.objects.filter(
                    project=self.project,
                    snapshot=None,
                    attribute__uri__in=set(attribute_uris),
                    set_collection=False,
                )
                .filter(
                    Q(set_prefix=self.scope_prefix, set_index__in=indexes)
                    | Q(set_prefix__in={str(index) for index in indexes}, set_index=0)
                )
                .order_by()
                .values_list("attribute__uri", "set_prefix", "set_index", "text", "external_id")
            )
            for uri, prefix, index, text, external_id in scalars:
                rows[(uri, prefix, index, False)].add((text, external_id))
        return DevicePlanningState(
            self.root_attribute.uri,
            self.scope_prefix,
            blocks,
            max(indexes, default=-1) + 1,
            dict(rows),
        )

    def for_scope(self, scope_prefix: str) -> RDMODeviceDetailStore:
        return type(self)(
            project=self.project,
            root_attribute=self.root_attribute,
            scope_prefix=scope_prefix,
            value_model=self.value_model,
        )

    def existing_blocks(self, configuration_key: str) -> dict[str, DeviceBlockReference]:
        return {
            block_key: block
            for block_key, block in self.all_existing_blocks().items()
            if parse_device_block_key(block_key)[0] == configuration_key
        }

    def find_block(self, block_key: str) -> DeviceBlockReference | None:
        value = (
            self.value_model.objects.filter(
                project=self.project,
                snapshot=None,
                attribute=self.root_attribute,
                set_collection=True,
                set_prefix=self.scope_prefix,
                external_id=block_key,
            )
            .order_by("id")
            .first()
        )
        return None if value is None else DeviceBlockReference(set_index=value.set_index)

    def all_existing_blocks(self) -> dict[str, DeviceBlockReference]:
        blocks = {}
        queryset = (
            self.value_model.objects.filter(
                project=self.project,
                snapshot=None,
                attribute=self.root_attribute,
                set_collection=True,
                set_prefix=self.scope_prefix,
            )
            .exclude(external_id__isnull=True)
            .exclude(external_id__exact="")
            .order_by("set_index", "id")
        )
        for value in queryset:
            block_key = value.external_id or ""
            configuration_key, device_external_id = parse_device_block_key(block_key)
            if configuration_key and device_external_id:
                blocks[block_key] = DeviceBlockReference(set_index=value.set_index)
        return blocks

    def next_set_index(self) -> int:
        existing_indexes = list(
            self.value_model.objects.filter(
                project=self.project,
                snapshot=None,
                attribute=self.root_attribute,
                set_collection=True,
                set_prefix=self.scope_prefix,
            ).values_list("set_index", flat=True)
        )
        return max(existing_indexes) + 1 if existing_indexes else 0

    def block_metadata_is_current(
        self,
        device: SelectedDevice,
        block_key: str,
        set_index: int,
        handler_binding: Any,
        configuration_label: str,
    ) -> bool:
        return self.has_matching_value(
            attribute=self.root_attribute,
            set_index=set_index,
            set_collection=True,
            text=_device_root_text(configuration_label, device),
            external_id=block_key,
        ) and self.has_matching_value(
            attribute_uri=handler_binding.search_attribute_uri,
            set_index=set_index,
            set_collection=False,
            text=base_device_text(device.text),
            external_id=device.external_id,
        )

    def block_needs_refresh(
        self,
        set_index: int,
        *,
        device_link_attribute_uri: str,
        usage_technology_attribute_uri: str,
        instrument_start_attribute_uri: str,
    ) -> bool:
        return not (
            self.has_nonempty_scalar_value(device_link_attribute_uri, set_index=set_index)
            and self.has_nonempty_scalar_value(usage_technology_attribute_uri, set_index=set_index)
            and self.has_nonempty_scalar_value(
                instrument_start_attribute_uri,
                set_prefix=str(set_index),
                set_index=0,
            )
        )

    def has_matching_value(
        self,
        *,
        set_index: int,
        set_collection: bool,
        attribute: Any = None,
        attribute_uri: str | None = None,
        text: str | None = None,
        external_id: str | None = None,
    ) -> bool:
        queryset = self.value_model.objects.filter(
            project=self.project,
            snapshot=None,
            set_prefix=self.scope_prefix,
            set_index=set_index,
            set_collection=set_collection,
        )
        if attribute is not None:
            queryset = queryset.filter(attribute=attribute)
        elif attribute_uri:
            queryset = queryset.filter(attribute__uri=attribute_uri)
        else:
            return False
        if text is not None:
            queryset = queryset.filter(text=text)
        if external_id is not None:
            queryset = queryset.filter(external_id=external_id)
        return queryset.exists()

    def has_nonempty_scalar_value(
        self,
        attribute_uri: str,
        *,
        set_index: int,
        set_prefix: str | None = None,
    ) -> bool:
        return (
            self.value_model.objects.filter(
                project=self.project,
                snapshot=None,
                attribute__uri=attribute_uri,
                set_prefix=self.scope_prefix if set_prefix is None else set_prefix,
                set_index=set_index,
                set_collection=False,
            )
            .exclude(text__isnull=True)
            .exclude(text__exact="")
            .exists()
        )

    def upsert_block_identity(self, plan: DeviceBlockPlan, configuration_label: str) -> None:
        from rdmo_sensorsearch.persistence.value_reconciliation import format_change_label, upsert_value_if_changed

        _, created, changed = upsert_value_if_changed(
            {
                "project": self.project,
                "attribute": self.root_attribute,
                "snapshot": None,
                "set_collection": True,
                "set_prefix": self.scope_prefix,
                "set_index": plan.set_index,
            },
            {
                "text": _device_root_text(configuration_label, plan.device),
                "external_id": plan.block_key,
            },
        )
        logger.info(
            "%s device block root for %s at set_prefix=%s set_index=%s",
            format_change_label(created, changed),
            plan.block_key,
            self.scope_prefix,
            plan.set_index,
        )

        search_attribute = get_attribute_by_uri(plan.handler_binding.search_attribute_uri)
        if search_attribute is None:
            logger.warning("Search attribute not found: %s", plan.handler_binding.search_attribute_uri)
            return
        _, created, changed = upsert_value_if_changed(
            {
                "project": self.project,
                "attribute": search_attribute,
                "snapshot": None,
                "set_collection": False,
                "set_prefix": self.scope_prefix,
                "set_index": plan.set_index,
            },
            {
                "text": base_device_text(plan.device.text),
                "external_id": plan.device.external_id,
            },
        )
        logger.info(
            "%s device search value for %s at set_prefix=%s set_index=%s",
            format_change_label(created, changed),
            plan.device.external_id,
            self.scope_prefix,
            plan.set_index,
        )

    def write_fetch_payload(
        self,
        plan: DeviceBlockPlan,
        fetched_payload: DeviceFetchResult,
        *,
        excluded_attribute_uris: set[str],
    ) -> None:
        from rdmo_sensorsearch.persistence.value_reconciliation import (
            reconcile_mapped_values,
            replace_scalar_value_in_scopes,
        )

        instance = self.block_instance(plan.set_index)
        reconcile_mapped_values(
            instance,
            plan.handler_binding.handler,
            fetched_payload.mapped_values,
            excluded_attribute_uris=excluded_attribute_uris,
        )
        for attribute_uri, value in fetched_payload.scoped_scalar_values.items():
            replace_scalar_value_in_scopes(
                instance,
                attribute_uri,
                value,
                scopes_to_set=[(str(plan.set_index), 0)],
                scopes_to_clear=[(self.scope_prefix, plan.set_index)],
            )

    def block_instance(self, set_index: int) -> _DeviceBlockValueContext:
        return _DeviceBlockValueContext(
            project=self.project,
            set_prefix=self.scope_prefix,
            set_index=set_index,
            attribute_id=self.root_attribute.id,
        )

    def delete_block(self, set_index: int, attribute_ids: set[int]) -> int:
        value_ids = list(
            self.value_model.objects.filter(
                project=self.project,
                snapshot=None,
                attribute_id__in=attribute_ids,
            )
            .filter(Q(set_prefix=self.scope_prefix, set_index=set_index) | Q(set_prefix=str(set_index)))
            .order_by("id")
            .values_list("id", flat=True)
            .distinct()
        )
        if not value_ids:
            return 0

        deleted, _ = self.value_model.objects.filter(
            project=self.project,
            snapshot=None,
            id__in=value_ids,
        ).delete()
        if deleted:
            logger.info(
                "Deleted device detail block at set_prefix=%s set_index=%s (%s rows, ids=%s)",
                self.scope_prefix,
                set_index,
                deleted,
                value_ids,
            )
        return deleted

    def orphaned_scopes(self, configuration_search_attribute_uris: Iterable[str]) -> set[tuple[str, int]]:
        active_configuration_keys = {
            value.external_id or value.text
            for value in self.value_model.objects.filter(
                project=self.project,
                snapshot=None,
                attribute__uri__in=configuration_search_attribute_uris,
            )
            if value.external_id or value.text
        }
        root_values = (
            self.value_model.objects.filter(
                project=self.project,
                snapshot=None,
                attribute=self.root_attribute,
                set_collection=True,
            )
            .exclude(external_id__isnull=True)
            .exclude(external_id__exact="")
        )
        orphaned_scopes = set()
        for value in root_values:
            configuration_key = configuration_key_from_device_block(value.external_id)
            if configuration_key and configuration_key not in active_configuration_keys:
                orphaned_scopes.add((value.set_prefix or "", value.set_index))
        return orphaned_scopes

    @measure_phase("device.compact")
    def compact(self, attribute_ids: set[int]) -> None:
        root_values = list(
            self.value_model.objects.filter(
                project=self.project,
                snapshot=None,
                attribute=self.root_attribute,
                set_collection=True,
                set_prefix=self.scope_prefix,
            ).order_by("set_index", "id")
        )
        current_indices = [value.set_index for value in root_values]
        if current_indices == list(range(len(root_values))) or not attribute_ids:
            return

        remap = {old: new for new, old in enumerate(current_indices)}
        temporary_offset = max(current_indices, default=-1) + 1000
        for old_index in current_indices:
            temporary_index = old_index + temporary_offset
            self.value_model.objects.filter(
                project=self.project,
                snapshot=None,
                attribute_id__in=attribute_ids,
                set_prefix=self.scope_prefix,
                set_index=old_index,
            ).update(set_index=temporary_index)
            self.value_model.objects.filter(
                project=self.project,
                snapshot=None,
                attribute_id__in=attribute_ids,
                set_prefix=str(old_index),
            ).update(set_prefix=str(temporary_index))

        for old_index, new_index in remap.items():
            temporary_index = old_index + temporary_offset
            self.value_model.objects.filter(
                project=self.project,
                snapshot=None,
                attribute_id__in=attribute_ids,
                set_prefix=self.scope_prefix,
                set_index=temporary_index,
            ).update(set_index=new_index)
            self.value_model.objects.filter(
                project=self.project,
                snapshot=None,
                attribute_id__in=attribute_ids,
                set_prefix=str(temporary_index),
            ).update(set_prefix=str(new_index))


def get_attribute_by_uri(attribute_uri: str):
    from rdmo.domain.models import Attribute

    try:
        return Attribute.objects.get(uri=attribute_uri)
    except Attribute.DoesNotExist:
        return None


def catalog_attribute_ids(catalog: Any, page_uris: set[str]) -> set[int]:
    context = get_catalog_context()
    key = catalog.pk if hasattr(catalog, "pk") else id(catalog)
    if context is not None and key in context.page_attributes:
        pages = context.page_attributes[key]
        return set().union(*(pages.get(uri, frozenset()) for uri in page_uris))
    catalog.prefetch_elements()
    pages = defaultdict(set)
    for page in catalog.pages:
        pages[page.uri].update(_collect_attribute_ids(page))
    if context is not None:
        context.page_attributes[key] = {uri: frozenset(ids) for uri, ids in pages.items()}
    return set().union(*(pages.get(uri, set()) for uri in page_uris))


def _collect_attribute_ids(element: Any) -> set[int]:
    attribute_ids = set()
    attribute_id = getattr(element, "attribute_id", None)
    if attribute_id:
        attribute_ids.add(attribute_id)
    for child in getattr(element, "elements", []):
        attribute_ids.update(_collect_attribute_ids(child))
    return attribute_ids


def _device_root_text(configuration_label: str, device: SelectedDevice) -> str:
    return device_detail_tab_label(
        configuration_label,
        device.text or device.external_id,
        device.external_id,
    )
