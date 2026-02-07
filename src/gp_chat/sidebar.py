# sidebar.py:
import streamlit as st
import os
import json
import time
import io
import datetime
from PIL import ImageGrab, Image # クリップボード操作用
from streamlit_ace import st_ace
from . import config

# --- 擬似的なアップロードファイルクラス ---
class VirtualUploadedFile:
    """クリップボードの画像をStreamlitのUploadedFileのように振る舞わせるクラス"""
    def __init__(self, file_bytes, name, mime_type):
        self._data = file_bytes
        self.name = name
        self.type = mime_type
        self.size = len(file_bytes)
    
    def getvalue(self):
        return self._data

def render_sidebar(supported_types, env_files, load_history, load_local_history, handle_clear, handle_review, handle_validation, handle_file_upload):
    """Renders the sidebar with Gemini 3 specific options and model selector."""
    with st.sidebar:
        # --- CSS Style Injection ---
        # ファイルアップローダーの「Limit 200MB...」などの補足テキストを非表示にしてスッキリさせる
        st.markdown(
            """
            <style>
                [data-testid="stFileUploader"] small {
                    display: none;
                }
            </style>
            """,
            unsafe_allow_html=True
        )

        # --- 1. AIモデル選択エリア ---
        st.header("AIモデル選択")
        
        st.selectbox(
            label="Environment (.env)",
            options=env_files,
            format_func=lambda x: os.path.basename(x),
            key='selected_env_file',
            disabled=st.session_state.get('is_generating', False)
        )

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

        st.checkbox(
            label=config.UITexts.WEB_SEARCH_LABEL,
            key='enable_google_search',
            help=config.UITexts.WEB_SEARCH_HELP
        )
        
        st.divider()

        # --- 2. 設定・履歴エリア ---
        def handle_full_reset():
            keys_to_keep = ['selected_env_file']
            for key, value in config.SESSION_STATE_DEFAULTS.items():
                if key in keys_to_keep:
                    continue
                st.session_state[key] = value.copy() if isinstance(value, (dict, list)) else value
            
            st.session_state['canvas_key_counter'] += 1
            if "file_uploader_key" in st.session_state:
                st.session_state["file_uploader_key"] += 1
            else:
                st.session_state["file_uploader_key"] = 1
            
            # クリップボードキューもリセット
            if 'clipboard_queue' in st.session_state:
                st.session_state['clipboard_queue'] = []
            
            # 自動保存用のファイル名情報もリセット
            if 'current_chat_filename' in st.session_state:
                del st.session_state['current_chat_filename']

        st.header(config.UITexts.SIDEBAR_HEADER)
        if st.button(config.UITexts.RESET_BUTTON_LABEL, use_container_width=True, on_click=handle_full_reset):
            st.rerun()

        # --- 追加機能: グラフ描画・データ分析モード ---
        if 'auto_plot_enabled' not in st.session_state:
            st.session_state['auto_plot_enabled'] = False

        st.checkbox(
            label="📈 グラフ描画・データ分析（β機能）", 
            key='auto_plot_enabled', 
            help="ONにすると、AIが生成したPythonコードを実行し、グラフ描画や計算結果を表示します。\nアップロードしたファイルは `files['name.csv']` でアクセス可能です。"
        )

        # History Management
        st.subheader(config.UITexts.HISTORY_SUBHEADER)
        
        # --- 自動履歴保存チェックボックス ---
        if 'auto_save_enabled' not in st.session_state:
            st.session_state['auto_save_enabled'] = True
            
        st.checkbox("■ 自動履歴保存", key='auto_save_enabled', help="会話が2往復以上続くと、./chat_log フォルダに自動保存します。")
        
        # --- ローカル保存された履歴からの再開 ---
        st.caption("📂 保存済み履歴から再開")
        log_dir = "chat_log"
        if os.path.exists(log_dir):
            # jsonファイルを検索し、更新日時が新しい順にソート
            log_files = [f for f in os.listdir(log_dir) if f.endswith(".json")]
            log_files.sort(key=lambda x: os.path.getmtime(os.path.join(log_dir, x)), reverse=True)
            
            if log_files:
                selected_log = st.selectbox("履歴ファイルを選択", options=log_files, key="local_history_selector", label_visibility="collapsed")
                if st.button("読み込む", key="load_local_history_btn", use_container_width=True):
                    load_local_history(selected_log)
            else:
                st.caption("（履歴ファイルはありません）")
        else:
             st.caption("（履歴フォルダはありません）")

        # --- 既存機能: ファイルアップロードによる再開 ---
        st.caption("📤 JSONファイルから再開")
        
        # 履歴ダウンロードボタン
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
        st.file_uploader(label=config.UITexts.UPLOAD_HISTORY_LABEL, type="json", key=history_uploader_key, on_change=load_history, args=(history_uploader_key,), label_visibility="collapsed")

        st.divider()

        # --- 3. ファイル添付エリア ---
        st.header(config.UITexts.FILE_UPLOAD_HEADER)
        
        if 'uploaded_file_queue' not in st.session_state:
            st.session_state['uploaded_file_queue'] = []
        if 'clipboard_queue' not in st.session_state:
            st.session_state['clipboard_queue'] = []

        if "file_uploader_key" not in st.session_state:
            st.session_state["file_uploader_key"] = 0
            
        uploader_key = f"file_uploader_{st.session_state['file_uploader_key']}"

        ALLOWED_EXTENSIONS = ["png", "jpg", "jpeg", "bmp", "gif", "pdf", "docx", "pptx", "ppt", "txt", "md", "py", "js", "json", "csv"]
        uploaded_files = st.file_uploader(
            label=config.UITexts.FILE_UPLOAD_LABEL,
            type=ALLOWED_EXTENSIONS,
            accept_multiple_files=True,
            help=config.UITexts.FILE_UPLOAD_HELP,
            key=uploader_key
        )
        
        if uploaded_files:
            st.session_state['uploaded_file_queue'] = uploaded_files
        else:
            st.session_state['uploaded_file_queue'] = []

        if st.button("📋 クリップボード画像を追加", use_container_width=True, help="Win+Shift+S等でコピーした画像を読み込みます"):
            try:
                img = ImageGrab.grabclipboard()
                if isinstance(img, Image.Image):
                    buf = io.BytesIO()
                    img.save(buf, format='PNG')
                    byte_data = buf.getvalue()
                    
                    timestamp = datetime.datetime.now().strftime("%H%M%S")
                    filename = f"clipboard_{timestamp}.png"
                    
                    virtual_file = VirtualUploadedFile(byte_data, filename, "image/png")
                    st.session_state['clipboard_queue'].append(virtual_file)
                    st.toast(f"画像を追加しました: {filename}", icon="✅")
                elif img is None:
                    st.toast("クリップボードに画像がありません", icon="⚠️")
                else:
                    st.toast("対応していないクリップボード形式です", icon="⚠️")
            except Exception as e:
                st.error(f"Clipboard Error: {e}")

        total_files = len(st.session_state['uploaded_file_queue']) + len(st.session_state['clipboard_queue'])
        
        if total_files > 0:
            st.markdown(f"**送信待ち: {total_files} 件**")
            
            if st.session_state['clipboard_queue']:
                st.caption("クリップボード取得分:")
                for i, vfile in enumerate(st.session_state['clipboard_queue']):
                    col_del, col_name = st.columns([1, 5])
                    with col_del:
                        if st.button("❌", key=f"del_clip_{i}"):
                            st.session_state['clipboard_queue'].pop(i)
                            st.rerun()
                    with col_name:
                        st.text(vfile.name)
        else:
            st.caption("ファイルは選択されていません")

        st.divider()

        # --- 4. コードエディタ (Canvas) エリア ---
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
            
        st.markdown("---")
        st.markdown(
            """
            <div style="text-align: center; font-size: 12px; color: #666;">
                Powered by <a href="https://github.com/yoichi-1984/GP-chat_With_Streamlit" target="_blank" style="color: #666;">GP-Chat</a><br>
                © yoichi-1984<br>
                Licensed under <a href="https://www.apache.org/licenses/LICENSE-2.0" target="_blank" style="color: #666;">Apache 2.0</a>
            </div>
            """,
            unsafe_allow_html=True
        )
        