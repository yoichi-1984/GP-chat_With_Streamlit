# utils.py :
import os
import sys
import yaml
import tempfile
import subprocess
import io
import glob
import hashlib
import json
import re
import datetime
from importlib import resources
import streamlit as st
from . import config
from google import genai
from google.genai import types

# python-docxのインポート（Wordファイル用）
try:
    import docx
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

# pywin32 (PowerPoint操作用) のインポート
try:
    import win32com.client
    import pythoncom
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

@st.cache_data
def load_prompts():
    """パッケージ内のprompts.yamlを一度だけ読み込み、結果をキャッシュする"""
    try:
        with resources.open_text("gp_chat", "prompts.yaml") as f:
            yaml_data = yaml.safe_load(f)
            return yaml_data.get("prompts", {})
    except Exception as e:
        print(f"Warning: prompts.yaml load failed: {e}")
        return {}

def find_env_files(directory="env"):
    """指定されたディレクトリ内の.envファイルを検索する"""
    if not os.path.isdir(directory):
        return []
    return [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(".env")]

def extract_text_from_docx(file_bytes):
    """docxファイルからテキストを抽出する"""
    if not HAS_DOCX:
        return "[Error] python-docx library is not installed. Please install it to read Word documents."
    
    try:
        doc = docx.Document(io.BytesIO(file_bytes))
        full_text = []
        for para in doc.paragraphs:
            full_text.append(para.text)
        return "\n".join(full_text)
    except Exception as e:
        return f"[Error parsing docx] {str(e)}"

def _convert_ppt_to_images_core(file_bytes, filename):
    """PowerPoint変換の実処理を行う内部関数"""
    if not HAS_WIN32:
        print("Server Configuration Error: 'pywin32' library is missing. PowerPoint conversion unavailable.")
        return []
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_ppt_path = os.path.join(temp_dir, filename)
        with open(temp_ppt_path, "wb") as f:
            f.write(file_bytes)
        
        output_dir = os.path.join(temp_dir, "slides")
        os.makedirs(output_dir, exist_ok=True)

        ppt_app = None
        presentation = None
        
        try:
            pythoncom.CoInitialize()
            ppt_app = win32com.client.Dispatch("PowerPoint.Application")
            presentation = ppt_app.Presentations.Open(os.path.abspath(temp_ppt_path), ReadOnly=True, WithWindow=False)
            presentation.SaveAs(os.path.abspath(os.path.join(output_dir, "slide.png")), 18) # 18 = ppSaveAsPNG
        except Exception as e:
            print(f"PowerPoint conversion error: {e}")
            return []
        finally:
            if presentation:
                try:
                    presentation.Close()
                except Exception:
                    pass
            ppt_app = None
        
        image_data_list = []
        search_path = os.path.join(output_dir, "*.PNG")
        slide_files = glob.glob(search_path)
        if not slide_files:
             search_path = os.path.join(output_dir, "*.png")
             slide_files = glob.glob(search_path)
        
        if not slide_files and os.path.isdir(os.path.join(output_dir, "slide")):
             search_path = os.path.join(output_dir, "slide", "*.PNG")
             slide_files = glob.glob(search_path)
             if not slide_files:
                search_path = os.path.join(output_dir, "slide", "*.png")
                slide_files = glob.glob(search_path)

        slide_files.sort(key=lambda x: len(x))

        for slide_file in slide_files:
            with open(slide_file, "rb") as img_f:
                img_bytes = img_f.read()
                image_data_list.append((img_bytes, "image/png"))
        
        return image_data_list

def convert_ppt_to_images_win32(file_bytes, filename):
    """ラッパー関数。st.session_stateを使用して手動でキャッシュ管理を行う。"""
    if not HAS_WIN32:
        return []
        
    file_hash = hashlib.md5(file_bytes).hexdigest()
    
    if "ppt_conversion_cache" not in st.session_state:
        st.session_state["ppt_conversion_cache"] = {}

    if file_hash in st.session_state["ppt_conversion_cache"]:
        return st.session_state["ppt_conversion_cache"][file_hash]

    st.toast(f"Processing PowerPoint: {filename}...", icon="🔄")
    images = _convert_ppt_to_images_core(file_bytes, filename)
    
    if images:
        st.session_state["ppt_conversion_cache"][file_hash] = images
        st.toast(f"Converted {len(images)} slides.", icon="✅")
    
    return images

