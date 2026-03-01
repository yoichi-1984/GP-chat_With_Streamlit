import streamlit as st
import os
import json
import time
import io
import datetime
from PIL import ImageGrab, Image # クリップボード操作用
from streamlit_ace import st_ace

# --- Import Logic for Package vs Script execution ---
try:
    from . import config
except ImportError:
    import config

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

        # カウンターを取得（この数字が変わることで、UIのキャッシュが破棄される）
        c_key = st.session_state.get('canvas_key_counter', 0)

        # --- 1. AIモデル選択エリア ---
        st.header("AIモデル選択")
        
        env_idx = 0
        curr_env = st.session_state.get('selected_env_file')
        if curr_env in env_files:
            env_idx = env_files.index(curr_env)
            
        sel_env = st.selectbox(
            label="Environment (.env)",
            options=env_files,
            index=env_idx,
            format_func=lambda x: os.path.basename(x),
            disabled=st.session_state.get('is_generating', False),
            key=f"env_sel_{c_key}" # カウンター付きキー
        )
        if sel_env != st.session_state.get('selected_env_file'):
            st.session_state['selected_env_file'] = sel_env
            st.rerun()

        model_idx = 0
        curr_model = st.session_state.get('current_model_id')
        if curr_model in config.AVAILABLE_MODELS:
            model_idx = config.AVAILABLE_MODELS.index(curr_model)

        sel_model = st.selectbox(
            label="Target Model",
            options=config.AVAILABLE_MODELS,
            index=model_idx,
            help="Gemini 3 が 404 になる場合は 2.0 Flash 等で接続を確認してください。",
            key=f"model_sel_{c_key}" # カウンター付きキー
        )
        if sel_model != st.session_state.get('current_model_id'):
            st.session_state['current_model_id'] = sel_model
            st.rerun()

        # --- More Research Mode と UI連動・ロック機構 ---
        is_more_research = st.session_state.get('enable_more_research', False)

        effort_options = ['high', 'low']
        # More Research ON時は強制的に 'high' に見せる
        curr_effort = 'high' if is_more_research else st.session_state.get('reasoning_effort', 'high')
        effort_idx = effort_options.index(curr_effort) if curr_effort in effort_options else 0

        sel_effort = st.selectbox(
            label="Thinking Level",
            options=effort_options,
            index=effort_idx,
            disabled=is_more_research, # More Research ONならロック
            help="high: Maximum reasoning depth. low: Faster response." + (" (Locked to 'high' in More Research Mode)" if is_more_research else ""),
            key=f"effort_sel_{c_key}" # カウンター付きキー
        )
        if not is_more_research and sel_effort != st.session_state.get('reasoning_effort', 'high'):
            st.session_state['reasoning_effort'] = sel_effort
            st.rerun()

        # More Research ON時は強制的にチェックを入れる
        curr_search = True if is_more_research else st.session_state.get('enable_google_search', False)
        sel_search = st.checkbox(
            label=config.UITexts.WEB_SEARCH_LABEL,
            value=curr_search,
            disabled=is_more_research, # More Research ONならロック
            help=config.UITexts.WEB_SEARCH_HELP + (" (Forced ON in More Research Mode)" if is_more_research else ""),
            key=f"search_chk_{c_key}" # カウンター付きキー
        )
        if not is_more_research and sel_search != st.session_state.get('enable_google_search', False):
            st.session_state['enable_google_search'] = sel_search
            st.rerun()

        # More Research Mode スイッチ
        sel_more_research = st.checkbox(
            label=config.UITexts.MORE_RESEARCH_LABEL,
            value=is_more_research,
            help=config.UITexts.MORE_RESEARCH_HELP,
            key=f"more_res_chk_{c_key}" # カウンター付きキー
        )
        
        # 値が変わった瞬間に画面を再描画して、上のロック状態を即座に反映させる
        if sel_more_research != is_more_research:
            st.session_state['enable_more_research'] = sel_more_research
            # 連動するステータスもここで一気に書き換える
            if sel_more_research:
                st.session_state['reasoning_effort'] = 'high'
                st.session_state['enable_google_search'] = True
            st.rerun()
        
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

        sel_plot = st.checkbox(
            label="📈 グラフ描画・データ分析", 
            value=st.session_state.get('auto_plot_enabled', False),
            help="ONにすると、AIが生成したPythonコードを実行し、グラフ描画や計算結果を表示します。\nアップロードしたファイルは `files['name.csv']` でアクセス可能です。",
            key=f"plot_chk_{c_key}" # カウンター付きキー
        )
        if sel_plot != st.session_state.get('auto_plot_enabled'):
            st.session_state['auto_plot_enabled'] = sel_plot
            st.rerun()

        # History Management
        st.subheader(config.UITexts.HISTORY_SUBHEADER)
        
        # --- 自動履歴保存チェックボックス ---
        if 'auto_save_enabled' not in st.session_state:
            st.session_state['auto_save_enabled'] = True
            
        sel_save = st.checkbox(
            "■ 自動履歴保存", 
            value=st.session_state.get('auto_save_enabled', True),
            help="会話が2往復以上続くと、./chat_log フォルダに自動保存します。",
            key=f"save_chk_{c_key}" # カウンター付きキー
        )
        if sel_save != st.session_state.get('auto_save_enabled'):
            st.session_state['auto_save_enabled'] = sel_save
            st.rerun()
        
        # --- ローカル保存された履歴からの再開 ---
        st.caption("📂 保存済み履歴から再開")
        log_dir = "chat_log"
        if os.path.exists(log_dir):
            # jsonファイルを検索し、更新日時が新しい順にソート
            log_files = [f for f in os.listdir(log_dir) if f.endswith(".json")]
            log_files.sort(key=lambda x: os.path.getmtime(os.path.join(log_dir, x)), reverse=True)
            
            if log_files:
                selected_log = st.selectbox("履歴ファイルを選択", options=log_files, key="local_history_selector", label_visibility="collapsed")
                st.button(
                    "読み込む", 
                    key="load_local_history_btn", 
                    use_container_width=True, 
                    on_click=load_local_history, 
                    args=(selected_log,)
                )
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
                "multi_code_enabled": st.session_state.get('multi_code_enabled', False),
                "enable_more_research": st.session_state.get('enable_more_research', False),
                "enable_google_search": st.session_state.get('enable_google_search', False),
                "reasoning_effort": st.session_state.get('reasoning_effort', 'high'),
                "auto_plot_enabled": st.session_state.get('auto_plot_enabled', False)
            }
            st.download_button(
                label=config.UITexts.DOWNLOAD_HISTORY_BUTTON,
                data=json.dumps(history_data, ensure_ascii=False, indent=2),
                file_name=f"gemini_chat_{int(time.time())}.json",
                mime="application/json",
                use_container_width=True
            )

        history_uploader_key = f"history_uploader_{c_key}"
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
        
        # マルチコードチェックボックスも同様に保護
        sel_multi = st.checkbox(
            config.UITexts.MULTI_CODE_CHECKBOX, 
            value=st.session_state.get('multi_code_enabled', False),
            key=f"multi_chk_{c_key}" # カウンター付きキー
        )
        if sel_multi != st.session_state.get('multi_code_enabled'):
            st.session_state['multi_code_enabled'] = sel_multi
            st.rerun()

        def _local_handle_clear(idx):
            # メイン処理（テキストを初期値に戻す）を実行
            handle_clear(idx)
            # keyカウンターを増やしてエディタを強制再描画
            st.session_state['canvas_key_counter'] += 1

        canvases = st.session_state['python_canvases']
        if st.session_state.get('multi_code_enabled', False):
            # 上部の追加ボタン
            if len(canvases) < config.MAX_CANVASES and st.button(config.UITexts.ADD_CANVAS_BUTTON, use_container_width=True, key="add_canvas_top"):
                canvases.append(config.ACE_EDITOR_DEFAULT_CODE)
                st.rerun()
            
            for i, content in enumerate(canvases):
                st.write(f"**Canvas-{i + 1}**")
                ace_key = f"ace_{i}_{st.session_state['canvas_key_counter']}"
                updated = st_ace(value=content, key=ace_key, **config.ACE_EDITOR_SETTINGS, auto_update=True)
                if updated != content:
                    canvases[i] = updated
                
                c1, c2, c3 = st.columns(3)
                c1.button(config.UITexts.CLEAR_BUTTON, key=f"clr_{i}", on_click=_local_handle_clear, args=(i,), use_container_width=True)
                c2.button(config.UITexts.REVIEW_BUTTON, key=f"rev_{i}", on_click=handle_review, args=(i, True), use_container_width=True)
                c3.button(config.UITexts.VALIDATE_BUTTON, key=f"val_{i}", on_click=handle_validation, args=(i,), use_container_width=True)

                up_key = f"up_{i}_{st.session_state['canvas_key_counter']}"
                st.file_uploader(f"Load into Canvas-{i+1}", type=supported_types, key=up_key, on_change=handle_file_upload, args=(i, up_key))
                st.divider()

            # 下部の追加ボタン
            if len(canvases) < config.MAX_CANVASES and st.button(config.UITexts.ADD_CANVAS_BUTTON, use_container_width=True, key="add_canvas_bottom"):
                canvases.append(config.ACE_EDITOR_DEFAULT_CODE)
                st.rerun()
                
        else:
            if len(canvases) > 1:
                st.session_state['python_canvases'] = [canvases[0]]
                st.rerun()
            
            ace_key = f"ace_single_{st.session_state['canvas_key_counter']}"
            updated = st_ace(value=canvases[0], key=ace_key, **config.ACE_EDITOR_SETTINGS, auto_update=True)
            if updated != canvases[0]:
                canvases[0] = updated

            c1, c2, c3 = st.columns(3)
            c1.button(config.UITexts.CLEAR_BUTTON, key="clr_s", on_click=_local_handle_clear, args=(0,), use_container_width=True)
            c2.button(config.UITexts.REVIEW_BUTTON, key="rev_s", on_click=handle_review, args=(0, False), use_container_width=True)
            c3.button(config.UITexts.VALIDATE_BUTTON, key="val_s", on_click=handle_validation, args=(0,), use_container_width=True)
            
            up_key = f"up_s_{st.session_state['canvas_key_counter']}"
            st.file_uploader("Load into Canvas", type=supported_types, key=up_key, on_change=handle_file_upload, args=(0, up_key))
            
        st.markdown("---")
        st.markdown(
            """
            <div style="text-align: center; font-size: 12px; color: #666;">
                Powered by <a href="https://github.com/yoichi-1984/GP-chat_With_Streamlit" target="_blank" style="color: #666;">GP-Chat Ver.0.2.6</a><br>
                © yoichi-1984<br>
                Licensed under <a href="https://www.apache.org/licenses/LICENSE-2.0" target="_blank" style="color: #666;">Apache 2.0</a>
            </div>
            """,
            unsafe_allow_html=True
        )