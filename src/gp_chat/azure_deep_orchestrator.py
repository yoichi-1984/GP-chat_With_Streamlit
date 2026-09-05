from __future__ import annotations

import asyncio
import concurrent.futures
import json
from typing import Any

try:
    from gp_chat import config
    from gp_chat import state_manager
except ImportError:
    import config
    import state_manager

from .azure_common_types import AzureModeResult, AzureUsageMetadata
from .azure_responses_router import _build_async_client, async_generate_response, async_stream_response
from .azure_runtime import AzureRuntime


def _safe_json_loads(raw_text: str) -> dict[str, Any]:
    """Safely parse JSON response from LLM, stripping potential markdown fences."""
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


def _run_coroutine(coro):
    """Safely execute an async coroutine from synchronous Streamlit execution threads."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


async def _run_async_orchestrated_generation(
    *,
    runtime: AzureRuntime,
    context,
    max_output_tokens: int,
    search_enabled: bool,
    effort: str,
    text_placeholder,
    thought_status,
    thought_placeholder,
    model_id: str | None = None,
) -> AzureModeResult:
    is_fallback = model_id not in config.AZURE_DIRECT_MODELS
    log_prefix = "Azure fallback" if is_fallback else f"Azure ({model_id})"
    state_manager.add_debug_log(
        f"[{log_prefix} Orchestrator] Starting hybrid HTTP/2 orchestrated generation (effort={effort})"
    )

    client = _build_async_client(runtime)
    try:
        full_thought_log = ""
        full_response = ""
        latest_usage: AzureUsageMetadata | None = None
        final_grounding: dict[str, object] | None = None

        # ---------------------------------------------------------
        # Phase 1: Planning & Task Breakdown (Planner)
        # ---------------------------------------------------------
        thought_status.update(
            label=f"{log_prefix} Planning subtasks...",
            state="running",
            expanded=False,
        )

        plan_data: dict[str, Any] = {}
        try:
            planner_result = await async_generate_response(
                runtime=runtime,
                input_messages=context.messages,
                instructions=config.AZURE_DEEP_PLANNER_PROMPT,
                max_output_tokens=4096,
                temperature=0.2,
                search_enabled=False,
                response_mime_type="application/json",
                response_schema=config.AZURE_DEEP_PLANNER_SCHEMA,
                structured_output_name="task_plan",
                reasoning_effort="low",
                client=client,
            )
            plan_text = planner_result.text.strip()
            if plan_text:
                plan_data = _safe_json_loads(plan_text)
        except Exception as e:
            state_manager.add_debug_log(f"[{log_prefix} Orchestrator] Phase 1 planning error: {e}")
            plan_data = {"needs_parallel_subtasks": False, "plan_summary": "Direct generation", "subtasks": []}

        needs_parallel = bool(plan_data.get("needs_parallel_subtasks", False))
        subtasks = plan_data.get("subtasks", [])
        plan_summary = plan_data.get("plan_summary", "")

        subtask_results: list[tuple[str, str, str]] = []

        if needs_parallel and isinstance(subtasks, list) and len(subtasks) > 0:
            full_thought_log += (
                f"### 📋 実行計画 (Phase 1: Task Breakdown)\n\n"
                f"**アプローチ要約**: {plan_summary}\n\n"
                f"**並行サブタスク ({len(subtasks)} 件)**:\n"
            )
            for item in subtasks:
                sub_id = item.get("id", "sub")
                desc = item.get("description", "")
                q = item.get("query", "")
                query_info = f" *(検索: `{q}`)*" if q else ""
                full_thought_log += f"- **[{sub_id}]**: {desc}{query_info}\n"
            full_thought_log += "\n"
            thought_placeholder.markdown(full_thought_log)

            # ---------------------------------------------------------
            # Phase 2: Parallel Subtask Execution (HTTP/2 Multiplexing)
            # ---------------------------------------------------------
            concurrency_limit = max(1, config.AZURE_DEEP_MAX_CONCURRENCY)
            semaphore = asyncio.Semaphore(concurrency_limit)
            completed_count = 0
            total_subtasks = len(subtasks)

            thought_status.update(
                label=f"{log_prefix} Executing parallel subtasks (0/{total_subtasks})...",
                state="running",
                expanded=False,
            )

            async def _execute_subtask(subtask_item: dict[str, str]) -> tuple[str, str, str]:
                nonlocal completed_count
                st_id = subtask_item.get("id", "sub")
                st_desc = subtask_item.get("description", "")
                st_query = subtask_item.get("query", "")

                st_instruction = (
                    f"{config.AZURE_DEEP_SUBTASK_PROMPT}\n\n"
                    f"Overall Plan: {plan_summary}\n"
                    f"Assigned Subtask ID: {st_id}\n"
                    f"Subtask Scope: {st_desc}"
                )
                st_messages = list(context.messages)
                if st_query:
                    st_messages.append(
                        {
                            "role": "user",
                            "content": f"[Subtask Query]: {st_query}\n[Goal]: {st_desc}",
                        }
                    )

                async with semaphore:
                    try:
                        res = await async_generate_response(
                            runtime=runtime,
                            input_messages=st_messages,
                            instructions=st_instruction,
                            max_output_tokens=min(max_output_tokens, 16384),
                            temperature=0.3,
                            search_enabled=search_enabled,
                            reasoning_effort="low",
                            client=client,
                        )
                        st_text = res.text
                    except Exception as exc:
                        state_manager.add_debug_log(
                            f"[{log_prefix} Orchestrator] Subtask {st_id} execution error: {exc}"
                        )
                        st_text = f"⚠️ サブタスク実行エラー ({exc})"

                    completed_count += 1
                    thought_status.update(
                        label=f"{log_prefix} Executing parallel subtasks ({completed_count}/{total_subtasks})...",
                        state="running",
                        expanded=False,
                    )
                    return st_id, st_desc, st_text

            tasks = [_execute_subtask(st_item) for st_item in subtasks]
            subtask_results = await asyncio.gather(*tasks)

            full_thought_log += "### ⚡ サブタスク収集結果 (Phase 2: Parallel Materials)\n\n"
            for st_id, st_desc, st_text in subtask_results:
                full_thought_log += (
                    f"<details><summary><b>✅ [{st_id}] {st_desc}</b></summary>\n\n"
                    f"{st_text}\n\n"
                    f"</details>\n"
                )
            full_thought_log += "\n"
            thought_placeholder.markdown(full_thought_log)

        else:
            full_thought_log += "### 📋 実行計画 (Phase 1: Task Breakdown)\n\n単一の直接推論タスクとして統合推論を実行します。\n\n"
            thought_placeholder.markdown(full_thought_log)

        # ---------------------------------------------------------
        # Phase 3: Reasoning Streaming & Synthesis (Synthesizer)
        # ---------------------------------------------------------
        thought_status.update(
            label=f"{log_prefix} Deep thinking & synthesizing...",
            state="running",
            expanded=False,
        )
        full_thought_log += "### 🧠 思考推論 & 統合回答生成 (Phase 3: Synthesis)\n\n"
        thought_placeholder.markdown(full_thought_log)

        synthesis_instruction = context.system_instruction or ""
        if subtask_results:
            materials_block = "\n\n".join(
                f"### Material from [{st_id}] ({st_desc}):\n{st_text}"
                for st_id, st_desc, st_text in subtask_results
            )
            synthesis_instruction += (
                f"\n\n---\n## Materials Gathered from Parallel Subtasks:\n"
                f"**Plan Summary**: {plan_summary}\n\n"
                f"{materials_block}\n\n"
                f"Based on the materials gathered above and the conversation context, synthesize a comprehensive, rigorous, and cohesive response."
            )

        async for chunk in async_stream_response(
            runtime=runtime,
            input_messages=context.messages,
            instructions=synthesis_instruction,
            max_output_tokens=max_output_tokens,
            reasoning_effort=effort,
            search_enabled=search_enabled,
            client=client,
        ):
            if chunk.usage_metadata:
                latest_usage = chunk.usage_metadata
            if chunk.grounding_metadata:
                final_grounding = chunk.grounding_metadata
                queries = chunk.grounding_metadata.get("queries", [])
                for q in queries:
                    full_thought_log += f"\n\n**Action (Azure Search):** `{q}`\n\n"
                    thought_placeholder.markdown(full_thought_log)
            if chunk.thought_delta:
                full_thought_log += chunk.thought_delta
                thought_placeholder.markdown(full_thought_log)
            elif chunk.text_delta:
                full_response += chunk.text_delta
                text_placeholder.markdown(full_response + "▌")

        text_placeholder.markdown(full_response)
        finished_prefix = "Azure fallback" if is_fallback else f"Azure ({model_id})"
        thought_status.update(
            label=f"{finished_prefix} finished thinking.",
            state="complete",
            expanded=False,
        )

        return AzureModeResult(
            full_response=full_response,
            thought_log=full_thought_log,
            system_instruction=synthesis_instruction,
            usage_metadata=latest_usage,
            grounding_metadata=final_grounding,
            mode_meta={
                "llm_route": "azure_deep_orchestrator",
                "subtasks_count": len(subtask_results),
                "llm_retry_count": 0,
            },
            available_files_map=context.available_files_map,
            file_attachments_meta=context.file_attachments_meta,
            retry_context_snapshot=context.clone_retry_context(),
        )
    finally:
        await client.close()


def run_orchestrated_generation(
    *,
    runtime: AzureRuntime,
    context,
    max_output_tokens: int,
    search_enabled: bool,
    effort: str,
    text_placeholder,
    thought_status,
    thought_placeholder,
    model_id: str | None = None,
) -> AzureModeResult:
    """Synchronous entry point called by Streamlit UI worker."""
    return _run_coroutine(
        _run_async_orchestrated_generation(
            runtime=runtime,
            context=context,
            max_output_tokens=max_output_tokens,
            search_enabled=search_enabled,
            effort=effort,
            text_placeholder=text_placeholder,
            thought_status=thought_status,
            thought_placeholder=thought_placeholder,
            model_id=model_id,
        )
    )
