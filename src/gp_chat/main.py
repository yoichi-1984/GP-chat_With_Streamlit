import os
import sys
import base64

import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types

# --- Local Module Imports ---
try:
    from gp_chat import config
    from gp_chat import utils
    from gp_chat import sidebar
    from gp_chat import data_manager
    from gp_chat import state_manager
    from gp_chat import code_agent
    from gp_chat import research_agent
except ImportError:
    import config
    import utils
    import sidebar
    import data_manager
    import state_manager
    import code_agent
    import research_agent

def run_chatbot_app():
    st.set_page_config(page_title=config.UITexts.APP_TITLE, layout="wide")
    st.title(config.UITexts.APP_TITLE)
    
    if "debug_logs" not in st.session_state:
        st.session_state["debug_logs"] = []

    # Initialize Data Manager
    dm = data_manager.SessionDataManager()

    # サイドバー描画
    PROMPTS = utils.load_prompts()
    APP_CONFIG = utils.load_app_config()
    supported_extensions = APP_CONFIG.get("file_uploader", {}).get("supported_extensions", [])
    env_files = utils.find_env_files()
    
    if not env_files:
        st.error("env ディレクトリに .env ファイルが必要です。")
        st.stop()

    for key, value in config.SESSION_STATE_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value.copy() if isinstance(value, (dict, list)) else value

    # Canvas読み込み時の文字コード対応関数
    def handle_canvas_upload(index, key):
        uploaded_file = st.session_state.get(key)
        if uploaded_file:
            bytes_data = uploaded_file.getvalue()
            text = ""
            try:
                # まずUTF-8で試す
                text = bytes_data.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    # ダメならCP932 (Windows Shift-JIS) で試す
                    text = bytes_data.decode("cp932")
                except UnicodeDecodeError:
                    st.toast("⚠️ 対応していない文字コードです (UTF-8, CP932以外)", icon="❌")
                    return
            
            st.session_state['python_canvases'][index] = text

    sidebar.render_sidebar(
        supported_extensions, env_files, 
        state_manager.load_history,
        state_manager.load_history_from_local,
        lambda i: st.session_state['python_canvases'].__setitem__(i, config.ACE_EDITOR_DEFAULT_CODE),
        lambda i, m: (st.session_state['messages'].append({"role": "user", "content": config.UITexts.REVIEW_PROMPT_MULTI.format(i=i+1) if m else config.UITexts.REVIEW_PROMPT_SINGLE}), st.session_state.__setitem__('is_generating', True)),
        lambda i: utils.run_pylint_validation(st.session_state['python_canvases'][i], i, PROMPTS),
        handle_canvas_upload 
    )

    # 中断リカバリーチェック
    if st.session_state.get('messages') and st.session_state['messages'][-1]['role'] == 'user' and not st.session_state.get('is_generating'):
        if state_manager.recover_interrupted_session():
            st.rerun()
    
    # --- .env ロードと Client 初期化 ---
    load_dotenv(dotenv_path=st.session_state.get('selected_env_file', env_files[0]), override=True)
    
    project_id = os.getenv(config.GCP_PROJECT_ID_NAME)
    location = os.getenv(config.GCP_LOCATION_NAME, "global") 
    model_id = st.session_state.get('current_model_id', os.getenv(config.GEMINI_MODEL_ID_NAME, "gemini-3-pro-preview"))
    
    INPUT_LIMIT = 1000000
    OUTPUT_LIMIT = 65536
    max_tokens_val = min(int(os.getenv("MAX_TOKEN", "65536")), OUTPUT_LIMIT)

    try:
        client = genai.Client(vertexai=True, project=project_id, location=location)
    except Exception as e:
        st.error(f"Client init error: {e}")
        st.stop()

    st.caption(f"Backend: {model_id} | Location: {location}")

    with st.expander("🛠 システムログ", expanded=False):
        for log in reversed(st.session_state["debug_logs"]):
            st.text(log)

    if not st.session_state['system_role_defined']:
        st.subheader("AIの役割を設定（デフォルトでも、変更してもどちらでもOK）")
        role = st.text_area("System Role", value=PROMPTS.get("system", {}).get("text", ""), height=200)
        if st.button("チャットを開始", type="primary"):
            st.session_state['messages'] = [{"role": "system", "content": role}]
            st.session_state['system_role_defined'] = True
            st.rerun()
        st.stop()

    for msg in st.session_state['messages']:
        if msg["role"] != "system":
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                
                # --- 画像 (グラフ) の表示ロジック ---
                if "images" in msg and msg["images"]:
                    for img_b64 in msg["images"]:
                        try:
                            st.image(base64.b64decode(img_b64), use_container_width=True)
                        except Exception as e:
                            st.error(f"画像表示エラー: {e}")
                # -------------------------------

                if "grounding_metadata" in msg and msg["grounding_metadata"]:
                    with st.expander("🔎 検索ソース (Grounding)"):
                        st.json(msg["grounding_metadata"])

                if msg["role"] == "assistant" and "usage" in msg:
                    u = msg["usage"]
                    in_p = (u['input_tokens'] / INPUT_LIMIT) * 100
                    out_p = (u['output_tokens'] / OUTPUT_LIMIT) * 100
                    
                    st.caption(
                        f"📊 **トークン使用量詳細**\n\n"
                        f"📥 **Input (Context):** {u['input_tokens']:,} / {INPUT_LIMIT:,} ({in_p:.2f}%)\n"
                        f"📤 **Output (Response):** {u['output_tokens']:,} / {OUTPUT_LIMIT:,} ({out_p:.2f}%)"
                    )

    if st.session_state['total_usage']['total_tokens'] > 0:
        st.divider()
        st.caption(f"🏁 セッション累計使用トークン: {st.session_state['total_usage']['total_tokens']:,}")

    if 'draft_input' in st.session_state:
        st.warning("⚠️ 前回の送信が中断されました。テキストを復元しました。")
        with st.form("draft_form"):
            draft_text = st.text_area("編集して再送信", value=st.session_state['draft_input'], height=150)
            c1, c2 = st.columns([1, 4])
            with c1:
                resend = st.form_submit_button("再送信", type="primary", use_container_width=True)
            with c2:
                cancel_draft = st.form_submit_button("破棄 (入力をクリア)", use_container_width=True)
            
            if resend:
                st.session_state['messages'].append({"role": "user", "content": draft_text})
                del st.session_state['draft_input']
                st.session_state['is_generating'] = True
                st.rerun()
            elif cancel_draft:
                del st.session_state['draft_input']
                st.rerun()
    
    else:
        if prompt := st.chat_input("指示を入力...", disabled=st.session_state['is_generating']):
            st.session_state['messages'].append({"role": "user", "content": prompt})
            st.session_state['is_generating'] = True
            st.rerun()

    if st.session_state['is_generating']:
        st.markdown("---")
        c_stop, c_info = st.columns([1, 5])
        with c_stop:
            if st.button("■ 送信取り消し", key="stop_generating_btn", type="primary"):
                st.session_state['is_generating'] = False
                st.rerun()
        with c_info:
            st.info("生成中... 「送信取り消し」を押すと中断し、テキストを復元します。")

        with st.chat_message("assistant"):
            thought_area_container = st.empty()
            with thought_area_container.container():
                thought_status = st.status("思考プロセス (Thinking Process)...", expanded=False)
                thought_placeholder = thought_status.empty()
            
            text_placeholder = st.empty()
            full_response = ""
            full_thought_log = ""
            usage_metadata = None 
            grounding_chunks = []
            
            is_special_mode = 'special_generation_messages' in st.session_state and st.session_state['special_generation_messages']
            
            target_messages = []
            if is_special_mode:
                target_messages = st.session_state['special_generation_messages']
                state_manager.add_debug_log("Generating response for SPECIAL validation request.")
            else:
                target_messages = st.session_state['messages']

            is_more_research = st.session_state.get('enable_more_research', False) and not is_special_mode

            chat_contents = []
            system_instruction = ""
            for m in target_messages:
                if m["role"] == "system":
                    system_instruction = m["content"]
                else:
                    chat_contents.append(types.Content(role=m["role"], parts=[types.Part.from_text(text=m["content"])]))
            
            file_attachments_meta = []
            queue_files = st.session_state.get('uploaded_file_queue', []) + st.session_state.get('clipboard_queue', [])
            
            available_files_map = {}
            if st.session_state.get('auto_plot_enabled', False) and not is_special_mode:
                for f in queue_files:
                    try:
                        f_path, f_name = dm.save_file(f)
                        if f_path:
                            available_files_map[f_name] = f_path
                            state_manager.add_debug_log(f"Saved temp file for analysis: {f_name}")
                    except Exception as e:
                        state_manager.add_debug_log(f"Failed to save temp file {f.name}: {e}", "error")

            if not is_special_mode and queue_files:
                file_parts, file_meta = utils.process_uploaded_files_for_gemini(queue_files)
                if file_parts and chat_contents:
                    last_user_msg_content = chat_contents[-1]
                    if last_user_msg_content.role == "user":
                        last_user_msg_content.parts = file_parts + last_user_msg_content.parts
                        file_attachments_meta = file_meta
                        state_manager.add_debug_log(f"Attached {len(file_parts)} files to the request.")

            if not is_special_mode:
                context_parts = []
                for i, code in enumerate(st.session_state['python_canvases']):
                    if code.strip() and code != config.ACE_EDITOR_DEFAULT_CODE:
                        context_parts.append(types.Part.from_text(text=f"\n[Canvas-{i+1}]\n```python\n{code}\n```"))
                
                if context_parts and chat_contents:
                    chat_contents[-1].parts = context_parts + chat_contents[-1].parts

            effort = st.session_state.get('reasoning_effort', 'high')
            
            if is_more_research:
                t_level = types.ThinkingLevel.HIGH
            else:
                t_level = types.ThinkingLevel.HIGH if effort == 'high' else types.ThinkingLevel.LOW

            tools_config = []
            enable_search = st.session_state.get('enable_google_search', False)
            
            if (enable_search or is_more_research) and not is_special_mode:
                msg = "Google Search Tool Enabled"
                if is_more_research and not enable_search:
                    msg += " (Forced by More Research Mode)."
                state_manager.add_debug_log(msg)
                tools_config = [types.Tool(google_search=types.GoogleSearch())]

            try:
                state_manager.add_debug_log(f"Requesting stream: {model_id} via {location} (max_output={max_tokens_val})")
                
                gen_config = types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    max_output_tokens=max_tokens_val,
                    tools=tools_config
                )
                if "gemini-3" in model_id:
                    gen_config.thinking_config = types.ThinkingConfig(
                        thinking_level=t_level,
                        include_thoughts=True
                    )

                if is_more_research:
                    # Deep Researchエージェントに処理を委譲
                    full_response, usage_metadata, final_grounding_metadata = research_agent.run_deep_research(
                        client=client,
                        model_id=model_id,
                        gen_config=gen_config,
                        chat_contents=chat_contents,
                        system_instruction=system_instruction,
                        text_placeholder=text_placeholder,
                        thought_status=thought_status,
                        thought_placeholder=thought_placeholder
                    )
                else:
                    # 通常のストリーミング生成
                    stream = client.models.generate_content_stream(
                        model=model_id,
                        contents=chat_contents,
                        config=gen_config
                    )

                    chunk_count = 0
                    for chunk in stream:
                        chunk_count += 1
                        if chunk.usage_metadata:
                            usage_metadata = chunk.usage_metadata
                        
                        if not chunk.candidates: continue
                        
                        cand = chunk.candidates[0]

                        if cand.grounding_metadata:
                            grounding_chunks.append(cand.grounding_metadata)
                            if cand.grounding_metadata.web_search_queries:
                                queries = cand.grounding_metadata.web_search_queries
                                state_manager.add_debug_log(f"[Grounding] Queries detected: {queries}")
                                for query in queries:
                                    action_text = f"\n\n🔍 **Action (Google Search):** `{query}`\n\n"
                                    full_thought_log += action_text
                                    thought_placeholder.markdown(full_thought_log)

                        if cand.content and cand.content.parts:
                            for part in cand.content.parts:
                                is_thought = False
                                thought_text = ""
                                if hasattr(part, 'thought') and isinstance(part.thought, str) and part.thought:
                                    is_thought = True
                                    thought_text = part.thought
                                elif hasattr(part, 'thought') and part.thought is True:
                                    is_thought = True
                                    thought_text = part.text

                                if is_thought:
                                    if thought_text:
                                        full_thought_log += thought_text
                                        thought_placeholder.markdown(full_thought_log)
                                elif part.text:
                                    full_response += part.text
                                    text_placeholder.markdown(full_response + "▌")
                    
                    text_placeholder.markdown(full_response)
                    
                    if not full_thought_log:
                        thought_area_container.empty()
                    else:
                        thought_status.update(label="思考完了 (Finished Thinking)", state="complete", expanded=False)
                    
                    final_grounding_metadata = None
                    if grounding_chunks:
                        last_meta = grounding_chunks[-1]
                        final_grounding_metadata = {}
                        if last_meta.grounding_chunks:
                            sources = []
                            for gc in last_meta.grounding_chunks:
                                if gc.web:
                                    sources.append({"title": gc.web.title, "uri": gc.web.uri})
                            if sources:
                                final_grounding_metadata["sources"] = sources
                        if last_meta.web_search_queries:
                            final_grounding_metadata["queries"] = last_meta.web_search_queries

                # SearchとDeep Research両方に対応した共通のGrounding表示
                if final_grounding_metadata and (final_grounding_metadata.get("sources") or final_grounding_metadata.get("queries")):
                    with st.expander("🔎 検索ソース (Grounding)"):
                        st.json(final_grounding_metadata)

                state_manager.add_debug_log("Stream successfully finished.")

                current_usage = None
                if usage_metadata:
                    current_usage = {
                        "total_tokens": usage_metadata.total_token_count,
                        "input_tokens": usage_metadata.prompt_token_count,
                        "output_tokens": usage_metadata.candidates_token_count
                    }
                    st.session_state['total_usage']['total_tokens'] += usage_metadata.total_token_count
                    st.session_state['last_usage_info'] = current_usage

                assistant_msg = {"role": "assistant", "content": full_response}
                if current_usage:
                    assistant_msg["usage"] = current_usage
                if final_grounding_metadata:
                    assistant_msg["grounding_metadata"] = final_grounding_metadata
                
                if is_special_mode:
                    for m in target_messages:
                        if m["role"] == "user":
                            st.session_state['messages'].append(m)
                    st.session_state['messages'].append(assistant_msg)
                    del st.session_state['special_generation_messages']
                    state_manager.add_debug_log("Special validation messages merged to history.")
                else:
                    st.session_state['messages'].append(assistant_msg)
                    
                    if st.session_state.get('auto_save_enabled', True):
                        current_file = st.session_state.get('current_chat_filename')
                        new_filename = utils.save_auto_history(
                            st.session_state['messages'],
                            st.session_state['python_canvases'],
                            st.session_state.get('multi_code_enabled', False),
                            client,
                            current_filename=current_file
                        )
                        if new_filename:
                            st.session_state['current_chat_filename'] = new_filename

                if 'uploaded_file_queue' in st.session_state:
                     st.session_state['uploaded_file_queue'] = []
                if 'clipboard_queue' in st.session_state:
                     st.session_state['clipboard_queue'] = []

                # --- 実行エンジンの統合 (モードONの場合) ---
                auto_plot = st.session_state.get('auto_plot_enabled', False)
                state_manager.add_debug_log(f"[DEBUG] Auto Plot Enabled: {auto_plot}, Special Mode: {is_special_mode}")

                if auto_plot and not is_special_mode:
                    # code_agent に委譲
                    code_agent.run_auto_plot_agent(
                        client=client,
                        model_id=model_id,
                        gen_config=gen_config,
                        initial_response_text=full_response,
                        available_files_map=available_files_map
                    )
                else:
                    if not auto_plot:
                         state_manager.add_debug_log("[DEBUG] Execution skipped because Auto Plot is OFF.")

            except Exception as e:
                st.error(f"Error during generation: {e}")
                state_manager.add_debug_log(str(e), "error")
            finally:
                st.session_state['is_generating'] = False
                st.rerun()

if __name__ == "__main__":
    run_chatbot_app()