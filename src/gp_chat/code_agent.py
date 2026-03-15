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
except ImportError:
    import execution_engine
    import state_manager
    import utils

def run_auto_plot_agent(client, model_id, gen_config, initial_response_text, available_files_map):
    """
    AIの回答からPythonコードを抽出し、実行し、エラーがあれば自動修正するエージェントループ。
    """
    max_retries = 2
    retry_count = 0
    current_response_text = initial_response_text
    
    # 内部の試行錯誤でUIのチャット履歴を汚染しないよう、内部履歴を作成
    internal_history = [m for m in st.session_state.get('messages', []) if m.get("role") != "system"]
    
    # UIの描画領域をループ外で確保（st.emptyを使用し、リトライ時にUIをクリーンに上書きする）
    agent_ui_placeholder = st.empty()

    while retry_count <= max_retries:
        # 正規表現: 大文字小文字区別なし、空白と改行を柔軟に許容
        code_blocks = re.findall(r"```python\s*(.*?)\s*```", current_response_text, re.DOTALL | re.IGNORECASE)
        state_manager.add_debug_log(f"[DEBUG] Retry:{retry_count} Found {len(code_blocks)} Python code blocks.") 
        
        target_code = None
        for code in reversed(code_blocks):
            if any(k in code for k in ["plt.", "fig", "matplotlib", "pd.", "print(", "dataframe"]):
                target_code = code
                break
        
        # コードが見つからなかった場合のハンドリング
        if not target_code:
            state_manager.add_debug_log("[DEBUG] No suitable target code found.")
            # リトライ中にAIがコードを返し忘れた場合はエラーとして扱う
            if retry_count > 0:
                with agent_ui_placeholder.container():
                    st.error("AIが修正コードを提示しなかったため、自動修正を中断しました。")
                    st.session_state['messages'].append({
                        "role": "assistant",
                        "content": f"❌ Auto-fix failed: AI did not provide a valid Python code block in attempt {retry_count}.\n\n{current_response_text}"
                    })
            break

        state_manager.add_debug_log(f"[DEBUG] Retry:{retry_count} Executing code...") 
        
        # プレースホルダー内にコンテナを展開 (ループのたびに前回の表示が上書きされ、画面が間延びしない)
        with agent_ui_placeholder.container():
            with st.chat_message("assistant"):
                status_label = "⚙️ コードを実行中..." if retry_count == 0 else f"⚙️ コードを修正して再実行中 (Retry {retry_count})..."
                with st.status(status_label, expanded=True) as exec_status:
                    try:
                        # サンドボックス実行
                        stdout_str, figures = execution_engine.execute_user_code(
                            target_code,
                            available_files_map, 
                            st.session_state.get('python_canvases', [])
                        )
                        
                        is_error = "Traceback (most recent call last):" in stdout_str
                        
                        # --- 成功時 または リトライ上限到達時 ---
                        if not is_error or retry_count >= max_retries:
                            state_manager.add_debug_log(f"[DEBUG] Execution finished (Error: {is_error}). Stdout len: {len(stdout_str)}, Figures: {len(figures)}") 

                            images_b64 = []
                            for fig_data in figures:
                                try:
                                    b64_str = base64.b64encode(fig_data.getvalue()).decode('utf-8')
                                    images_b64.append(b64_str)
                                except Exception as e:
                                    state_manager.add_debug_log(f"Image encode error: {e}", "error")

                            # UIへの表示
                            if stdout_str:
                                st.caption("📄 標準出力:")
                                st.text(stdout_str)
                            
                            if images_b64:
                                st.caption(f"📊 生成されたグラフ ({len(images_b64)}枚):")
                                for img_b64 in images_b64:
                                    st.image(base64.b64decode(img_b64), use_container_width=True)

                            # 修正が行われた場合、AIが生成した「修正後のコード」をメイン履歴に追記してユーザーに見せる
                            if retry_count > 0:
                                st.session_state['messages'].append({
                                    "role": "assistant", 
                                    "content": f"**[AIによる自動修復コード (Attempt {retry_count})]**\n\n```python\n{target_code}\n```"
                                })

                            # 実行結果の履歴保存
                            if stdout_str or images_b64:
                                content_text = f"Running Code...\n\n```text\n{stdout_str}\n```"
                                if is_error:
                                    content_text = f"❌ Execution Failed (Retry limit reached):\n\n```text\n{stdout_str}\n```"
                                
                                exec_result_msg = {
                                    "role": "assistant",
                                    "content": content_text,
                                    "images": images_b64 
                                }
                                st.session_state['messages'].append(exec_result_msg)
                                
                                # プロジェクト全体との整合性: utils.save_auto_history を呼び出して履歴を最新化
                                if st.session_state.get('auto_save_enabled', True):
                                    current_file = st.session_state.get('current_chat_filename')
                                    new_filename = utils.save_auto_history(
                                        st.session_state['messages'],
                                        st.session_state.get('python_canvases', []),
                                        st.session_state.get('multi_code_enabled', False),
                                        client,
                                        current_filename=current_file
                                    )
                                    if new_filename:
                                        st.session_state['current_chat_filename'] = new_filename
                                        st.session_state['current_report_folder'] = os.path.splitext(new_filename)[0]

                            # ステータスの更新
                            if is_error:
                                exec_status.update(label="コード実行エラー (修正不能)", state="error")
                                st.error("AIによるコード自動修正が失敗しました。")
                            elif stdout_str or images_b64:
                                exec_status.update(label="コード実行完了", state="complete")
                            else:
                                exec_status.update(label="コード実行完了 (出力なし)", state="complete")
                                st.warning("グラフも標準出力も生成されませんでした。")
                            
                            break # ループを抜ける (成功 or 諦め)

                        # --- 失敗時 (リトライ実行) ---
                        else:
                            retry_count += 1
                            error_feedback = f"Code Execution Failed with Error:\n{stdout_str}\n\nPlease fix the code and output the corrected Python code block."
                            
                            st.warning(f"⚠️ コード実行エラーを検知しました。AIが修正を試みています... (Attempt {retry_count}/{max_retries})")
                            state_manager.add_debug_log(f"[Auto-Fix] Requesting fix for error: {stdout_str[:100]}...")

                            # エラー情報は "user" ロールとして内部履歴に追加
                            internal_history.append({"role": "user", "content": error_feedback})
                            
                            # 再生成リクエスト用のコンテキスト構築
                            fix_chat_contents = []
                            for m in internal_history:
                                # StreamlitのロールをGoogle APIの仕様(user/model)にマッピング
                                api_role = "model" if m["role"] == "assistant" else "user"
                                parts = [types.Part.from_text(text=m["content"])]
                                fix_chat_contents.append(types.Content(role=api_role, parts=parts))

                            # 修正案の生成
                            exec_status.update(label=f"⚙️ コードを再生成中 (Attempt {retry_count})...", state="running")
                            fix_response = client.models.generate_content(
                                model=model_id,
                                contents=fix_chat_contents,
                                config=gen_config
                            )
                            
                            current_response_text = ""
                            if fix_response.candidates and fix_response.candidates[0].content.parts:
                                current_response_text = "".join(part.text for part in fix_response.candidates[0].content.parts if part.text)
                            
                            # 修正案を内部履歴に追加し、次のループ(抽出・実行)へ
                            internal_history.append({"role": "assistant", "content": current_response_text})

                    except Exception as e:
                        # 例外発生時のステータスフリーズ防止
                        exec_status.update(label="エージェント処理中のシステムエラー", state="error")
                        st.error(f"Auto-fix loop failed due to system error: {e}")
                        state_manager.add_debug_log(f"Auto-fix loop failed due to system error: {e}", "error")
                        break