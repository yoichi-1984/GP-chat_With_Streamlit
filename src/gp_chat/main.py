# main.py:
import os
import json
import sys
import time
import traceback

import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai import errors
from streamlit_ace import st_ace

# --- Local Module Imports ---
try:
    from gp_chat import config
    from gp_chat import utils
    from gp_chat import sidebar
except ImportError:
    import config
    import utils
    import sidebar

# --- Helper Functions ---

def add_debug_log(message, level="info"):
    """システムログをセッションステートに記録します。"""
    if "debug_logs" not in st.session_state:
        st.session_state["debug_logs"] = []
    
    timestamp = time.strftime("%H:%M:%S")
    st.session_state["debug_logs"].append(f"[{timestamp}] [{level.upper()}] {message}")
    if len(st.session_state["debug_logs"]) > 50:
        st.session_state["debug_logs"].pop(0)

def load_history(uploader_key):
    """JSONから会話履歴とCanvasを復元します。"""
    uploaded_file = st.session_state.get(uploader_key)
    if not uploaded_file:
        return
    try:
        loaded_data = json.load(uploaded_file)
        if isinstance(loaded_data, dict) and "messages" in loaded_data:
            st.session_state['messages'] = loaded_data["messages"]
            if "python_canvases" in loaded_data:
                st.session_state['python_canvases'] = loaded_data["python_canvases"]
            
            if "multi_code_enabled" in loaded_data:
                st.session_state['multi_code_enabled'] = loaded_data["multi_code_enabled"]

            st.success(config.UITexts.HISTORY_LOADED_SUCCESS)
            st.session_state['system_role_defined'] = True
            st.session_state['canvas_key_counter'] += 1
            add_debug_log("Session restored from JSON.")

    except Exception as e:
        st.error(f"Load failed: {e}")
        add_debug_log(f"Restore error: {e}", "error")

def recover_interrupted_session():
    """
    中断されたセッション（ユーザー発言で終わっている状態）を検知し、
    履歴から削除してテキストをドラフト領域に復元します。
    """
    messages = st.session_state.get('messages', [])
    
    # 最後のメッセージがユーザーで、かつ生成中フラグが立っていない（または中断後のリラン）場合
    if messages and messages[-1]["role"] == "user":
        last_user_msg = messages.pop() # 履歴から削除
        content = last_user_msg["content"]
        
        # テキストをドラフト領域に復元
        st.session_state['draft_input'] = content
        st.session_state['is_generating'] = False # 生成フラグをリセット
        
        add_debug_log("Detected interrupted session. Restored draft text.")
        return True
    return False

# --- Streamlit Application ---

