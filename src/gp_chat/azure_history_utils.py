from __future__ import annotations

import datetime
import glob
import json
import os
import re

import streamlit as st

try:
    from gp_chat import state_manager
except ImportError:
    import state_manager

from . import azure_responses_router
from .azure_runtime import AzureRuntime


def sanitize_filename(filename: str) -> str:
    safe_name = re.sub(r'[\\/*?:"<>|]', "_", filename)
    return safe_name.replace("\n", "").replace("\r", "").strip()


def get_unique_filename(directory: str, base_filename: str) -> str:
    name, ext = os.path.splitext(base_filename)
    counter = 1
    unique_filename = base_filename
    while os.path.exists(os.path.join(directory, unique_filename)):
        unique_filename = f"{name}_{counter}{ext}"
        counter += 1
    return unique_filename


def generate_branch_filename(current_filename, log_dir="chat_log"):
    today_str = datetime.datetime.now().strftime("%y%m%d")
    base_title = "branched_chat"
    if current_filename:
        name_no_ext = os.path.splitext(current_filename)[0]
        match = re.match(r"^(?:\d{6}_)?(.*?)(?:-\d{2,})?$", name_no_ext)
        if match and match.group(1):
            base_title = match.group(1)
        else:
            base_title = name_no_ext

    pattern = os.path.join(log_dir, f"*_{base_title}-*.json")
    existing_files = glob.glob(pattern)

    max_branch = 1
    for filename in existing_files:
        basename = os.path.basename(filename)
        name_no_ext = os.path.splitext(basename)[0]
        suffix_match = re.search(r"-(\d{2,})$", name_no_ext)
        if suffix_match:
            num = int(suffix_match.group(1))
            if num > max_branch:
                max_branch = num
    return f"{today_str}_{base_title}-{max_branch + 1:02d}.json"


def generate_chat_title(messages, runtime: AzureRuntime) -> str:
    try:
        conversation_text = ""
        for message in messages:
            if message["role"] != "system":
                content = message.get("content", "")[:500]
                conversation_text += f"{message['role']}: {content}\n"

        prompt = (
            "Create a concise Japanese chat title in 15 to 20 Japanese characters. "
            "Return only the title text, no quotes, no markdown.\n\n"
            "Conversation:\n{conversation_text}"
        )
        result = azure_responses_router.generate_response(
            runtime=runtime,
            input_messages=[
                {"role": "user", "content": [{"type": "input_text", "text": prompt}]}
            ],
            instructions="You create concise Japanese chat titles.",
            max_output_tokens=128,
            temperature=0.1,
        )
        title = (result.text or "").strip()
        if not title:
            title = "自動保存チャット"
        return sanitize_filename(title)
    except Exception as exc:
        state_manager.add_debug_log(f"[Azure History] Title generation failed: {exc}", "error")
        return "自動保存チャット"


def save_auto_history(
    messages,
    canvases,
    multi_code_enabled,
    runtime: AzureRuntime,
    current_filename=None,
):
    log_dir = "chat_log"
    os.makedirs(log_dir, exist_ok=True)

    valid_msgs = [message for message in messages if message["role"] != "system"]
    if len(valid_msgs) < 4:
        return None

    if not current_filename:
        date_prefix = datetime.datetime.now().strftime("%y%m%d")
        chat_title = generate_chat_title(messages, runtime)
        base_filename = f"{date_prefix}_{chat_title}.json"
        current_filename = get_unique_filename(log_dir, base_filename)

    history_data = {
        "messages": messages,
        "python_canvases": canvases,
        "multi_code_enabled": multi_code_enabled,
        "enable_more_research": st.session_state.get("enable_more_research", False),
        "enable_report_pdf": st.session_state.get("enable_report_pdf", False),
        "enable_google_search": st.session_state.get("enable_google_search", False),
        "reasoning_effort": st.session_state.get("reasoning_effort", "high"),
        "auto_plot_enabled": st.session_state.get("auto_plot_enabled", False),
        "current_model_id": st.session_state.get("current_model_id"),
        "selected_env_file": st.session_state.get("selected_env_file"),
        "auto_save_enabled": st.session_state.get("auto_save_enabled", True),
        "always_send_all_canvases": st.session_state.get("always_send_all_canvases", False),
        "current_report_folder": st.session_state.get("current_report_folder"),
        "saved_at": datetime.datetime.now().isoformat(),
    }

    file_path = os.path.join(log_dir, current_filename)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(history_data, f, ensure_ascii=False, indent=2)
        return current_filename
    except Exception as exc:
        state_manager.add_debug_log(f"[Azure History] Auto-save failed: {exc}", "error")
        return current_filename