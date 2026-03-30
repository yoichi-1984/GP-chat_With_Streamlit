# src\gp_chat\azure_report_agent.py:
from __future__ import annotations
import os
import re
import subprocess
from pathlib import Path
import streamlit as st
try:
    from gp_chat import state_manager
except ImportError:
    import state_manager
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
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
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
    pdf_success, pdf_error = _render_html_to_pdf(html_path, pdf_path)
    if pdf_success:
        assistant_text = (
            "Azure fallback generated the report.\n\n"
            f"- HTML: `{html_path}`\n"
            f"- PDF: `{pdf_path}`"
        )
        state_manager.add_debug_log(f"[Azure Report] Saved PDF: {pdf_path}")
        thought_status.update(label="Azure report generation complete.", state="complete", expanded=False)
    else:
        assistant_text = (
            "Azure fallback generated the HTML report, but PDF export failed.\n\n"
            f"- HTML: `{html_path}`\n"
            f"- PDF: `{pdf_path}`\n"
            f"- Error: {pdf_error}"
        )
        thought_status.update(label="Azure report generation failed during PDF export.", state="error", expanded=True)
        state_manager.add_debug_log(f"[Azure Report] PDF export failed: {pdf_error}", "error")

    text_placeholder.markdown(assistant_text)
    return assistant_text, response.usage_metadata, {
        "html_path": html_path,
        "pdf_path": pdf_path,
        "pdf_success": pdf_success,
        "llm_route": response.route,
        "llm_retry_count": response.app_retry_count,
    }