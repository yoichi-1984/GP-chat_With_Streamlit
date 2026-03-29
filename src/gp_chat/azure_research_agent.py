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


def _safe_json_loads(raw_text: str, fallback_reason: str) -> dict[str, object]:
    try:
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
    except Exception as exc:
        state_manager.add_debug_log(
            f"[Azure Research] JSON parse failed: {exc}. Raw: {raw_text[:120]}...",
            "error",
        )
        return {
            "status": "sufficient",
            "next_queries": [],
            "reasoning": fallback_reason.format(error=exc),
        }


def run_deep_research(
    *,
    runtime: AzureRuntime,
    context,
    max_output_tokens: int,
    text_placeholder,
    thought_status,
    thought_placeholder,
) -> AzureModeResult:
    state_manager.add_debug_log("[Azure Research] Starting Azure Deep Research fallback.")
    total_usage = {"input": 0, "output": 0}
    combined_grounding = {"sources": [], "queries": []}
    full_thought_log = "### Azure Deep Research Process\n\n"
    research_results: list[str] = []
    executed_queries: set[str] = set()

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
        label="Azure fallback is running Deep Research...",
        state="running",
        expanded=False,
    )
    thought_placeholder.markdown(full_thought_log)

    react_schema = {
        "type": "OBJECT",
        "properties": {
            "status": {"type": "STRING"},
            "next_queries": {"type": "ARRAY", "items": {"type": "STRING"}},
            "reasoning": {"type": "STRING"},
        },
        "required": ["status", "next_queries", "reasoning"],
    }

    max_iterations = 3
    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        thought_status.update(
            label=f"Azure research cycle {iteration}/{max_iterations}...",
            state="running",
        )
        current_knowledge = "\n\n".join(research_results) if research_results else "No research results yet."
        react_prompt = (
            "You are planning the next research actions. Review the latest known information and decide "
            "whether more search is required. Return JSON only.\n\n"
            f"Current knowledge:\n{current_knowledge}"
        )
        react_messages = context.messages[-3:] if len(context.messages) > 3 else list(context.messages)
        react_messages = _append_user_message(react_messages, react_prompt)
        react_response = generate_response(
            runtime=runtime,
            input_messages=react_messages,
            instructions=context.system_instruction,
            max_output_tokens=2048,
            temperature=0.2,
            response_schema=react_schema,
            structured_output_name="azure_research_react",
        )
        add_usage(react_response.usage_metadata)
        react_data = _safe_json_loads(
            react_response.text,
            "Azure research planner JSON parse failed. Finish with current knowledge. ({error})",
        )
        status = react_data.get("status", "needs_more_info")
        next_queries = react_data.get("next_queries", [])
        reasoning = react_data.get("reasoning", "")
        full_thought_log += f"\n**[Cycle {iteration}]** {reasoning}\n"
        thought_placeholder.markdown(full_thought_log)

        if status == "sufficient" or not next_queries:
            full_thought_log += "Research loop concluded that current knowledge is sufficient.\n"
            thought_placeholder.markdown(full_thought_log)
            break

        queries_to_run = [query for query in next_queries if query not in executed_queries][:3]
        if not queries_to_run:
            full_thought_log += "No new queries remained. Ending research loop.\n"
            thought_placeholder.markdown(full_thought_log)
            break

        for query in queries_to_run:
            executed_queries.add(query)
            full_thought_log += f"* Search: `{query}`\n"
            thought_placeholder.markdown(full_thought_log)
            exec_response = generate_response(
                runtime=runtime,
                input_messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "Search the web for the following query and summarize the findings in detail.\n"
                                    f"Query: {query}"
                                ),
                            }
                        ],
                    }
                ],
                instructions="Use web search and return a detailed synthesis of the query results.",
                max_output_tokens=4096,
                temperature=0.1,
                search_enabled=True,
            )
            add_usage(exec_response.usage_metadata)
            add_grounding(exec_response.grounding_metadata)
            result_text = exec_response.text
            research_results.append(f"[Query: {query}]\n{result_text}")
            disp_text = result_text[:100].replace("\n", " ") + "..." if len(result_text) > 100 else result_text
            full_thought_log += f"  * Result: {disp_text}\n"
            thought_placeholder.markdown(full_thought_log)
            time.sleep(1)

    thought_status.update(label="Azure fallback is synthesizing research...", state="running")
    compiled_research = "\n\n".join(research_results) if research_results else "No additional research results were gathered."
    synthesis_instruction = context.system_instruction + (
        "\n\nUse the research notes below to answer the user request. "
        "Provide a grounded, well-structured final response.\n\n"
        f"{compiled_research}"
    )

    full_response = ""
    synth_usage = None
    for chunk in stream_response(
        runtime=runtime,
        input_messages=context.messages,
        instructions=synthesis_instruction,
        max_output_tokens=max_output_tokens,
        temperature=0.3,
        search_enabled=True,
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
    thought_status.update(label="Azure Deep Research finished.", state="complete", expanded=False)

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
        mode_meta={"llm_route": "azure_fallback", "llm_retry_count": 0},
        available_files_map=context.available_files_map,
        file_attachments_meta=context.file_attachments_meta,
        retry_context_snapshot=context.clone_retry_context(),
    )