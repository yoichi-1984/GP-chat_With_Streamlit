import os
import re
import base64
import streamlit as st
from google.genai import types

# --- Local Module Imports ---
try:
    from gp_chat import execution_engine
    from gp_chat import state_manager
    from gp_chat import utils
    from gp_chat import llm_router
except ImportError:
    import execution_engine
    import state_manager
    import utils
    import llm_router


def run_auto_plot_agent(
    client,
    model_id,
    gen_config,
    initial_response_text,
    available_files_map,
    retry_context_snapshot,
):
    """
    AI-generated Python code is executed and, on failure, an auto-fix retry loop
    asks the model for corrected code.
    """
    max_retries = 2
    retry_count = 0
    current_response_text = initial_response_text
    llm_clients = llm_router.coerce_llm_clients(client)
    last_fix_usage = None

    # Snapshot elements are treated as immutable. Retry is append-only so a
    # shallow list copy is safe even when utils had to use shallow fallback.
    current_retry_context = list(retry_context_snapshot)
    state_manager.add_debug_log(
        (
            "[Auto-Fix] Initialized snapshot-based retry context with "
            f"{len(current_retry_context)} messages."
        )
    )

    # Use a placeholder so the retry UI stays grouped with the current response.
    agent_ui_placeholder = st.empty()

    while retry_count <= max_retries:
        code_blocks = re.findall(
            r"```python\s*(.*?)\s*```",
            current_response_text,
            re.DOTALL | re.IGNORECASE,
        )
        state_manager.add_debug_log(
            f"[DEBUG] Retry:{retry_count} Found {len(code_blocks)} Python code blocks."
        )

        target_code = None
        for code in reversed(code_blocks):
            if any(
                key in code
                for key in ["plt.", "fig", "matplotlib", "pd.", "print(", "dataframe"]
            ):
                target_code = code
                break

        if not target_code:
            state_manager.add_debug_log("[DEBUG] No suitable target code found.")
            if retry_count > 0:
                with agent_ui_placeholder.container():
                    st.error(
                        "AIが有効な修正コードを返せなかったため、自動修正を中断しました。"
                    )
                    st.session_state["messages"].append(
                        {
                            "role": "assistant",
                            "content": (
                                "⚠️ Auto-fix failed: AI did not provide a valid "
                                f"Python code block in attempt {retry_count}.\n\n"
                                f"{current_response_text}"
                            ),
                        }
                    )
            break

        state_manager.add_debug_log(f"[DEBUG] Retry:{retry_count} Executing code...")

        with agent_ui_placeholder.container():
            with st.chat_message("assistant"):
                status_label = (
                    "🚀 コードを実行中..."
                    if retry_count == 0
                    else f"🚀 コードを修正して再実行中 (Retry {retry_count})..."
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
                            state_manager.add_debug_log(
                                (
                                    "[DEBUG] Execution finished "
                                    f"(Error: {is_error}). Stdout len: {len(stdout_str)}, "
                                    f"Figures: {len(figures)}"
                                )
                            )

                            images_b64 = []
                            for fig_data in figures:
                                try:
                                    b64_str = base64.b64encode(
                                        fig_data.getvalue()
                                    ).decode("utf-8")
                                    images_b64.append(b64_str)
                                except Exception as e:
                                    state_manager.add_debug_log(
                                        f"Image encode error: {e}", "error"
                                    )

                            if stdout_str:
                                st.caption("🧾 標準出力")
                                st.text(stdout_str)

                            if images_b64:
                                st.caption(f"📊 生成されたグラフ ({len(images_b64)}枚):")
                                for img_b64 in images_b64:
                                    st.image(
                                        base64.b64decode(img_b64),
                                        width="stretch",
                                    )

                            if retry_count > 0:
                                fix_msg = {
                                    "role": "assistant",
                                    "content": (
                                        f"**[AIによる自動修正コード (Attempt {retry_count})]**\n\n"
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
                                        "⚠️ Execution Failed (Retry limit reached):\n\n"
                                        f"```text\n{stdout_str}\n```"
                                    )

                                exec_result_msg = {
                                    "role": "assistant",
                                    "content": content_text,
                                    "images": images_b64,
                                }
                                st.session_state["messages"].append(exec_result_msg)

                                if st.session_state.get("auto_save_enabled", True):
                                    current_file = st.session_state.get(
                                        "current_chat_filename"
                                    )
                                    new_filename = utils.save_auto_history(
                                        st.session_state["messages"],
                                        st.session_state.get("python_canvases", []),
                                        st.session_state.get(
                                            "multi_code_enabled", False
                                        ),
                                        client,
                                        current_filename=current_file,
                                    )
                                    if new_filename:
                                        st.session_state[
                                            "current_chat_filename"
                                        ] = new_filename

                            if is_error:
                                exec_status.update(
                                    label="コード実行エラー (修正上限到達)",
                                    state="error",
                                )
                                st.error(
                                    "AIによるコード自動修正が失敗しました。"
                                )
                            elif stdout_str or images_b64:
                                exec_status.update(
                                    label="コード実行完了", state="complete"
                                )
                            else:
                                exec_status.update(
                                    label="コード実行完了 (出力なし)",
                                    state="complete",
                                )
                                st.warning(
                                    "グラフも標準出力も生成されませんでした。"
                                )

                            break

                        retry_count += 1
                        error_feedback = (
                            "Code Execution Failed with Error:\n"
                            f"{stdout_str}\n\n"
                            "Please fix the code and output the corrected Python code block."
                        )

                        st.warning(
                            (
                                "⚠️ コード実行エラーを検知しました。"
                                f"AIが修正を試みています... (Attempt {retry_count}/{max_retries})"
                            )
                        )
                        state_manager.add_debug_log(
                            f"[Auto-Fix] Requesting fix for error: {stdout_str[:100]}..."
                        )

                        current_retry_context.append(
                            types.Content(
                                role="model",
                                parts=[types.Part.from_text(text=current_response_text)],
                            )
                        )
                        current_retry_context.append(
                            types.Content(
                                role="user",
                                parts=[types.Part.from_text(text=error_feedback)],
                            )
                        )
                        state_manager.add_debug_log(
                            (
                                "[Auto-Fix] Calling retry model with "
                                f"{len(current_retry_context)} messages in context."
                            )
                        )

                        exec_status.update(
                            label=f"⚙️ コードを再生成中 (Attempt {retry_count})...",
                            state="running",
                        )
                        fix_response = llm_router.generate_content_with_route(
                            llm_clients=llm_clients,
                            model_id=model_id,
                            contents=current_retry_context,
                            config=gen_config,
                            mode="auto_plot_fix",
                            logger=state_manager.add_debug_log,
                        )

                        current_response_text = fix_response.text or ""
                        last_fix_usage = None

                        if fix_response.usage_metadata:
                            usage_summary = llm_router.summarize_usage_metadata(
                                fix_response.usage_metadata
                            )
                            last_fix_usage = {
                                "total_tokens": usage_summary["total_token_count"],
                                "input_tokens": usage_summary["prompt_token_count"],
                                "output_tokens": usage_summary[
                                    "candidates_token_count"
                                ],
                                "llm_route": fix_response.route,
                                "llm_retry_count": fix_response.app_retry_count,
                            }
                            if usage_summary.get("traffic_type") is not None:
                                last_fix_usage["traffic_type"] = usage_summary[
                                    "traffic_type"
                                ]
                            if usage_summary.get("thoughts_token_count"):
                                last_fix_usage["thoughts_tokens"] = usage_summary[
                                    "thoughts_token_count"
                                ]
                            if usage_summary.get("cached_content_token_count"):
                                last_fix_usage["cached_tokens"] = usage_summary[
                                    "cached_content_token_count"
                                ]
                            st.session_state["last_usage_info"] = last_fix_usage
                            if "total_usage" in st.session_state:
                                st.session_state["total_usage"][
                                    "total_tokens"
                                ] += usage_summary["total_token_count"]

                    except Exception as e:
                        exec_status.update(
                            label="エージェント処理中のシステムエラー",
                            state="error",
                        )
                        st.error(f"Auto-fix loop failed due to system error: {e}")
                        state_manager.add_debug_log(
                            f"Auto-fix loop failed due to system error: {e}",
                            "error",
                        )
                        break