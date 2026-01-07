import streamlit as st
import os
import json
import time
from streamlit_ace import st_ace
from . import config

def render_sidebar(supported_types, env_files, load_history, handle_clear, handle_review, handle_validation, handle_file_upload):
    """Renders the sidebar with Gemini 3 specific options and model selector."""
    with st.sidebar:
        st.header("AIモデル選択")
        
        def on_env_change():
            # Reset conversation but keep settings
            for key, value in config.SESSION_STATE_DEFAULTS.items():
                if key in ['reasoning_effort', 'canvas_key_counter', 'current_model_id', 'enable_google_search', 'uploaded_file_queue']:
                    continue
                st.session_state[key] = value.copy() if isinstance(value, (dict, list)) else value
            st.session_state['canvas_key_counter'] += 1

        st.selectbox(
            label="Environment (.env)",
            options=env_files,
            format_func=lambda x: os.path.basename(x),
            key='selected_env_file',
            on_change=on_env_change,
            disabled=st.session_state.get('is_generating', False)
        )

        # モデルを直接UIから選択できるように追加
        st.selectbox(
            label="Target Model",
            options=config.AVAILABLE_MODELS,
            key='current_model_id',
            help="Gemini 3 が 404 になる場合は 2.0 Flash 等で接続を確認してください。"
        )

        st.selectbox(
            label="Thinking Level",
            options=['high', 'low'],
            key='reasoning_effort',
            help="high: Maximum reasoning depth. low: Faster response."
        )

        # Web検索 (Grounding) チェックボックス
        st.checkbox(
            label=config.UITexts.WEB_SEARCH_LABEL,
            key='enable_google_search',
            help=config.UITexts.WEB_SEARCH_HELP
        )
        
        # --- ファイル取り込み機能 ---
        st.divider()
        st.header(config.UITexts.FILE_UPLOAD_HEADER)
        
        # キューの初期化（未定義の場合の安全策）
        if 'uploaded_file_queue' not in st.session_state:
            st.session_state['uploaded_file_queue'] = []

        # ファイルアップローダーのリセット用キー管理
        if "file_uploader_key" not in st.session_state:
            st.session_state["file_uploader_key"] = 0
            
        uploader_key = f"file_uploader_{st.session_state['file_uploader_key']}"

        # 許可する拡張子をここで明示的に定義（Configの更新漏れ対策）
        # PDF, Word, 画像, テキスト各種を許可
        ALLOWED_EXTENSIONS = ["png", "jpg", "jpeg", "bmp", "gif", "pdf", "docx", "txt", "md", "py", "js", "json", "csv"]

        # アップローダーの表示 (コールバックは廃止し、直接同期する)
        uploaded_files = st.file_uploader(
            label=config.UITexts.FILE_UPLOAD_LABEL,
            type=ALLOWED_EXTENSIONS,
            accept_multiple_files=True,
            help=config.UITexts.FILE_UPLOAD_HELP,
            key=uploader_key
        )
        
        # --- DEBUG: サイドバーでのファイル認識状態 ---
        if uploaded_files:
            st.sidebar.markdown("--- 🛠 DEBUG INFO ---")
            st.sidebar.text(f"Widget Files: {len(uploaded_files)}")
            for f in uploaded_files:
                st.sidebar.text(f"- {f.name} ({f.size}B)")
        # ----------------------------------------
        
        # セッションステートへの同期（シンプルかつ確実に）
        if uploaded_files:
            st.session_state['uploaded_file_queue'] = uploaded_files
            file_count = len(uploaded_files)
            st.info(f"送信待ちファイル: {file_count} 件\nチャットを送信するとAIに渡されます。")
        else:
            st.session_state['uploaded_file_queue'] = []


        st.divider()

        def handle_full_reset():
            for key, value in config.SESSION_STATE_DEFAULTS.items():
                st.session_state[key] = value.copy() if isinstance(value, (dict, list)) else value
            st.session_state['canvas_key_counter'] += 1

        st.header(config.UITexts.SIDEBAR_HEADER)
        if st.button(config.UITexts.RESET_BUTTON_LABEL, use_container_width=True, on_click=handle_full_reset):
            st.rerun()

        st.info(config.UITexts.CODEX_MINI_INFO)

        # History Management
        st.subheader(config.UITexts.HISTORY_SUBHEADER)
        if st.session_state.get('messages'):
            history_data = {
                "messages": st.session_state['messages'],
                "python_canvases": st.session_state['python_canvases'],
                "multi_code_enabled": st.session_state['multi_code_enabled']
            }
            st.download_button(
                label=config.UITexts.DOWNLOAD_HISTORY_BUTTON,
                data=json.dumps(history_data, ensure_ascii=False, indent=2),
                file_name=f"gemini_chat_{int(time.time())}.json",
                mime="application/json",
                use_container_width=True
            )

        history_uploader_key = f"history_uploader_{st.session_state['canvas_key_counter']}"
        st.file_uploader(label=config.UITexts.UPLOAD_HISTORY_LABEL, type="json", key=history_uploader_key, on_change=load_history, args=(history_uploader_key,))
        
        # Editor (Canvas) Management
        st.subheader(config.UITexts.EDITOR_SUBHEADER)
        multi_code_enabled = st.checkbox(config.UITexts.MULTI_CODE_CHECKBOX, value=st.session_state['multi_code_enabled'])
        if multi_code_enabled != st.session_state['multi_code_enabled']:
            st.session_state['multi_code_enabled'] = multi_code_enabled
            st.rerun()

        canvases = st.session_state['python_canvases']
        if st.session_state['multi_code_enabled']:
            if len(canvases) < config.MAX_CANVASES and st.button(config.UITexts.ADD_CANVAS_BUTTON, use_container_width=True):
                canvases.append(config.ACE_EDITOR_DEFAULT_CODE)
                st.rerun()
            
            for i, content in enumerate(canvases):
                st.write(f"**Canvas-{i + 1}**")
                ace_key = f"ace_{i}_{st.session_state['canvas_key_counter']}"
                updated = st_ace(value=content, key=ace_key, **config.ACE_EDITOR_SETTINGS, auto_update=True)
                if updated != content:
                    canvases[i] = updated
                
                c1, c2, c3 = st.columns(3)
                c1.button("クリア", key=f"clr_{i}", on_click=handle_clear, args=(i,), use_container_width=True)
                c2.button("レビュー", key=f"rev_{i}", on_click=handle_review, args=(i, True), use_container_width=True)
                c3.button("検証", key=f"val_{i}", on_click=handle_validation, args=(i,), use_container_width=True)

                up_key = f"up_{i}_{st.session_state['canvas_key_counter']}"
                st.file_uploader(f"Load into Canvas-{i+1}", type=supported_types, key=up_key, on_change=handle_file_upload, args=(i, up_key))
                st.divider()
        else:
            if len(canvases) > 1:
                st.session_state['python_canvases'] = [canvases[0]]
                st.rerun()
            
            ace_key = f"ace_single_{st.session_state['canvas_key_counter']}"
            updated = st_ace(value=canvases[0], key=ace_key, **config.ACE_EDITOR_SETTINGS, auto_update=True)
            if updated != canvases[0]:
                canvases[0] = updated

            c1, c2, c3 = st.columns(3)
            c1.button("Clear", key="clr_s", on_click=handle_clear, args=(0,), use_container_width=True)
            c2.button("Review", key="rev_s", on_click=handle_review, args=(0, False), use_container_width=True)
            c3.button("Validate", key="val_s", on_click=handle_validation, args=(0,), use_container_width=True)
            
            up_key = f"up_s_{st.session_state['canvas_key_counter']}"
            st.file_uploader("Load into Canvas", type=supported_types, key=up_key, on_change=handle_file_upload, args=(0, up_key))
            