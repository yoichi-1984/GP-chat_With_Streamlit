# src\gp_chat\azure_report_agent.py:
from __future__ import annotations
import os
import re
import subprocess
from pathlib import Path
import streamlit as st
try:
    from gp_chat import state_manager
    from gp_chat import report_visual_inspector
except ImportError:
    import state_manager
    import report_visual_inspector
from . import azure_history_utils
from . import azure_responses_router
from .azure_runtime import AzureRuntime

DEFAULT_REPORT_PROMPT = """
# Task
Create a complete single-file HTML slide deck from the conversation so far.
# Output requirements
* Return exactly one complete HTML document.
* Include all CSS inline in a <style> block.
* Do not wrap the answer in markdown fences.
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

def _resolve_report_folder_name(messages, runtime: AzureRuntime):
    current_report_folder = st.session_state.get("current_report_folder")
    if current_report_folder:
        return current_report_folder

    current_chat_filename = st.session_state.get("current_chat_filename")
    if current_chat_filename:
        folder_name = os.path.splitext(os.path.basename(current_chat_filename))[0]
    else:
        folder_name = azure_history_utils.generate_chat_title(messages, runtime)

    folder_name = azure_history_utils.sanitize_filename(folder_name or "report_chat")
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
        return False, "Edge or Chrome is required to export the report PDF."

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
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "PDF export timed out after 60 seconds."
    except Exception as e:
        return False, f"Error launching browser for PDF export: {e}"

    if result.returncode != 0:
        error_text = (result.stderr or result.stdout or "").strip()
        return False, error_text or "Browser-based PDF export failed."
    if not os.path.exists(abs_pdf_path):
        return False, "PDF file was not created."
    return True, None

def run_report_generation(
    *,
    runtime: AzureRuntime,
    prompts,
    context,
    messages,
    max_output_tokens,
    text_placeholder,
    thought_status,
) -> tuple[str, object | None, dict[str, object]]:
    report_prompt = prompts.get("report_pdf", {}).get("text", DEFAULT_REPORT_PROMPT)
    report_instruction = (
        f"{report_prompt}\n\n"
        "# Additional requirements\n"
        "* Reflect the full conversation so far.\n"
        "* Include supporting visuals, citations, or summary structure when useful.\n"
        "* Return only the final HTML document.\n"
    )
    report_messages = list(context.messages)
    report_messages.append(
        {"role": "user", "content": [{"type": "input_text", "text": report_instruction}]}
    )
    thought_status.update(
        label="Azure report fallback is generating the HTML slide deck...",
        state="running",
        expanded=False,
    )
    state_manager.add_debug_log("[Azure Report] Generating HTML slide deck.")

    response = azure_responses_router.generate_response(
        runtime=runtime,
        input_messages=report_messages,
        instructions=context.system_instruction,
        max_output_tokens=max_output_tokens,
        temperature=0.2,
    )

    html_document = _extract_html_document(response.text)
    if "<html" not in html_document.lower():
        raise ValueError("Azure report agent did not return a complete HTML document.")

    # Twemoji CDN & 絵文字フォールバックCSSを自動注入
    html_document = report_visual_inspector.inject_twemoji_and_fonts(html_document)

    folder_name = _resolve_report_folder_name(messages, runtime)
    report_dir = os.path.join("slide_data", folder_name)
    os.makedirs(report_dir, exist_ok=True)

    report_number = _next_report_number(report_dir)
    base_name = f"{report_number:02d}"
    html_path = os.path.abspath(os.path.join(report_dir, f"{base_name}.html"))
    pdf_path = os.path.abspath(os.path.join(report_dir, f"{base_name}.pdf"))

    with open(html_path, "w", encoding="utf-8") as html_file:
        html_file.write(html_document)

    state_manager.add_debug_log(f"[Azure Report] Saved HTML: {html_path}")

    # --- マルチモーダルVLM (Azure Vision) による視覚的目視検査 ---
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
        inspection = report_visual_inspector.inspect_slides_with_azure(
            runtime=runtime,
            slide_images=slide_images,
        )
        if not inspection.passed:
            state_manager.add_debug_log(
                f"[Azure Report] Visual inspection failed: {inspection.issues}", "warning"
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
            retry_messages = list(context.messages)
            retry_messages.append(
                {"role": "user", "content": [{"type": "input_text", "text": retry_instruction}]}
            )
            retry_response = azure_responses_router.generate_response(
                runtime=runtime,
                input_messages=retry_messages,
                instructions=context.system_instruction,
                max_output_tokens=max_output_tokens,
                temperature=0.2,
            )
            retry_html = _extract_html_document(retry_response.text)
            if "<html" in retry_html.lower():
                html_document = report_visual_inspector.inject_twemoji_and_fonts(retry_html)
                with open(html_path, "w", encoding="utf-8") as html_file:
                    html_file.write(html_document)
                state_manager.add_debug_log(f"[Azure Report] Saved retry HTML: {html_path}")
                response = retry_response
        else:
            state_manager.add_debug_log("[Azure Report] Visual inspection passed.")

    thought_status.update(label="PDF スライドをレンダリング中...", state="running", expanded=False)
    pdf_success, pdf_error = _render_html_to_pdf(html_path, pdf_path)
    if pdf_success:
        assistant_text = (
            "Azure fallback generated the report.\n\n"
            f"- HTML: `{html_path}`\n"
            f"- PDF: `{pdf_path}`"
        )
        state_manager.add_debug_log(f"[Azure Report] Saved PDF: {pdf_path}")
        thought_status.update(
            label="Azure report generation complete.", state="complete", expanded=False
        )
    else:
        assistant_text = (
            "Azure fallback generated the HTML report, but PDF export failed.\n\n"
            f"- HTML: `{html_path}`\n"
            f"- PDF: `{pdf_path}`\n"
            f"- Error: {pdf_error}"
        )
        thought_status.update(
            label="Azure report generation failed during PDF export.",
            state="error",
            expanded=True,
        )
        state_manager.add_debug_log(f"[Azure Report] PDF export failed: {pdf_error}", "error")

    text_placeholder.markdown(assistant_text)
    return assistant_text, response.usage_metadata, {
        "html_path": html_path,
        "pdf_path": pdf_path,
        "pdf_success": pdf_success,
        "llm_route": response.route,
        "llm_retry_count": response.app_retry_count,
    }
