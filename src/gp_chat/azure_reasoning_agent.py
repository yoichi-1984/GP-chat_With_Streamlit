from __future__ import annotations

import json
import time

import streamlit as st

try:
    from gp_chat import state_manager
except ImportError:
    import state_manager

from .azure_common_types import AzureModeResult, AzureUsageMetadata
from .azure_responses_router import generate_response, stream_response
from .azure_runtime import AzureRuntime


def _merge_grounding_metadata(
    current: dict[str, object] | None,
    incoming: dict[str, object] | None,
) -> dict[str, object] | None:
    if not incoming:
        return current
    merged = {
        "sources": list((current or {}).get("sources", [])),
        "queries": list((current or {}).get("queries", [])),
    }
    existing_uris = {source.get("uri") for source in merged["sources"]}
    for source in incoming.get("sources", []):
        uri = source.get("uri")
        if uri and uri not in existing_uris:
            merged["sources"].append(source)
            existing_uris.add(uri)
    existing_queries = set(merged["queries"])
    for query in incoming.get("queries", []):
        if query not in existing_queries:
            merged["queries"].append(query)
            existing_queries.add(query)
    if not merged["sources"] and not merged["queries"]:
        return None
    return merged


def _append_user_message(messages: list[dict[str, object]], text: str) -> list[dict[str, object]]:
    copied = [dict(message) for message in messages]
    copied.append({"role": "user", "content": [{"type": "input_text", "text": text}]})
    return copied


def _safe_json_loads(raw_text: str) -> dict[str, object]:
    clean_text = raw_text.strip()
    if clean_text.startswith("```"):
        lines = clean_text.split("\n")
        if len(lines) >= 3:
            clean_text = "\n".join(lines[1:-1]).strip()
        else:
            clean_text = clean_text.replace("```json", "").replace("```", "").strip()
    start_idx = clean_text.find("{")
    end_idx = clean_text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
        clean_text = clean_text[start_idx : end_idx + 1]
    return json.loads(clean_text)


