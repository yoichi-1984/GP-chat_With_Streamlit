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
    
    Args:
        client: genai.Client
        model_id: 対象のモデル名
        gen_config: 生成コンフィグ (リトライ時に使用)
        initial_response_text: 初回のAIの回答テキスト
        available_files_map: 今回アップロードされたファイルのパス辞書
    """
    max_retries = 2
    retry_count = 0
    current_response_text = initial_response_text
    
    while retry_count <= max_retries:
        # コードブロックを抽出
        code_blocks = re.findall(r"```python\n(.*?)\n```", current_response_text, re.DOTALL)
        state_manager.add_debug_log(f"[DEBUG] Retry:{retry_count} Found {len(code_blocks)} Python code blocks.") 
        
        target_code = None
        for code in reversed(code_blocks):
            if any(k in code for k in ["plt.", "fig", "matplotlib", "pd.", "print(", "dataframe"]):
                target_code = code
                break
        
        if not target_code:
            state_manager.add_debug_log("[DEBUG] No suitable target code found (no plt/pd/print keywords).")
            break # コードがなければループ終了

        state_manager.add_debug_log(f"[DEBUG] Retry:{retry_count} Executing code...") 
        
        with st.chat_message("assistant"):
            status_label = "⚙️ コードを実行中..." if retry_count == 0 else f"⚙️ コードを修正して再実行中 (Retry {retry_count})..."
            with st.status(status_label, expanded=True) as exec_status:
                
                # execution_engineを使ってコードをサンドボックス実行
                stdout_str, figures = execution_engine.execute_user_code(
                    target_code,
                    available_files_map, 
                    st.session_state.get('python_canvases', [])
                )
                
                # エラー判定 (Tracebackが含まれているか)
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

                    # 履歴への保存処理
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
                        
                        # 自動保存のトリガー
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
                    # エラーを検知したので、AIにフィードバックして再生成させる
                    retry_count += 1
                    error_feedback = f"Code Execution Failed with Error:\n{stdout_str}\n\nPlease fix the code and output the corrected Python code block."
                    
                    st.warning(f"⚠️ コード実行エラーを検知しました。AIが修正を試みています... (Attempt {retry_count}/{max_retries})")
                    state_manager.add_debug_log(f"[Auto-Fix] Requesting fix for error: {stdout_str[:100]}...")

                    # 履歴にエラー情報を追加（AIへの入力として）
                    st.session_state['messages'].append({"role": "system", "content": error_feedback})
                    
                    # 再生成リクエスト用のコンテキスト構築
                    fix_chat_contents = []
                    for m in st.session_state['messages']:
                        if m["role"] == "system":
                            continue 
                        parts = []
                        if "images" in m: 
                            pass # 画像の送信は省略
                        
                        parts.append(types.Part.from_text(text=m["content"]))
                        fix_chat_contents.append(types.Content(role=m["role"], parts=parts))

                    # 修正案の生成
                    try:
                        fix_response = client.models.generate_content(
                            model=model_id,
                            contents=fix_chat_contents,
                            config=gen_config
                        )
                        
                        # 修正後の回答テキストを取得
                        current_response_text = ""
                        if fix_response.candidates and fix_response.candidates[0].content.parts:
                            for part in fix_response.candidates[0].content.parts:
                                if part.text:
                                    current_response_text += part.text
                        
                        # 修正案を履歴に追加
                        st.session_state['messages'].append({"role": "assistant", "content": current_response_text})
                        
                        # 次のループへ進む（新しい current_response_text で抽出・実行される）

                    except Exception as e:
                        st.error(f"Auto-fix generation failed: {e}")
                        break # APIエラー等は諦める