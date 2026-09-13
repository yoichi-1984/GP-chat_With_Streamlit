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
    from gp_chat import llm_router
    from gp_chat import report_visual_inspector
except ImportError:
    import state_manager
    import utils
    import llm_router
    import report_visual_inspector

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

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",    # 追加: 出力をUTF-8として明示的に読み込む
            errors="replace",    # 追加: デコードできない文字は「?」等に置換してクラッシュを防ぐ
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "PDF 生成がタイムアウトしました (60秒)。"
    except Exception as e:
        return False, f"ブラウザの起動中にエラーが発生しました: {e}"

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
    llm_clients = llm_router.coerce_llm_clients(client)

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

    response = llm_router.generate_content_with_route(
        llm_clients=llm_clients,
        model_id=model_id,
        contents=report_contents,
        config=gen_config,
        mode="report",
        logger=state_manager.add_debug_log,
    )

    html_document = _extract_html_document(response.text)
    if "<html" not in html_document.lower():
        raise ValueError("Report agent did not return a complete HTML document.")

    # Twemoji CDN & 絵文字フォールバックCSSを自動注入
    html_document = report_visual_inspector.inject_twemoji_and_fonts(html_document)

    folder_name = _resolve_report_folder_name(messages, llm_clients, model_id)
    report_dir = os.path.join("slide_data", folder_name)
    os.makedirs(report_dir, exist_ok=True)

    report_number = _next_report_number(report_dir)
    base_name = f"{report_number:02d}"
    html_path = os.path.abspath(os.path.join(report_dir, f"{base_name}.html"))
    pdf_path = os.path.abspath(os.path.join(report_dir, f"{base_name}.pdf"))

    with open(html_path, "w", encoding="utf-8") as html_file:
        html_file.write(html_document)

    state_manager.add_debug_log(f"[Report Agent] Saved HTML: {html_path}")

    # --- マルチモーダルVLMによる視覚的目視検査（文字化け・はみ出しチェック） ---
    thought_status.update(
        label="スライドの見た目（文字化け・レイアウト）を目視検査中...",
        state="running",
        expanded=False,
    )
    temp_inspect_dir = os.path.join(report_dir, f"{base_name}_inspect")
    slide_images = report_visual_inspector.capture_slides_as_images(
        html_path, temp_inspect_dir, max_slides=6
    )
    if slide_images:
        inspection = report_visual_inspector.inspect_slides_with_gemini(
            client=client,
            model_id=model_id,
            slide_images=slide_images,
        )
        if not inspection.passed:
            state_manager.add_debug_log(
                f"[Report Agent] Visual inspection failed: {inspection.issues}", "warning"
            )
            thought_status.update(
                label="視覚検査で不備を検出。レイアウトを自動調整して再生成中...",
                state="running",
                expanded=True,
            )
            fix_adv = (
                f"改善アドバイス: {inspection.suggested_prompt_fix}\n"
                if inspection.suggested_prompt_fix else ""
            )
            retry_instruction = (
                f"{report_instruction}\n\n"
                "# 視覚品質検査官からの修正指示（最優先で遵守してください）\n"
                "前回のスライド画像検査において、以下の問題が視覚的に確認されました。"
                "これらを確実に解決するようにHTMLコードを修正・再構成してください：\n"
                + "\n".join(f"- {issue}" for issue in inspection.issues) + "\n"
                + fix_adv
            )
            retry_contents = list(chat_contents)
            retry_contents.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=retry_instruction)],
                )
            )
            retry_response = llm_router.generate_content_with_route(
                llm_clients=llm_clients,
                model_id=model_id,
                contents=retry_contents,
                config=gen_config,
                mode="report",
                logger=state_manager.add_debug_log,
            )
            retry_html = _extract_html_document(retry_response.text)
            if "<html" in retry_html.lower():
                html_document = report_visual_inspector.inject_twemoji_and_fonts(retry_html)
                with open(html_path, "w", encoding="utf-8") as html_file:
                    html_file.write(html_document)
                state_manager.add_debug_log(f"[Report Agent] Saved retry HTML: {html_path}")
                response = retry_response
        else:
            state_manager.add_debug_log("[Report Agent] Visual inspection passed.")

    thought_status.update(label="PDF スライドをレンダリング中...", state="running", expanded=False)
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
        "llm_route": response.route,
        "llm_retry_count": response.app_retry_count,
    }