def run_chatbot_app():
    st.set_page_config(page_title=config.UITexts.APP_TITLE, layout="wide")
    st.title(config.UITexts.APP_TITLE)
    
    if "debug_logs" not in st.session_state:
        st.session_state["debug_logs"] = []

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

    # --- 機能改善: 中断リカバリーチェック ---
    # アプリのリラン時（停止ボタン押下後など）に、完了していないユーザーメッセージがあれば復元
    # generate完了後にフラグを落とすため、ここに到達した時点で generating=False かつ Last=User なら中断されたと判断
    if st.session_state.get('messages') and st.session_state['messages'][-1]['role'] == 'user' and not st.session_state.get('is_generating'):
        recover_interrupted_session()
        st.rerun()

    sidebar.render_sidebar(
        supported_extensions, env_files, load_history, 
        lambda i: st.session_state['python_canvases'].__setitem__(i, config.ACE_EDITOR_DEFAULT_CODE),
        lambda i, m: (st.session_state['messages'].append({"role": "user", "content": config.UITexts.REVIEW_PROMPT_MULTI.format(i=i+1) if m else config.UITexts.REVIEW_PROMPT_SINGLE}), st.session_state.__setitem__('is_generating', True)),
        lambda i: utils.run_pylint_validation(st.session_state['python_canvases'][i], i, PROMPTS),
        lambda i, k: st.session_state['python_canvases'].__setitem__(i, st.session_state[k].getvalue().decode("utf-8")) if st.session_state.get(k) else None
    )
    
    # --- .env ロードと Client 初期化 ---
    load_dotenv(dotenv_path=st.session_state.get('selected_env_file', env_files[0]), override=True)
    
    project_id = os.getenv(config.GCP_PROJECT_ID_NAME)
    location = os.getenv(config.GCP_LOCATION_NAME, "global") 
    model_id = st.session_state.get('current_model_id', os.getenv(config.GEMINI_MODEL_ID_NAME, "gemini-3-pro-preview"))
    
    # 定数値の定義
    INPUT_LIMIT = 1000000
    OUTPUT_LIMIT = 65536
    max_tokens_val = min(int(os.getenv("MAX_TOKEN", "65536")), OUTPUT_LIMIT)

    try:
        client = genai.Client(vertexai=True, project=project_id, location=location)
    except Exception as e:
        st.error(f"Client init error: {e}")
        st.stop()

    st.caption(f"Backend: {model_id} | Location: {location}")

    # デバッグログ表示
    with st.expander("🛠 システムログ", expanded=False):
        for log in reversed(st.session_state["debug_logs"]):
            st.text(log)

    # システムプロンプト設定
    if not st.session_state['system_role_defined']:
        st.subheader("AIの役割を設定（デフォルトでも、変更してもどちらでもOK）")
        role = st.text_area("System Role", value=PROMPTS.get("system", {}).get("text", ""), height=200)
        if st.button("チャットを開始", type="primary"):
            st.session_state['messages'] = [{"role": "system", "content": role}]
            st.session_state['system_role_defined'] = True
            st.rerun()
        st.stop()

    # 会話表示
    for msg in st.session_state['messages']:
        if msg["role"] != "system":
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                
                # Groundingソースの表示（履歴にある場合）
                if "grounding_metadata" in msg and msg["grounding_metadata"]:
                    with st.expander("🔎 検索ソース (Grounding)"):
                        st.json(msg["grounding_metadata"])

                # トークン使用量の詳細表示
                if msg["role"] == "assistant" and "usage" in msg:
                    u = msg["usage"]
                    in_p = (u['input_tokens'] / INPUT_LIMIT) * 100
                    out_p = (u['output_tokens'] / OUTPUT_LIMIT) * 100
                    
                    st.caption(
                        f"📊 **トークン使用量詳細**\n\n"
                        f"📥 **Input (Context):** {u['input_tokens']:,} / {INPUT_LIMIT:,} ({in_p:.2f}%)\n"
                        f"📤 **Output (Response):** {u['output_tokens']:,} / {OUTPUT_LIMIT:,} ({out_p:.2f}%)"
                    )

    # セッション累計
    if st.session_state['total_usage']['total_tokens'] > 0:
        st.divider()
        st.caption(f"🏁 セッション累計使用トークン: {st.session_state['total_usage']['total_tokens']:,}")

    # --- 機能改善: 入力エリアの分岐 (通常 vs ドラフト復元モード) ---
    if 'draft_input' in st.session_state:
        # --- リカバリーモード (復元されたテキストの編集) ---
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
        # --- 通常モード ---
        if prompt := st.chat_input("指示を入力...", disabled=st.session_state['is_generating']):
            st.session_state['messages'].append({"role": "user", "content": prompt})
            st.session_state['is_generating'] = True
            st.rerun()

    # 生成ロジック
    if st.session_state['is_generating']:
        # --- 機能改善: 停止ボタンの表示 ---
        # 生成中はチャット欄が無効化されるため、ここに停止ボタンを表示します。
        st.markdown("---")
        c_stop, c_info = st.columns([1, 5])
        with c_stop:
            if st.button("■ 送信取り消し", key="stop_generating_btn", type="primary"):
                # ボタンが押されるとスクリプトはここで再実行(Rerun)されます。
                # 生成処理は中断されます。
                # Rerun後、上記の「中断リカバリーチェック」が作動し、テキストが復元されます。
                st.session_state['is_generating'] = False
                st.rerun()
        with c_info:
            st.info("生成中... 「送信取り消し」を押すと中断し、テキストを復元します。")

        with st.chat_message("assistant"):
            # --- 機能改善③: Thinking & Grounding Process 表示エリア ---
            thought_area_container = st.empty()
            with thought_area_container.container():
                thought_status = st.status("思考プロセス (Thinking Process)...", expanded=False)
                thought_placeholder = thought_status.empty()
            
            text_placeholder = st.empty()
            full_response = ""
            
            # 思考ログ（Thoughtテキスト + 検索アクション）をまとめる文字列
            full_thought_log = ""
            
            usage_metadata = None 
            grounding_chunks = []
            
            # --- 特殊生成モード（Pylint検証等）か通常モードかの判定 ---
            is_special_mode = 'special_generation_messages' in st.session_state and st.session_state['special_generation_messages']
            
            # リクエストに使用するメッセージリストを決定
            target_messages = []
            if is_special_mode:
                target_messages = st.session_state['special_generation_messages']
                add_debug_log("Generating response for SPECIAL validation request.")
            else:
                target_messages = st.session_state['messages']

            chat_contents = []
            system_instruction = ""
            for m in target_messages:
                if m["role"] == "system":
                    system_instruction = m["content"]
                else:
                    chat_contents.append(types.Content(role=m["role"], parts=[types.Part.from_text(text=m["content"])]))
            
            # --- ファイル添付処理 (今回のターン) ---
            file_attachments_meta = []
            
            # --- 機能改善: キューの結合 (アップロード分 + クリップボード分) ---
            queue_files = st.session_state.get('uploaded_file_queue', []) + st.session_state.get('clipboard_queue', [])
            
            if not is_special_mode and queue_files:
                file_parts, file_meta = utils.process_uploaded_files_for_gemini(queue_files)
                
                if file_parts and chat_contents:
                    # ユーザーの最後のメッセージ（直前の入力）にパーツを追加
                    last_user_msg_content = chat_contents[-1]
                    if last_user_msg_content.role == "user":
                        # テキストパーツの前にファイルパーツを挿入
                        last_user_msg_content.parts = file_parts + last_user_msg_content.parts
                        file_attachments_meta = file_meta
                        add_debug_log(f"Attached {len(file_parts)} files to the request.")

            # Canvasコンテキストの挿入
            if not is_special_mode:
                context_parts = []
                for i, code in enumerate(st.session_state['python_canvases']):
                    if code.strip() and code != config.ACE_EDITOR_DEFAULT_CODE:
                        context_parts.append(types.Part.from_text(text=f"\n[Canvas-{i+1}]\n```python\n{code}\n```"))
                
                if context_parts and chat_contents:
                    chat_contents[-1].parts = context_parts + chat_contents[-1].parts

            effort = st.session_state.get('reasoning_effort', 'high')
            t_level = types.ThinkingLevel.HIGH if effort == 'high' else types.ThinkingLevel.LOW

            # --- Tool設定 (Google Search) ---
            tools_config = []
            if st.session_state.get('enable_google_search', False) and not is_special_mode:
                add_debug_log("Google Search Tool Enabled.")
                tools_config = [types.Tool(google_search=types.GoogleSearch())]

            try:
                add_debug_log(f"Requesting stream: {model_id} via {location} (max_output={max_tokens_val})")
                
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

                    # --- Grounding Metadata (検索アクション) の処理 ---
                    if cand.grounding_metadata:
                        grounding_chunks.append(cand.grounding_metadata)
                        
                        if cand.grounding_metadata.web_search_queries:
                            queries = cand.grounding_metadata.web_search_queries
                            add_debug_log(f"[Grounding] Queries detected: {queries}")
                            for query in queries:
                                action_text = f"\n\n🔍 **Action (Google Search):** `{query}`\n\n"
                                full_thought_log += action_text
                                thought_placeholder.markdown(full_thought_log)

                    # --- Content Parts の処理 ---
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
                
                # Grounding情報の統合と表示
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
                    
                    if final_grounding_metadata:
                        with st.expander("🔎 検索ソース (Grounding)"):
                            st.json(final_grounding_metadata)

                add_debug_log("Stream successfully finished.")

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
                
                # --- 履歴への保存処理 ---
                if is_special_mode:
                    for m in target_messages:
                        if m["role"] == "user":
                            st.session_state['messages'].append(m)
                    
                    st.session_state['messages'].append(assistant_msg)
                    del st.session_state['special_generation_messages']
                    add_debug_log("Special validation messages merged to history.")
                else:
                    st.session_state['messages'].append(assistant_msg)
                
                # --- 機能改善: 送信待ちファイル & クリップボードキューのクリア ---
                if 'uploaded_file_queue' in st.session_state:
                     st.session_state['uploaded_file_queue'] = []
                if 'clipboard_queue' in st.session_state:
                     st.session_state['clipboard_queue'] = []

            except Exception as e:
                st.error(f"Error during generation: {e}")
                add_debug_log(str(e), "error")
            finally:
                st.session_state['is_generating'] = False
                st.rerun()

if __name__ == "__main__":
    run_chatbot_app()
    