from __future__ import annotations

import base64
import copy
import re

import streamlit as st

try:
    from gp_chat import execution_engine
    from gp_chat import state_manager
except ImportError:
    import execution_engine
    import state_manager

from . import azure_history_utils
from . import azure_responses_router
from .azure_runtime import AzureRuntime


def _build_base_messages_from_session() -> tuple[str, list[dict[str, object]]]:
    system_instruction = ""
    messages: list[dict[str, object]] = []
    for message in st.session_state.get("messages", []):
        role = message.get("role", "user")
        if role == "system":
            system_instruction = message.get("content", "")
            continue
        mapped_role = "assistant" if role in ("assistant", "model") else "user"
        content_type = "output_text" if mapped_role == "assistant" else "input_text"
        messages.append(
            {
                "role": mapped_role,
                "content": [{"type": content_type, "text": message.get("content", "")}],
            }
        )
    return system_instruction, messages


def run_auto_plot_agent(
    *,
    runtime: AzureRuntime,
    initial_response_text: str,
    available_files_map: dict[str, str],
    max_output_tokens: int,
    retry_context_snapshot: list[dict[str, object]] | None = None,
    system_instruction: str = "",
) -> None:
    max_retries = 2
    retry_count = 0
    current_response_text = initial_response_text
    if retry_context_snapshot is not None:
        current_retry_context = copy.deepcopy(retry_context_snapshot)
        system_instruction = system_instruction or ""
    else:
        system_instruction, current_retry_context = _build_base_messages_from_session()
    last_fix_usage = None
    agent_ui_placeholder = st.empty()

    while retry_count <= max_retries:
        code_blocks = re.findall(
            r"```python\s*(.*?)\s*```",
            current_response_text,
            re.DOTALL | re.IGNORECASE,
        )
        state_manager.add_debug_log(
            f"[Azure Auto-Fix] Retry:{retry_count} Found {len(code_blocks)} Python code blocks."
        )
        target_code = None
        for code in reversed(code_blocks):
            if any(key in code for key in ["plt.", "fig", "matplotlib", "pd.", "print(", "dataframe"]):
                target_code = code
                break

        if not target_code:
            state_manager.add_debug_log("[Azure Auto-Fix] No suitable target code found.")
            if retry_count > 0:
                with agent_ui_placeholder.container():
                    st.error("Azure fallback did not return a valid Python code block.")
                    st.session_state["messages"].append(
                        {
                            "role": "assistant",
                            "content": (
                                "Auto-fix failed: Azure fallback did not return a valid Python code block.\n\n"
                                f"{current_response_text}"
                            ),
                        }
                    )
            break

        with agent_ui_placeholder.container():
            with st.chat_message("assistant"):
                status_label = (
                    "Azure fallback is executing generated code..."
                    if retry_count == 0
                    else f"Azure fallback is retrying code execution (Retry {retry_count})..."
                )
                with st.status(status_label, expanded=True) as exec_status:
                    try:
                        stdout_str, figures = execution_engine.execute_user_code(
                            target_code,
                            available_files_map,
                            st.session_state.get("python_canvases", []),
                        )
                        is_error = "Traceback (most recent call last):" in stdout_str

                        if not is_error or retry_count >= max_retries:
                            images_b64 = []
                            for fig_data in figures:
                                b64_str = base64.b64encode(fig_data.getvalue()).decode("utf-8")
                                images_b64.append(b64_str)

                            if stdout_str:
                                st.caption("Execution Output")
                                st.text(stdout_str)

                            if images_b64:
                                st.caption(f"Generated Charts ({len(images_b64)})")
                                for img_b64 in images_b64:
                                    st.image(base64.b64decode(img_b64), width="stretch")

                            if retry_count > 0:
                                fix_msg = {
                                    "role": "assistant",
                                    "content": (
                                        f"**[Azure Corrected Code (Attempt {retry_count})]**\n\n"
                                        f"```python\n{target_code}\n```"
                                    ),
                                }
                                if last_fix_usage:
                                    fix_msg["usage"] = last_fix_usage
                                st.session_state["messages"].append(fix_msg)

                            if stdout_str or images_b64:
                                content_text = f"Running Code...\n\n```text\n{stdout_str}\n```"
                                if is_error:
                                    content_text = (
                                        "Execution failed (retry limit reached):\n\n"
                                        f"```text\n{stdout_str}\n```"
                                    )
                                exec_result_msg = {
                                    "role": "assistant",
                                    "content": content_text,
                                    "images": images_b64,
                                }
                                st.session_state["messages"].append(exec_result_msg)
                                if st.session_state.get("auto_save_enabled", True):
                                    current_file = st.session_state.get("current_chat_filename")
                                    new_filename = azure_history_utils.save_auto_history(
                                        st.session_state["messages"],
                                        st.session_state.get("python_canvases", []),
                                        st.session_state.get("multi_code_enabled", False),
                                        runtime,
                                        current_filename=current_file,
                                    )
                                    if new_filename:
                                        st.session_state["current_chat_filename"] = new_filename

                            exec_status.update(
                                label=(
                                    "Azure code execution finished."
                                    if not is_error
                                    else "Azure code execution failed."
                                ),
                                state="complete" if not is_error else "error",
                            )
                            break

                        retry_count += 1
                        error_feedback = (
                            "Code execution failed with the following error:\n"
                            f"{stdout_str}\n\n"
                            "Please fix the code and return only the corrected Python code block."
                        )
                        current_retry_context.append(
                            {
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": current_response_text}],
                            }
                        )
                        current_retry_context.append(
                            {
                                "role": "user",
                                "content": [{"type": "input_text", "text": error_feedback}],
                            }
                        )
                        fix_response = azure_responses_router.generate_response(
                            runtime=runtime,
                            input_messages=current_retry_context,
                            instructions=system_instruction,
                            max_output_tokens=max_output_tokens,
                            temperature=0.2,
                        )
                        current_response_text = fix_response.text or ""
                        if fix_response.usage_metadata:
                            usage = azure_responses_router.normalize_usage(fix_response.usage_metadata) or {}
                            last_fix_usage = {
                                "total_tokens": usage.get("total_token_count", 0),
                                "input_tokens": usage.get("prompt_token_count", 0),
                                "output_tokens": usage.get("candidates_token_count", 0),
                                "llm_route": "azure_fallback",
                                "llm_retry_count": 0,
                            }
                            st.session_state["last_usage_info"] = last_fix_usage
                            if "total_usage" in st.session_state:
                                st.session_state["total_usage"]["total_tokens"] += int(
                                    usage.get("total_token_count", 0) or 0
                                )
                    except Exception as exc:
                        exec_status.update(
                            label="Azure code-fix loop failed due to a system error.",
                            state="error",
                        )
                        st.error(f"Azure auto-fix loop failed: {exc}")
                        state_manager.add_debug_log(
                            f"[Azure Auto-Fix] System error: {exc}",
                            "error",
                        )
                        break