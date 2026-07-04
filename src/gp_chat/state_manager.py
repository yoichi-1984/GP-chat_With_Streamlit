import os
import json
import time
import streamlit as st

# --- Local Module Imports ---
try:
    from gp_chat import config
except ImportError:
    import config

def add_debug_log(message, level="info"):
    """システムログをセッションステートに記録します。"""
    if "debug_logs" not in st.session_state:
        st.session_state["debug_logs"] = []
    
    timestamp = time.strftime("%H:%M:%S")
    st.session_state["debug_logs"].append(f"[{timestamp}] [{level.upper()}] {message}")
    if len(st.session_state["debug_logs"]) > 50:
        st.session_state["debug_logs"].pop(0)

def load_history(uploader_key):
    """Streamlit UploadedFile (JSON) から会話履歴とCanvasを復元します。"""
    uploaded_file = st.session_state.get(uploader_key)
    if not uploaded_file:
        return
    try:
        loaded_data = json.load(uploaded_file)
        if isinstance(loaded_data, dict) and "messages" in loaded_data:
            # 1. 添付ファイルのクリアとファイルアップローダーのリセット
            st.session_state['uploaded_file_queue'] = []
            st.session_state['clipboard_queue'] = []
            if "file_uploader_key" in st.session_state:
                st.session_state["file_uploader_key"] += 1
            else:
                st.session_state["file_uploader_key"] = 1

            st.session_state['messages'] = loaded_data["messages"]
            
            # 2. Canvas状態の復元と初期化
            if "python_canvases" in loaded_data:
                st.session_state['python_canvases'] = loaded_data["python_canvases"]
            else:
                st.session_state['python_canvases'] = [config.ACE_EDITOR_DEFAULT_CODE]
            
            st.session_state['multi_code_enabled'] = True

            # 保存された各種設定フラグを復元
            if "enable_more_research" in loaded_data:
                st.session_state['enable_more_research'] = loaded_data["enable_more_research"]
            st.session_state['enable_report_pdf'] = loaded_data.get("enable_report_pdf", False)
            st.session_state['enable_report_pptx'] = loaded_data.get("enable_report_pptx", False)
            if "enable_google_search" in loaded_data:
                st.session_state['enable_google_search'] = loaded_data["enable_google_search"]
            if "reasoning_effort" in loaded_data:
                st.session_state['reasoning_effort'] = loaded_data["reasoning_effort"]
            if "auto_plot_enabled" in loaded_data:
                st.session_state['auto_plot_enabled'] = loaded_data["auto_plot_enabled"]
            if "current_model_id" in loaded_data:
                st.session_state['current_model_id'] = loaded_data["current_model_id"]
            if "selected_env_file" in loaded_data:
                st.session_state['selected_env_file'] = loaded_data["selected_env_file"]
            if "auto_save_enabled" in loaded_data:
                st.session_state['auto_save_enabled'] = loaded_data["auto_save_enabled"]
            if "always_send_all_canvases" in loaded_data:
                st.session_state['always_send_all_canvases'] = loaded_data["always_send_all_canvases"]
            
            # --- 修正箇所 [P1]: current_report_folder の残留防止 ---
            if "current_report_folder" in loaded_data:
                st.session_state['current_report_folder'] = loaded_data["current_report_folder"]
            else:
                # 履歴データに無い場合は、前のセッションの情報が残らないようにクリアする
                if 'current_report_folder' in st.session_state:
                    del st.session_state['current_report_folder']
            # ----------------------------------------------------

            # 3. Canvas送信フラグ（canvas_enabled）とキーの再構築
            canvas_count = len(st.session_state.get('python_canvases', []))
            target_len = max(canvas_count, 5)
            if st.session_state.get('always_send_all_canvases', False):
                st.session_state['canvas_enabled'] = [True] * target_len
            else:
                # 前のセッションの canvas_enabled は引き継がず新規初期化。
                # コードが存在（デフォルト以外の意味のある内容）するCanvasのみをTrueとする。
                st.session_state['canvas_enabled'] = []
                for i in range(target_len):
                    if i < len(st.session_state['python_canvases']):
                        code = st.session_state['python_canvases'][i]
                        is_empty = (code.strip() == "" or code == config.ACE_EDITOR_DEFAULT_CODE)
                        st.session_state['canvas_enabled'].append(not is_empty)
                    else:
                        st.session_state['canvas_enabled'].append(False)

            st.session_state['toggle_keys'] = [0] * target_len
            st.session_state['always_send_all_canvases_ui'] = st.session_state.get('always_send_all_canvases', False)

            st.success(config.UITexts.HISTORY_LOADED_SUCCESS)
            st.session_state['system_role_defined'] = True
            st.session_state['canvas_key_counter'] += 1
            st.session_state['_canvas_reset_pending'] = True

            # 古い Canvas widget の state や一時ファイルアップローダー、トグルのキーをクリア
            for key in list(st.session_state.keys()):
                if key.startswith("ace_") or key.startswith("up_") or key.startswith("cvs_tog_"):
                    del st.session_state[key]

            if 'current_chat_filename' in st.session_state:
                del st.session_state['current_chat_filename']

            add_debug_log("Session restored from Uploaded JSON.")

    except Exception as e:
        st.error(f"Load failed: {e}")
        add_debug_log(f"Restore error: {e}", "error")

