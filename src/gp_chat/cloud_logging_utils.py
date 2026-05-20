import datetime
import os
import uuid
from typing import Any, Callable


LOG_ID = "run.googleapis.com%2Fstdout"
APP_NAME = "gp-chat"
EVENT_TYPE_AI_USAGE = "ai_usage"
DEFAULT_SERVICE_NAME = "gp-chat"
DEFAULT_REVISION_NAME = "gp-chat-local"
DISABLED_VALUES = {"0", "false", "no", "off"}

_CLIENT_CACHE: dict[str, Any] = {}
_LOGGER_CACHE: dict[tuple[Any, ...], Any] = {}
_IMPORT_ERROR: Exception | None = None


def _emit(logger: Callable[..., Any] | None, message: str, level: str = "info") -> None:
    if logger is None:
        return
    try:
        logger(message, level)
    except TypeError:
        logger(message)


def is_cloud_logging_enabled(env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    value = source.get("GP_CHAT_CLOUD_LOGGING_ENABLED", "true").strip().lower()
    return value not in DISABLED_VALUES


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def build_ai_usage_payload(
    *,
    user_email: str,
    model_name: str,
    current_usage: dict[str, Any],
    task_id: str,
    timestamp: datetime.datetime,
) -> dict[str, Any]:
    return {
        "app_name": APP_NAME,
        "user_email": user_email,
        "timestamp": timestamp.isoformat(),
        "additional_info": {
            "gcs_object_name": "",
        },
        "task_id": task_id,
        "model_name": model_name,
        "token_usage": {
            "response_tokens": _safe_int(current_usage.get("output_tokens")),
            "total_tokens": _safe_int(current_usage.get("total_tokens")),
            "prompt_tokens": _safe_int(current_usage.get("input_tokens")),
        },
        "event_type": EVENT_TYPE_AI_USAGE,
    }


def _load_cloud_logging_modules() -> tuple[Any, Any] | None:
    global _IMPORT_ERROR

    if _IMPORT_ERROR is not None:
        return None

    try:
        from google.cloud import logging as cloud_logging
        from google.cloud.logging_v2.resource import Resource
    except Exception as exc:
        _IMPORT_ERROR = exc
        return None
    return cloud_logging, Resource


def _build_resource(*, project_id: str, location: str) -> Any | None:
    modules = _load_cloud_logging_modules()
    if modules is None:
        return None
    _, Resource = modules

    service_name = os.getenv("GP_CHAT_LOG_SERVICE_NAME", DEFAULT_SERVICE_NAME)
    return Resource(
        type="cloud_run_revision",
        labels={
            "service_name": service_name,
            "location": os.getenv("GP_CHAT_LOG_LOCATION", location),
            "revision_name": os.getenv("GP_CHAT_LOG_REVISION_NAME", DEFAULT_REVISION_NAME),
            "configuration_name": os.getenv("GP_CHAT_LOG_CONFIGURATION_NAME", service_name),
            "project_id": project_id,
        },
    )


def _get_logger(*, project_id: str, location: str) -> tuple[Any, Any] | None:
    modules = _load_cloud_logging_modules()
    if modules is None:
        return None
    cloud_logging, _ = modules

    resource = _build_resource(project_id=project_id, location=location)
    if resource is None:
        return None

    client = _CLIENT_CACHE.get(project_id)
    if client is None:
        client = cloud_logging.Client(project=project_id)
        _CLIENT_CACHE[project_id] = client

    resource_key = tuple(sorted(resource.labels.items()))
    cache_key = (project_id, LOG_ID, resource.type, resource_key)
    logger = _LOGGER_CACHE.get(cache_key)
    if logger is None:
        logger = client.logger(LOG_ID)
        _LOGGER_CACHE[cache_key] = logger

    return logger, resource


def write_ai_usage_log(
    *,
    current_usage: dict[str, Any] | None,
    user_email: str | None,
    model_name: str | None,
    project_id: str | None,
    location: str | None,
    logger: Callable[..., Any] | None = None,
) -> bool:
    if not is_cloud_logging_enabled():
        return False
    if not current_usage:
        return False
    if not project_id:
        _emit(logger, "[Cloud Logging] GCP_PROJECT_ID is not set. Skipping ai_usage log.", "warning")
        return False

    timestamp = utc_now()
    task_id = str(uuid.uuid4())
    payload = build_ai_usage_payload(
        user_email=user_email or "",
        model_name=model_name or "",
        current_usage=current_usage,
        task_id=task_id,
        timestamp=timestamp,
    )

    try:
        logger_and_resource = _get_logger(project_id=project_id, location=location or "global")
        if logger_and_resource is None:
            reason = _IMPORT_ERROR if _IMPORT_ERROR is not None else "unknown import error"
            _emit(logger, f"[Cloud Logging] google-cloud-logging is unavailable: {reason}", "warning")
            return False

        cloud_logger, resource = logger_and_resource
        cloud_logger.log_struct(
            payload,
            severity="INFO",
            timestamp=timestamp,
            insert_id=task_id,
            labels={"it": ""},
            resource=resource,
        )
        _emit(logger, f"[Cloud Logging] ai_usage log sent. task_id={task_id}")
        return True
    except Exception as exc:
        _emit(logger, f"[Cloud Logging] ai_usage log send failed: {exc}", "warning")
        return False