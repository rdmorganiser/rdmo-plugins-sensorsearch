from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from dataclasses import dataclass
from typing import Any

from rdmo_sensorsearch.contracts import (
    DeviceDetailSettings,
    HandlerExecutionContext,
    HandlerFailure,
    HandlerResult,
    RefreshNotice,
)
from rdmo_sensorsearch.services.device_details import DeviceBlockPlan, parse_external_id
from rdmo_sensorsearch.services.performance import measure_phase

logger = logging.getLogger(__name__)

DEFAULT_DEVICE_FETCH_WORKERS = 4


@dataclass(frozen=True)
class DeviceFetchResult:
    mapped_values: dict[str, Any]
    scoped_scalar_values: dict[str, Any]
    notices: tuple[RefreshNotice, ...] = ()


@dataclass(frozen=True)
class DeviceFetchError:
    external_id: str
    message: str


@dataclass(frozen=True)
class DeviceFetchBatchResult:
    payloads: dict[str, DeviceFetchResult]
    errors: tuple[DeviceFetchError, ...] = ()


PayloadEnricher = Callable[[dict[str, Any], DeviceBlockPlan], tuple[RefreshNotice, ...] | None]


@measure_phase("device.fetch_batch")
def fetch_device_metadata_batch(
    plans: Sequence[DeviceBlockPlan],
    *,
    device_detail_settings: DeviceDetailSettings,
    scoped_attribute_uris: tuple[str, ...],
    auth_token: str | None = None,
    enrich_payload: PayloadEnricher | None = None,
    max_workers: int = DEFAULT_DEVICE_FETCH_WORKERS,
) -> DeviceFetchBatchResult:
    """Fetch independent device payloads concurrently without Django access."""

    refresh_plans = [plan for plan in plans if plan.needs_refresh]
    if not refresh_plans:
        return DeviceFetchBatchResult(payloads={})
    if max_workers < 1:
        raise ValueError("max_workers must be greater than zero")

    worker_count = min(max_workers, len(refresh_plans))
    payloads = {}
    errors = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_plan = {
            executor.submit(
                copy_context().run,
                _fetch_device_metadata,
                plan,
                device_detail_settings,
                scoped_attribute_uris,
                auth_token,
                enrich_payload,
            ): plan
            for plan in refresh_plans
        }

        for future in as_completed(future_to_plan):
            plan = future_to_plan[future]
            try:
                result = future.result()
            except Exception as error:
                message = str(error) or error.__class__.__name__
                logger.exception("Failed to fetch device detail payload for %s", plan.device.external_id)
                errors.append(DeviceFetchError(external_id=plan.block_key, message=message))
                continue

            if isinstance(result, DeviceFetchError):
                errors.append(result)
            else:
                payloads[plan.block_key] = result

    return DeviceFetchBatchResult(payloads=payloads, errors=tuple(errors))


def _fetch_device_metadata(
    plan: DeviceBlockPlan,
    device_detail_settings: DeviceDetailSettings,
    scoped_attribute_uris: tuple[str, ...],
    auth_token: str | None,
    enrich_payload: PayloadEnricher | None,
) -> DeviceFetchResult | DeviceFetchError:
    device_id = parse_external_id(plan.device.external_id)[1]
    if device_id is None:
        return DeviceFetchError(
            external_id=plan.block_key,
            message="Could not parse external device ID.",
        )

    # Bulk mounting belongs to the injected enricher; no direct mount lookup.
    context = HandlerExecutionContext(device_detail_settings=device_detail_settings)
    handler = plan.handler_binding.handler
    if getattr(handler, "uses_auth_token", False):
        handler_result = handler.handle(
            backend_id=device_id,
            context=context,
            auth_token=auth_token,
        )
    else:
        handler_result = handler.handle(backend_id=device_id, context=context)

    if isinstance(handler_result, HandlerFailure):
        logger.error("Device handler returned errors for %s: %s", plan.device.external_id, handler_result.errors)
        return DeviceFetchError(
            external_id=plan.block_key,
            message="; ".join(handler_result.errors),
        )
    if not isinstance(handler_result, HandlerResult):
        logger.warning(
            "Sensor handler returned unexpected payload for %s: %s",
            plan.device.external_id,
            type(handler_result).__name__,
        )
        return DeviceFetchError(
            external_id=plan.block_key,
            message=f"Device handler returned unexpected payload type: {type(handler_result).__name__}.",
        )
    if handler_result.collections or handler_result.effects:
        return DeviceFetchError(
            external_id=plan.block_key,
            message="Sensor handlers cannot return collections or effects during block sync.",
        )

    mapped_values = dict(handler_result.mapped_values)
    notices = list(handler_result.notices)
    if enrich_payload is not None:
        notices.extend(enrich_payload(mapped_values, plan) or ())
    scoped_scalar_values = {attribute_uri: mapped_values.pop(attribute_uri, "") for attribute_uri in scoped_attribute_uris}
    return DeviceFetchResult(
        mapped_values=mapped_values,
        scoped_scalar_values=scoped_scalar_values,
        notices=tuple(notices),
    )