def load_history_from_local(filename):
    """ローカルの ./chat_log フォルダにあるJSONファイルから履歴を復元します。"""
    file_path = os.path.join("chat_log", filename)
    if not os.path.exists(file_path):
        st.error(f"File not found: {file_path}")
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            loaded_data = json.load(f)
        
        if isinstance(loaded_data, dict) and "messages" in loaded_data:
            # 1. 添付ファイルのクリアとファイルアップローダーのリセット
            st.session_state['uploaded_file_queue'] = []
            st.session_state['clipboard_queue'] = []
            if "file_uploader_key" in st.session_state:
                st.session_state["file_uploader_key"] += 1
            else:
                st.session_state["file_uploader_key"] = 1

            st.session_state['messages'] = loaded_data["messages"]
            
            # 2. Canvas状態の復元と初期化
            if "python_canvases" in loaded_data:
                st.session_state['python_canvases'] = loaded_data["python_canvases"]
            else:
                st.session_state['python_canvases'] = [config.ACE_EDITOR_DEFAULT_CODE]
            
            st.session_state['multi_code_enabled'] = True

            # 保存された各種設定フラグを復元
            if "enable_more_research" in loaded_data:
                st.session_state['enable_more_research'] = loaded_data["enable_more_research"]
            st.session_state['enable_report_pdf'] = loaded_data.get("enable_report_pdf", False)
            st.session_state['enable_report_pptx'] = loaded_data.get("enable_report_pptx", False)
            if "enable_google_search" in loaded_data:
                st.session_state['enable_google_search'] = loaded_data["enable_google_search"]
            if "reasoning_effort" in loaded_data:
                st.session_state['reasoning_effort'] = loaded_data["reasoning_effort"]
            if "auto_plot_enabled" in loaded_data:
                st.session_state['auto_plot_enabled'] = loaded_data["auto_plot_enabled"]
            if "current_model_id" in loaded_data:
                st.session_state['current_model_id'] = loaded_data["current_model_id"]
            if "selected_env_file" in loaded_data:
                st.session_state['selected_env_file'] = loaded_data["selected_env_file"]
            if "auto_save_enabled" in loaded_data:
                st.session_state['auto_save_enabled'] = loaded_data["auto_save_enabled"]
            if "always_send_all_canvases" in loaded_data:
                st.session_state['always_send_all_canvases'] = loaded_data["always_send_all_canvases"]

            # 3. Canvas送信フラグ（canvas_enabled）とキーの再構築
            canvas_count = len(st.session_state.get('python_canvases', []))
            target_len = max(canvas_count, 5)
            if st.session_state.get('always_send_all_canvases', False):
                st.session_state['canvas_enabled'] = [True] * target_len
            else:
                # 前のセッションの canvas_enabled は引き継がず新規初期化。
                # コードが存在（デフォルト以外の意味のある内容）するCanvasのみをTrueとする。
                st.session_state['canvas_enabled'] = []
                for i in range(target_len):
                    if i < len(st.session_state['python_canvases']):
                        code = st.session_state['python_canvases'][i]
                        is_empty = (code.strip() == "" or code == config.ACE_EDITOR_DEFAULT_CODE)
                        st.session_state['canvas_enabled'].append(not is_empty)
                    else:
                        st.session_state['canvas_enabled'].append(False)

            st.session_state['toggle_keys'] = [0] * target_len
            st.session_state['always_send_all_canvases_ui'] = st.session_state.get('always_send_all_canvases', False)

            st.success(f"Loaded: {filename}")
            st.session_state['system_role_defined'] = True
            st.session_state['canvas_key_counter'] += 1
            st.session_state['_canvas_reset_pending'] = True

            # 古い Canvas widget の state や一時ファイルアップローダー、トグルのキーをクリア
            for key in list(st.session_state.keys()):
                if key.startswith("ace_") or key.startswith("up_") or key.startswith("cvs_tog_"):
                    del st.session_state[key]

            st.session_state['current_chat_filename'] = filename
            st.session_state['current_report_folder'] = loaded_data.get("current_report_folder", os.path.splitext(filename)[0])

            add_debug_log(f"Session restored from local file: {filename}")
            
    except Exception as e:
        st.error(f"Load failed: {e}")
        add_debug_log(f"Restore error: {e}", "error")

def recover_interrupted_session():
    """
    中断されたセッション（ユーザー発言で終わっている状態）を検知し、
    履歴から削除してテキストをドラフト領域に復元します。
    """
    messages = st.session_state.get('messages', [])
    
    if messages and messages[-1]["role"] == "user":
        last_user_msg = messages.pop()
        content = last_user_msg["content"]
        
        st.session_state['draft_input'] = content
        st.session_state['is_generating'] = False
        
        add_debug_log("Detected interrupted session. Restored draft text.")
        return True
    return False