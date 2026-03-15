# report_agent.py:
import os
import re
import subprocess
from pathlib import Path

import streamlit as st
from google.genai import types

# --- Local Module Imports ---
try:
    from gp_chat import state_manager
    from gp_chat import utils
except ImportError:
    import state_manager
    import utils


DEFAULT_REPORT_PROMPT = """
# 指令
これまでの議論の全容を総括し、プレゼンテーションや報告書としてそのまま使用できる「HTMLベースのインフォグラフィックス（スライド資料）」を作成してください。

# 出力形式
* 1つのファイルで完結するHTMLコード（CSSは<style>タグ内に記述）として出力してください。
* 説明文やコードフェンスは不要です。HTMLコードのみを返してください。
""".strip()


PDF_BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def _extract_html_document(raw_text):
    cleaned = (raw_text or "").strip()
    fenced_match = re.search(r"```(?:html)?\s*(.*?)```", cleaned, flags=re.IGNORECASE | re.DOTALL)

    if fenced_match:
        cleaned = fenced_match.group(1).strip()

    lowered = cleaned.lower()
    doctype_pos = lowered.find("<!doctype")
    html_pos = lowered.find("<html")

    if doctype_pos >= 0:
        return cleaned[doctype_pos:].strip()
    if html_pos >= 0:
        return cleaned[html_pos:].strip()
    return cleaned


def _resolve_report_folder_name(messages, client, model_id):
    current_report_folder = st.session_state.get("current_report_folder")
    if current_report_folder:
        return current_report_folder

    current_chat_filename = st.session_state.get("current_chat_filename")
    if current_chat_filename:
        folder_name = os.path.splitext(os.path.basename(current_chat_filename))[0]
    else:
        folder_name = utils.generate_chat_title(messages, client, model_id=model_id)

    folder_name = utils.sanitize_filename(folder_name or "report_chat")
    folder_name = folder_name[:80] or "report_chat"
    st.session_state["current_report_folder"] = folder_name
    return folder_name


def _next_report_number(report_dir):
    existing_numbers = []
    if os.path.isdir(report_dir):
        for filename in os.listdir(report_dir):
            stem, ext = os.path.splitext(filename)
            if ext.lower() == ".html" and stem.isdigit():
                existing_numbers.append(int(stem))
    return max(existing_numbers, default=0) + 1


def _find_pdf_browser():
    for browser_path in PDF_BROWSER_CANDIDATES:
        if os.path.exists(browser_path):
            return browser_path
    return None


def _render_html_to_pdf(html_path, pdf_path):
    browser_path = _find_pdf_browser()
    if not browser_path:
        return False, "Edge または Chrome が見つかりませんでした。"

    html_uri = Path(os.path.abspath(html_path)).as_uri()
    abs_pdf_path = os.path.abspath(pdf_path)
    command = [
        browser_path,
        "--headless=new",
        "--disable-gpu",
        "--allow-file-access-from-files",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=5000",
        f"--print-to-pdf={abs_pdf_path}",
        html_uri,
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",    # 追加: 出力をUTF-8として明示的に読み込む
        errors="replace",    # 追加: デコードできない文字は「?」等に置換してクラッシュを防ぐ
        timeout=60,
        check=False,
    )

    if result.returncode != 0:
        error_text = (result.stderr or result.stdout or "").strip()
        return False, error_text or "ブラウザの PDF 出力に失敗しました。"

    if not os.path.exists(abs_pdf_path):
        return False, "PDF ファイルが出力されませんでした。"

    return True, None


def run_report_generation(
    client,
    model_id,
    prompts,
    chat_contents,
    messages,
    system_instruction,
    max_output_tokens,
    text_placeholder,
    thought_status,
):
    report_prompt = prompts.get("report_pdf", {}).get("text", DEFAULT_REPORT_PROMPT)
    report_instruction = (
        f"{report_prompt}\n\n"
        "# 実行指示\n"
        "* ここまでの会話全体を参照してください。\n"
        "* 特に直近のユーザー依頼を最優先で反映してください。\n"
        "* 保存可能な完全な HTML 文書として返してください。\n"
    )

    report_contents = list(chat_contents)
    report_contents.append(
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=report_instruction)],
        )
    )

    thought_status.update(label="レポート用 HTML を生成中...", state="running", expanded=False)
    state_manager.add_debug_log("[Report Agent] Generating HTML slide deck.")

    gen_config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        max_output_tokens=max_output_tokens,
        temperature=0.2,
    )
    if "gemini-3" in model_id:
        gen_config.thinking_config = types.ThinkingConfig(
            thinking_level=types.ThinkingLevel.LOW,
            include_thoughts=False,
        )

    response = client.models.generate_content(
        model=model_id,
        contents=report_contents,
        config=gen_config,
    )

    html_document = _extract_html_document(response.text)
    if "<html" not in html_document.lower():
        raise ValueError("Report agent did not return a complete HTML document.")

    folder_name = _resolve_report_folder_name(messages, client, model_id)
    report_dir = os.path.join("slide_data", folder_name)
    os.makedirs(report_dir, exist_ok=True)

    report_number = _next_report_number(report_dir)
    base_name = f"{report_number:02d}"
    html_path = os.path.abspath(os.path.join(report_dir, f"{base_name}.html"))
    pdf_path = os.path.abspath(os.path.join(report_dir, f"{base_name}.pdf"))

    with open(html_path, "w", encoding="utf-8") as html_file:
        html_file.write(html_document)

    state_manager.add_debug_log(f"[Report Agent] Saved HTML: {html_path}")
    pdf_success, pdf_error = _render_html_to_pdf(html_path, pdf_path)

    if pdf_success:
        state_manager.add_debug_log(f"[Report Agent] Saved PDF: {pdf_path}")
        assistant_text = (
            "レポートを保存しました。\n\n"
            f"- HTML: `{html_path}`\n"
            f"- PDF: `{pdf_path}`"
        )
        thought_status.update(label="レポート生成完了", state="complete", expanded=False)
    else:
        assistant_text = (
            "HTML レポートを保存しましたが、PDF 化に失敗しました。\n\n"
            f"- HTML: `{html_path}`\n"
            f"- PDF: `{pdf_path}`\n"
            f"- Error: {pdf_error}"
        )
        thought_status.update(label="レポート生成は完了、PDF 化は失敗", state="error", expanded=True)
        state_manager.add_debug_log(f"[Report Agent] PDF export failed: {pdf_error}", "error")

    text_placeholder.markdown(assistant_text)

    return assistant_text, response.usage_metadata, {
        "html_path": html_path,
        "pdf_path": pdf_path,
        "pdf_success": pdf_success,
    }