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
            st.session_state['messages'] = loaded_data["messages"]
            if "python_canvases" in loaded_data:
                st.session_state['python_canvases'] = loaded_data["python_canvases"]
            
            if "multi_code_enabled" in loaded_data:
                st.session_state['multi_code_enabled'] = loaded_data["multi_code_enabled"]

            # 保存された各種設定フラグを復元
            if "enable_more_research" in loaded_data:
                st.session_state['enable_more_research'] = loaded_data["enable_more_research"]
            if "enable_google_search" in loaded_data:
                st.session_state['enable_google_search'] = loaded_data["enable_google_search"]
            if "reasoning_effort" in loaded_data:
                st.session_state['reasoning_effort'] = loaded_data["reasoning_effort"]
            if "auto_plot_enabled" in loaded_data:
                st.session_state['auto_plot_enabled'] = loaded_data["auto_plot_enabled"]

            st.success(config.UITexts.HISTORY_LOADED_SUCCESS)
            st.session_state['system_role_defined'] = True
            st.session_state['canvas_key_counter'] += 1
            
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
            st.session_state['messages'] = loaded_data["messages"]
            if "python_canvases" in loaded_data:
                st.session_state['python_canvases'] = loaded_data["python_canvases"]
            
            if "multi_code_enabled" in loaded_data:
                st.session_state['multi_code_enabled'] = loaded_data["multi_code_enabled"]

            # 保存された各種設定フラグを復元
            if "enable_more_research" in loaded_data:
                st.session_state['enable_more_research'] = loaded_data["enable_more_research"]
            if "enable_google_search" in loaded_data:
                st.session_state['enable_google_search'] = loaded_data["enable_google_search"]
            if "reasoning_effort" in loaded_data:
                st.session_state['reasoning_effort'] = loaded_data["reasoning_effort"]
            if "auto_plot_enabled" in loaded_data:
                st.session_state['auto_plot_enabled'] = loaded_data["auto_plot_enabled"]

            st.success(f"Loaded: {filename}")
            st.session_state['system_role_defined'] = True
            st.session_state['canvas_key_counter'] += 1
            
            st.session_state['current_chat_filename'] = filename
            
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