def process_uploaded_files_for_gemini(uploaded_files):
    """アップロードファイルをGemini API用のPartsリストに変換する"""
    from google.genai import types
    
    api_parts = []
    display_info = []

    for uploaded_file in uploaded_files:
        # VirtualUploadedFile (クリップボード) と Streamlit UploadedFile の両方に対応
        file_bytes = uploaded_file.getvalue()
        
        # VirtualUploadedFileの場合は属性として持っている、Streamlitの場合は属性
        mime_type = getattr(uploaded_file, "type", "application/octet-stream")
        filename = getattr(uploaded_file, "name", "unknown_file")
        
        file_ext = os.path.splitext(filename)[1].lower()

        if "wordprocessingml" in mime_type or filename.endswith(".docx"):
            text_content = extract_text_from_docx(file_bytes)
            prompt_text = f"\n\n[Attached Document: {filename}]\n{text_content}\n"
            api_parts.append(types.Part.from_text(text=prompt_text))
            display_info.append({"name": filename, "type": "docx", "size": len(file_bytes)})

        elif file_ext in [".ppt", ".pptx"]:
            images = convert_ppt_to_images_win32(file_bytes, filename)
            if images:
                for idx, (img_bytes, img_mime) in enumerate(images):
                    api_parts.append(types.Part.from_bytes(data=img_bytes, mime_type=img_mime))
                display_info.append({"name": filename, "type": "pptx(images)", "size": len(file_bytes)})
            else:
                st.error(f"Failed to convert PowerPoint: {filename}")

        elif mime_type == "application/pdf" or mime_type.startswith("image/"):
            api_parts.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type))
            display_info.append({"name": filename, "type": mime_type, "size": len(file_bytes)})
        
        elif mime_type.startswith("text/") or filename.endswith((".py", ".js", ".md", ".txt", ".json")):
            try:
                text_content = file_bytes.decode("utf-8")
                prompt_text = f"\n\n[Attached File: {filename}]\n```\n{text_content}\n```\n"
                api_parts.append(types.Part.from_text(text=prompt_text))
                display_info.append({"name": filename, "type": "text", "size": len(file_bytes)})
            except Exception:
                 st.warning(f"Could not decode text file: {filename}")

        else:
            st.warning(f"Unsupported file type for direct AI processing: {filename} ({mime_type})")

    return api_parts, display_info

def run_pylint_validation(canvas_code, canvas_index, prompts):
    """コードに対してpylintを実行し、分析プロンプトを生成する"""
    if not canvas_code or canvas_code.strip() == "" or canvas_code.strip() == config.ACE_EDITOR_DEFAULT_CODE.strip():
        st.toast(config.UITexts.NO_CODE_TO_VALIDATE, icon="⚠️")
        return

    spinner_text = config.UITexts.VALIDATE_SPINNER_MULTI.format(i=canvas_index + 1) if st.session_state['multi_code_enabled'] else config.UITexts.VALIDATE_SPINNER_SINGLE
    with st.spinner(spinner_text):
        tmp_file_path = ""
        pylint_report = ""
        try:
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.py', delete=False, encoding='utf-8') as tmp_file:
                tmp_file_path = tmp_file.name
                tmp_file.write(canvas_code.replace('\r\n', '\n'))
                tmp_file.flush()
            
            result = subprocess.run(
                [sys.executable, "-m", "pylint", tmp_file_path],
                capture_output=True, text=True, check=False
            )
            
            error_output = (result.stderr or "") + (result.stdout or "")
            if "syntax-error" in error_output.lower():
                st.toast(config.UITexts.PYLINT_SYNTAX_ERROR, icon="⚠️")
                return 

            issues = []
            if result.stdout:
                issues = [line for line in result.stdout.splitlines() if line.strip() and not line.startswith(('*', '-')) and 'Your code has been rated' not in line]
            
            if issues:
                cleaned_issues = [issue.replace(f'{tmp_file_path}:', 'Line ') for issue in issues]
                pylint_report = "\n".join(cleaned_issues)
        finally:
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)

    if not pylint_report.strip():
        st.sidebar.success(f"✅ Canvas-{canvas_index + 1}: pylint検証完了。問題なし。")
        return

    validation_template = prompts.get("validation", {}).get("text", "以下はpylintのレポートです。解析してください:\n{pylint_report}\n\n対象コード:\n{code_for_prompt}")
    code_for_prompt = f"```python\n{canvas_code}\n```"
    validation_prompt = validation_template.format(code_for_prompt=code_for_prompt, pylint_report=pylint_report)
    
    system_message = st.session_state['messages'][0] if st.session_state['messages'] and st.session_state['messages'][0]["role"] == "system" else {"role": "system", "content": ""}
    st.session_state['special_generation_messages'] = [system_message, {"role": "user", "content": validation_prompt}]
    st.session_state['is_generating'] = True