def run_deep_reasoning(
    *,
    runtime: AzureRuntime,
    context,
    max_output_tokens: int,
    search_enabled: bool,
    text_placeholder,
    thought_status,
    thought_placeholder,
) -> AzureModeResult:
    state_manager.add_debug_log("[Azure Reasoning] Starting Azure Deep Reasoning fallback.")
    total_usage = {"input": 0, "output": 0}
    combined_grounding = {"sources": [], "queries": []}
    last_route = "azure_fallback"
    full_thought_log = "### Azure Deep Reasoning Process\n\n"

    def add_usage(usage_metadata):
        if not usage_metadata:
            return
        total_usage["input"] += usage_metadata.prompt_token_count or 0
        total_usage["output"] += usage_metadata.candidates_token_count or 0

    def add_grounding(grounding_metadata):
        nonlocal combined_grounding
        merged = _merge_grounding_metadata(combined_grounding, grounding_metadata)
        if merged:
            combined_grounding = {
                "sources": list(merged.get("sources", [])),
                "queries": list(merged.get("queries", [])),
            }

    thought_status.update(
        label="Azure fallback is brainstorming approaches...",
        state="running",
        expanded=False,
    )
    thought_placeholder.markdown(full_thought_log)

    brainstorm_prompt = (
        "Propose up to three strong approaches for solving the user's latest request. "
        "Return JSON only."
    )
    brainstorm_schema = {
        "type": "OBJECT",
        "properties": {
            "approaches": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {"type": "STRING"},
                        "description": {"type": "STRING"},
                    },
                    "required": ["name", "description"],
                },
            }
        },
        "required": ["approaches"],
    }

    approaches = []
    try:
        brainstorm_messages = context.messages[-3:] if len(context.messages) > 3 else list(context.messages)
        brainstorm_messages = _append_user_message(brainstorm_messages, brainstorm_prompt)
        bs_response = generate_response(
            runtime=runtime,
            input_messages=brainstorm_messages,
            instructions=context.system_instruction,
            max_output_tokens=2048,
            temperature=0.4,
            search_enabled=search_enabled,
            response_schema=brainstorm_schema,
            structured_output_name="azure_reasoning_brainstorm",
        )
        add_usage(bs_response.usage_metadata)
        add_grounding(bs_response.grounding_metadata)
        bs_data = _safe_json_loads(bs_response.text)
        approaches = bs_data.get("approaches", [])[:3]
        for index, approach in enumerate(approaches, start=1):
            full_thought_log += f"* Approach {index} [{approach['name']}]: {approach['description']}\n"
        thought_placeholder.markdown(full_thought_log)
    except Exception as exc:
        state_manager.add_debug_log(f"[Azure Reasoning] Brainstorm failed: {exc}", "error")
        approaches = [
            {
                "name": "Direct solution",
                "description": "Provide the strongest direct solution with explicit tradeoffs.",
            }
        ]
        full_thought_log += "Azure brainstorming failed, falling back to a single direct approach.\n"

    critique_results = []
    thought_status.update(label="Azure fallback is critiquing approaches...", state="running")
    for index, approach in enumerate(approaches, start=1):
        full_thought_log += f"\n* Critiquing: {approach['name']}\n"
        thought_placeholder.markdown(full_thought_log)
        critique_prompt = (
            f"Evaluate this approach for the user's request.\n"
            f"Approach name: {approach['name']}\n"
            f"Description: {approach['description']}\n\n"
            "Explain strengths, risks, and limits."
        )
        try:
            cr_response = generate_response(
                runtime=runtime,
                input_messages=_append_user_message(context.messages, critique_prompt),
                instructions=context.system_instruction,
                max_output_tokens=3072,
                temperature=0.2,
                search_enabled=search_enabled,
            )
            add_usage(cr_response.usage_metadata)
            add_grounding(cr_response.grounding_metadata)
            result_text = cr_response.text
            critique_results.append(f"[{approach['name']}]\n{result_text}")
            disp_text = result_text[:120].replace("\n", " ") + "..." if len(result_text) > 120 else result_text
            full_thought_log += f"  * Result: {disp_text}\n"
            thought_placeholder.markdown(full_thought_log)
            time.sleep(1)
        except Exception as exc:
            state_manager.add_debug_log(
                f"[Azure Reasoning] Critique failed for '{approach['name']}': {exc}",
                "error",
            )
            full_thought_log += "  * Critique failed for this approach.\n"
            thought_placeholder.markdown(full_thought_log)

    thought_status.update(label="Azure fallback is integrating the final answer...", state="running")
    compiled_reasoning = "\n\n".join(critique_results)
    synthesis_instruction = context.system_instruction + (
        "\n\nUse the reasoning notes below to produce the strongest final answer.\n\n"
        f"{compiled_reasoning}"
    )

    full_response = ""
    synth_usage = None
    for chunk in stream_response(
        runtime=runtime,
        input_messages=context.messages,
        instructions=synthesis_instruction,
        max_output_tokens=max_output_tokens,
        temperature=0.3,
        search_enabled=search_enabled,
    ):
        if chunk.usage_metadata:
            synth_usage = chunk.usage_metadata
        if chunk.grounding_metadata:
            add_grounding(chunk.grounding_metadata)
        if chunk.thought_delta:
            full_thought_log += chunk.thought_delta
            thought_placeholder.markdown(full_thought_log)
        elif chunk.text_delta:
            full_response += chunk.text_delta
            text_placeholder.markdown(full_response + "▌")
    text_placeholder.markdown(full_response)
    add_usage(synth_usage)
    thought_status.update(label="Azure Deep Reasoning finished.", state="complete", expanded=False)

    return AzureModeResult(
        full_response=full_response,
        thought_log=full_thought_log,
        system_instruction=context.system_instruction,
        usage_metadata=AzureUsageMetadata(
            prompt_token_count=total_usage["input"],
            candidates_token_count=total_usage["output"],
            total_token_count=total_usage["input"] + total_usage["output"],
        ),
        grounding_metadata=combined_grounding,
        mode_meta={"llm_route": last_route, "llm_retry_count": 0},
        available_files_map=context.available_files_map,
        file_attachments_meta=context.file_attachments_meta,
        retry_context_snapshot=context.clone_retry_context(),
    )