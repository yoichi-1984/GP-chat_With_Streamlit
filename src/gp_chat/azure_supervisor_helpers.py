from __future__ import annotations

import re
from typing import Any

import streamlit as st

from .azure_fault_injection import (
    build_synthetic_terminal_429,
    should_force_azure_branch,
    should_inject_terminal_429,
)


_ISOLATED_429_RE = re.compile(r"(?<!\d)429(?!\d)")
_RATE_LIMIT_TOKENS = (
    "resource exhausted",
    "resource_exhausted",
    "too many requests",
    "rate limit",
    "ratelimit",
)
_ERROR_CONTEXT_TOKENS = (
    "[error]",
    "error during generation",
    "error code",
    "failed",
    "exception",
    "traceback",
    "invalid_request_error",
)


def _has_isolated_429(text: str) -> bool:
    return bool(_ISOLATED_429_RE.search(text))


def _has_rate_limit_marker(text: str) -> bool:
    return any(token in text for token in _RATE_LIMIT_TOKENS)


def _has_error_context(text: str) -> bool:
    return any(token in text for token in _ERROR_CONTEXT_TOKENS)


def get_debug_logs_since(start_index: int) -> list[str]:
    return list(st.session_state.get("debug_logs", [])[start_index:])


def detect_terminal_429_from_exception(exc: Exception | None) -> bool:
    if exc is None:
        return False
    for value in (
        getattr(exc, "code", None),
        getattr(exc, "status_code", None),
        getattr(getattr(exc, "response", None), "status_code", None),
    ):
        if value == 429:
            return True
    class_name = exc.__class__.__name__.lower()
    text = f"{class_name} {str(exc).lower()}"
    has_429 = _has_isolated_429(text)
    if not has_429:
        return False
    return _has_rate_limit_marker(text) or "error" in class_name or "exception" in class_name


def detect_terminal_429_from_log_lines(lines: list[str]) -> bool:
    for line in lines:
        lowered = line.lower()
        if _has_isolated_429(lowered) and (
            _has_rate_limit_marker(lowered) or _has_error_context(lowered)
        ):
            return True
    return False


def has_visible_output_started(
    *,
    full_response: str = "",
    messages_before: int | None = None,
    messages_after: int | None = None,
) -> bool:
    if full_response:
        return True
    if messages_before is not None and messages_after is not None and messages_after > messages_before:
        return True
    return False


def can_take_over_auto_plot_fix(
    *,
    messages_before: int,
    messages_after: int,
    debug_logs_since_start: list[str],
) -> bool:
    return messages_after == messages_before and detect_terminal_429_from_log_lines(
        debug_logs_since_start
    )


def apply_fault_injection(mode: str, cfg) -> Exception | None:
    if should_force_azure_branch(mode, cfg):
        return build_synthetic_terminal_429(mode)
    if should_inject_terminal_429(mode, cfg):
        return build_synthetic_terminal_429(mode)
    return None


def should_skip_gcp_for_mode(mode: str, cfg) -> bool:
    return should_force_azure_branch(mode, cfg)


def should_attempt_azure_fallback(
    *,
    exception: Exception | None,
    log_lines: list[str],
    visible_output_started: bool,
    azure_runtime_available: bool,
    mode_supported: bool,
) -> bool:
    if visible_output_started:
        return False
    if not azure_runtime_available or not mode_supported:
        return False
    return detect_terminal_429_from_exception(exception) or detect_terminal_429_from_log_lines(log_lines)