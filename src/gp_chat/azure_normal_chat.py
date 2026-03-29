from __future__ import annotations

import streamlit as st

try:
    from gp_chat import state_manager
except ImportError:
    import state_manager

from .azure_common_types import AzureModeResult
from .azure_responses_router import stream_response
from .azure_runtime import AzureRuntime


def _thinking_enabled(effort: str) -> bool:
    return effort in ("high", "deep")


def _thinking_label(is_special_mode: bool) -> str:
    if is_special_mode:
        return "Azure fallback is processing the validation request..."
    return "Azure fallback is generating the response..."


def run_normal_generation(
    *,
    runtime: AzureRuntime,
    context,
    max_output_tokens: int,
    search_enabled: bool,
    effort: str,
    is_special_mode: bool,
    text_placeholder,
    thought_status,
    thought_placeholder,
) -> AzureModeResult:
    state_manager.add_debug_log("[Azure Normal] Starting Azure fallback generation.")
    thought_status.update(label=_thinking_label(is_special_mode), state="running", expanded=False)

    full_response = ""
    full_thought_log = ""
    latest_usage = None
    final_grounding = None

    for chunk in stream_response(
        runtime=runtime,
        input_messages=context.messages,
        instructions=context.system_instruction,
        max_output_tokens=max_output_tokens,
        temperature=0.7 if effort == "low" else 0.3,
        search_enabled=search_enabled,
    ):
        if chunk.usage_metadata:
            latest_usage = chunk.usage_metadata
        if chunk.grounding_metadata:
            final_grounding = chunk.grounding_metadata
            queries = chunk.grounding_metadata.get("queries", [])
            if queries:
                state_manager.add_debug_log(f"[Azure Normal] Queries detected: {queries}")
                for query in queries:
                    full_thought_log += f"\n\n**Action (Azure Search):** `{query}`\n\n"
                    thought_placeholder.markdown(full_thought_log)
        if chunk.thought_delta and _thinking_enabled(effort):
            full_thought_log += chunk.thought_delta
            thought_placeholder.markdown(full_thought_log)
        elif chunk.text_delta:
            full_response += chunk.text_delta
            text_placeholder.markdown(full_response + "▌")

    text_placeholder.markdown(full_response)
    if full_thought_log:
        thought_status.update(label="Azure fallback finished thinking.", state="complete", expanded=False)
    else:
        thought_status.update(label="Azure fallback finished.", state="complete", expanded=False)

    return AzureModeResult(
        full_response=full_response,
        thought_log=full_thought_log,
        system_instruction=context.system_instruction,
        usage_metadata=latest_usage,
        grounding_metadata=final_grounding,
        mode_meta={"llm_route": "azure_fallback", "llm_retry_count": 0},
        available_files_map=context.available_files_map,
        file_attachments_meta=context.file_attachments_meta,
        retry_context_snapshot=context.clone_retry_context(),
    )


def run_special_generation(
    *,
    runtime: AzureRuntime,
    context,
    max_output_tokens: int,
    effort: str,
    text_placeholder,
    thought_status,
    thought_placeholder,
) -> AzureModeResult:
    return run_normal_generation(
        runtime=runtime,
        context=context,
        max_output_tokens=max_output_tokens,
        search_enabled=False,
        effort=effort,
        is_special_mode=True,
        text_placeholder=text_placeholder,
        thought_status=thought_status,
        thought_placeholder=thought_placeholder,
    )