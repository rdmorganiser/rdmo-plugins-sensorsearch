from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from dataclasses import dataclass
from typing import Any

from rdmo_sensorsearch.handlers.base import HandlerResult
from rdmo_sensorsearch.services.device_details import DeviceBlockPlan, parse_external_id

logger = logging.getLogger(__name__)

DEFAULT_DEVICE_FETCH_WORKERS = 4


@dataclass(frozen=True)
class DeviceBlockInstance:
    """Minimal RDMO-like context passed to a device handler."""

    project: Any
    set_prefix: str
    set_index: int
    attribute_id: int


@dataclass(frozen=True)
class DeviceFetchResult:
    mapped_values: dict[str, Any]
    scoped_scalar_values: dict[str, Any]


@dataclass(frozen=True)
class DeviceFetchError:
    external_id: str
    message: str


@dataclass(frozen=True)
class DeviceFetchBatchResult:
    payloads: dict[str, DeviceFetchResult]
    errors: tuple[DeviceFetchError, ...] = ()


PayloadEnricher = Callable[[dict[str, Any], DeviceBlockPlan], None]


def fetch_device_metadata_batch(
    plans: Sequence[DeviceBlockPlan],
    *,
    root_attribute_id: int,
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
                root_attribute_id,
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
    root_attribute_id: int,
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

    instance = DeviceBlockInstance(
        project=None,
        set_prefix="",
        set_index=plan.set_index,
        attribute_id=root_attribute_id,
    )
    handler = plan.handler_binding.handler
    if getattr(handler, "uses_auth_token", False):
        handler_result = handler.handle(
            backend_id=device_id,
            instance=instance,
            auth_token=auth_token,
        )
    else:
        handler_result = handler.handle(backend_id=device_id, instance=instance)

    if isinstance(handler_result, dict) and "errors" in handler_result:
        logger.error("Device handler returned errors for %s: %s", plan.device.external_id, handler_result["errors"])
        return DeviceFetchError(
            external_id=plan.block_key,
            message=_format_handler_errors(handler_result["errors"]),
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
    if handler_result.collections or handler_result.post_actions:
        return DeviceFetchError(
            external_id=plan.block_key,
            message="Sensor handlers cannot return collections or post-actions during block sync.",
        )

    mapped_values = dict(handler_result.mapped_values)
    if enrich_payload is not None:
        enrich_payload(mapped_values, plan)
    scoped_scalar_values = {attribute_uri: mapped_values.pop(attribute_uri, "") for attribute_uri in scoped_attribute_uris}
    return DeviceFetchResult(
        mapped_values=mapped_values,
        scoped_scalar_values=scoped_scalar_values,
    )


def _format_handler_errors(errors: Any) -> str:
    if isinstance(errors, list):
        return "; ".join(str(error) for error in errors)
    return str(errors)
