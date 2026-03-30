# src\gp_chat\azure_runtime.py:
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from dotenv import dotenv_values


AZURE_OPENAI_ENDPOINT_NAME = "AZURE_OPENAI_ENDPOINT"
AZURE_OPENAI_API_KEY_NAME = "AZURE_OPENAI_API_KEY"
AZURE_OPENAI_GPT54_DEPLOYMENT_NAME = "AZURE_OPENAI_GPT54_DEPLOYMENT"
AZURE_OPENAI_ENV_FILE_NAME = "AZURE_OPENAI_ENV_FILE"

LoggerFn = Callable[[str, str], None]


@dataclass(frozen=True)
class AzureRuntime:
    endpoint: str
    api_key: str
    deployment: str
    base_url: str


def _log(logger: LoggerFn | None, message: str, level: str = "info") -> None:
    if not logger:
        return
    try:
        logger(message, level)
    except TypeError:
        logger(message)


def _normalize_env_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _load_env_values(env_path: str | None) -> dict[str, str]:
    if not env_path:
        return {}
    resolved_path = os.path.abspath(os.path.expandvars(os.path.expanduser(env_path)))
    if not os.path.isfile(resolved_path):
        return {}
    return {
        key: _normalize_env_value(value)
        for key, value in dotenv_values(resolved_path).items()
        if value is not None
    }


def _resolve_relative_env_path(raw_path: str, base_env_path: str | None) -> str:
    expanded_path = os.path.expandvars(os.path.expanduser(raw_path))
    if os.path.isabs(expanded_path):
        return os.path.normpath(expanded_path)
    if base_env_path:
        base_dir = os.path.dirname(os.path.abspath(base_env_path))
        return os.path.normpath(os.path.join(base_dir, expanded_path))
    return os.path.normpath(os.path.abspath(expanded_path))


def _get_config_value(
    name: str,
    env_values: dict[str, str],
    *,
    allow_process_fallback: bool,
) -> str:
    if name in env_values:
        return env_values[name]
    if allow_process_fallback:
        return _normalize_env_value(os.getenv(name, ""))
    return ""


def _normalize_base_url(endpoint: str) -> str:
    base_url = endpoint.rstrip("/")
    if base_url.endswith("/openai/v1"):
        return f"{base_url}/"
    if base_url.endswith("/openai"):
        return f"{base_url}/v1/"
    return f"{base_url}/openai/v1/"


def load_azure_runtime_from_env(
    *,
    bootstrap_env_path: str | None = None,
    logger: LoggerFn | None = None,
) -> AzureRuntime | None:
    bootstrap_values = _load_env_values(bootstrap_env_path)
    allow_process_fallback = not bootstrap_values

    endpoint = _get_config_value(
        AZURE_OPENAI_ENDPOINT_NAME,
        bootstrap_values,
        allow_process_fallback=allow_process_fallback,
    )
    api_key = _get_config_value(
        AZURE_OPENAI_API_KEY_NAME,
        bootstrap_values,
        allow_process_fallback=allow_process_fallback,
    )
    deployment = _get_config_value(
        AZURE_OPENAI_GPT54_DEPLOYMENT_NAME,
        bootstrap_values,
        allow_process_fallback=allow_process_fallback,
    )

    external_env_path = _get_config_value(
        AZURE_OPENAI_ENV_FILE_NAME,
        bootstrap_values,
        allow_process_fallback=allow_process_fallback,
    )
    if external_env_path:
        resolved_external_env_path = _resolve_relative_env_path(
            external_env_path,
            bootstrap_env_path,
        )
        if os.path.isfile(resolved_external_env_path):
            external_values = _load_env_values(resolved_external_env_path)
            endpoint = external_values.get(AZURE_OPENAI_ENDPOINT_NAME, endpoint)
            api_key = external_values.get(AZURE_OPENAI_API_KEY_NAME, api_key)
            deployment = external_values.get(
                AZURE_OPENAI_GPT54_DEPLOYMENT_NAME,
                deployment,
            )
            _log(
                logger,
                f"[Azure Runtime] Loaded Azure config from {resolved_external_env_path}",
            )
        else:
            _log(
                logger,
                f"[Azure Runtime] Azure env file not found: {resolved_external_env_path}",
                "warning",
            )

    if not (endpoint and api_key and deployment):
        if external_env_path:
            _log(
                logger,
                (
                    "[Azure Runtime] Azure config is incomplete. "
                    "Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and "
                    "AZURE_OPENAI_GPT54_DEPLOYMENT in the referenced env file."
                ),
                "warning",
            )
        return None
    return AzureRuntime(
        endpoint=endpoint,
        api_key=api_key,
        deployment=deployment,
        base_url=_normalize_base_url(endpoint),
    )


def is_azure_runtime_available(runtime: AzureRuntime | None) -> bool:
    return runtime is not None and bool(
        runtime.endpoint and runtime.api_key and runtime.deployment
    )