def load_app_config():
    """パッケージ内のconfig.yamlを読み込む"""
    try:
        with resources.open_text("gp_chat", "config.yaml") as f:
            return yaml.safe_load(f)
    except Exception:
        return {}

# --- 自動履歴保存機能用の新規関数 ---

def sanitize_filename(filename):
    """OSで禁止されている文字を置換し、長さを制限する"""
    # Windows等の禁止文字: \ / : * ? " < > |
    safe_name = re.sub(r'[\\/*?:"<>|]', '_', filename)
    # 改行コードなどを削除
    safe_name = safe_name.replace('\n', '').replace('\r', '').strip()
    return safe_name

def get_unique_filename(directory, base_filename):
    """同名ファイルが存在する場合、連番を付与してユニークなファイル名を生成する"""
    name, ext = os.path.splitext(base_filename)
    counter = 1
    unique_filename = base_filename
    
    while os.path.exists(os.path.join(directory, unique_filename)):
        unique_filename = f"{name}_{counter}{ext}"
        counter += 1
    
    return unique_filename

def generate_chat_title(messages, client, model_id="gemini-3-flash-preview"):
    """
    会話履歴からチャット名を生成する。
    軽量なモデルを使用し、Thinking LevelはLOW、GroundingはOFF。
    """
    try:
        # システムプロンプトを除く直近の会話内容を抽出（軽量化のためテキストのみ）
        conversation_text = ""
        for m in messages:
            if m["role"] != "system":
                # コンテンツが長い場合は切り詰める
                content = m.get("content", "")[:500]
                conversation_text += f"{m['role']}: {content}\n"
        
        prompt = (
            "以下の会話の内容を、15文字から20文字程度の** 日本語ベースの **短い要約（タイトル）にしてください。必要なら多少の英語を使ってもOKです。\n"
            "ファイル名として使用するため、記号は含めないでください。\n"
            "例: Pythonのクラス継承について\n"
            "例: 2024年のAI動向\n\n"
            f"会話内容:\n{conversation_text}"
        )

        # タイトル生成用の設定 (Thinking Level: LOW)
        gen_config = types.GenerateContentConfig(
            max_output_tokens=10000,
            temperature=0.1
        )
        if "gemini-3" in model_id:
             gen_config.thinking_config = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.LOW,
                include_thoughts=True # FlashモデルでもThinkingが有効な場合があるため念のため
            )

        response = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=gen_config
        )
        
        # Thinkingが含まれる場合のパース
        title = ""
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                # テキストパートを採用（Thoughtパートは無視）
                if part.text and (not hasattr(part, 'thought') or not part.thought):
                    title += part.text
        
        if not title:
            title = "無題のチャット"
            
        return sanitize_filename(title.strip())

    except Exception as e:
        print(f"Title generation failed: {e}")
        return "自動保存チャット"

def save_auto_history(messages, canvases, multi_code_enabled, client, current_filename=None):
    """
    履歴を自動保存する。
    current_filenameがあればそれを使い（上書き）、なければ新規生成する。
    """
    log_dir = "chat_log"
    os.makedirs(log_dir, exist_ok=True)
    
    # 有効な会話（System以外）の数をカウント
    valid_msgs = [m for m in messages if m["role"] != "system"]
    
    # 2往復未満（4メッセージ未満）なら何もしない
    if len(valid_msgs) < 4:
        return None

    # ファイル名が未定の場合、新規生成
    if not current_filename:
        # 日付プレフィックス (YYDDMMに修正)
        date_prefix = datetime.datetime.now().strftime("%y%m%d")
        
        # タイトル生成
        chat_title = generate_chat_title(messages, client)
        
        base_filename = f"{date_prefix}_{chat_title}.json"
        filename = get_unique_filename(log_dir, base_filename)
        current_filename = filename
    
    # 保存データ構築
    history_data = {
        "messages": messages,
        "python_canvases": canvases,
        "multi_code_enabled": multi_code_enabled,
        "saved_at": datetime.datetime.now().isoformat()
    }
    
    file_path = os.path.join(log_dir, current_filename)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(history_data, f, ensure_ascii=False, indent=2)
        print(f"Auto-saved history to: {file_path}")
        return current_filename
    except Exception as e:
        print(f"Auto-save failed: {e}")
        return current_filename
    