from __future__ import annotations

import base64
import copy
import glob
import hashlib
import io
import os
import tempfile

import streamlit as st

try:
    from gp_chat import config
    from gp_chat import state_manager
except ImportError:
    import config
    import state_manager

try:
    import docx

    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    import win32com.client
    import pythoncom

    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

from .azure_common_types import AzureMaterializedContext


class AzureContextBuildError(RuntimeError):
    pass


def _content_item_text(role: str, text: str) -> dict[str, str]:
    item_type = "output_text" if role == "assistant" else "input_text"
    return {"type": item_type, "text": text}


def _message_content_role(role: str) -> str:
    return "assistant" if role in ("assistant", "model") else "user"


def _extract_text_from_docx(file_bytes: bytes) -> str:
    if not HAS_DOCX:
        raise AzureContextBuildError(
            "python-docx is required to process Word documents during Azure fallback."
        )
    try:
        doc = docx.Document(io.BytesIO(file_bytes))
        return "\n".join(para.text for para in doc.paragraphs)
    except Exception as exc:
        raise AzureContextBuildError(f"Failed to read docx attachment: {exc}") from exc


def _convert_ppt_to_images_core(file_bytes: bytes, filename: str) -> list[tuple[bytes, str]]:
    if not HAS_WIN32:
        raise AzureContextBuildError(
            "pywin32 is required to process PowerPoint files during Azure fallback."
        )

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
            presentation = ppt_app.Presentations.Open(
                os.path.abspath(temp_ppt_path),
                ReadOnly=True,
                WithWindow=False,
            )
            presentation.SaveAs(os.path.abspath(os.path.join(output_dir, "slide.png")), 18)
        except Exception as exc:
            raise AzureContextBuildError(
                f"Failed to convert PowerPoint attachment: {exc}"
            ) from exc
        finally:
            if presentation:
                try:
                    presentation.Close()
                except Exception:
                    pass
            ppt_app = None

        image_data_list: list[tuple[bytes, str]] = []
        slide_files = glob.glob(os.path.join(output_dir, "*.PNG"))
        if not slide_files:
            slide_files = glob.glob(os.path.join(output_dir, "*.png"))
        if not slide_files and os.path.isdir(os.path.join(output_dir, "slide")):
            slide_files = glob.glob(os.path.join(output_dir, "slide", "*.PNG"))
            if not slide_files:
                slide_files = glob.glob(os.path.join(output_dir, "slide", "*.png"))
        slide_files.sort(key=lambda x: len(x))
        for slide_file in slide_files:
            with open(slide_file, "rb") as img_f:
                image_data_list.append((img_f.read(), "image/png"))
        return image_data_list


def _convert_ppt_to_images_win32(file_bytes: bytes, filename: str) -> list[tuple[bytes, str]]:
    if not HAS_WIN32:
        raise AzureContextBuildError(
            "pywin32 is required to process PowerPoint files during Azure fallback."
        )

    file_hash = hashlib.md5(file_bytes).hexdigest()
    if "azure_ppt_conversion_cache" not in st.session_state:
        st.session_state["azure_ppt_conversion_cache"] = {}

    cache = st.session_state["azure_ppt_conversion_cache"]
    if file_hash in cache:
        return cache[file_hash]

    images = _convert_ppt_to_images_core(file_bytes, filename)
    cache[file_hash] = images
    return images


def _bytes_to_data_url(data: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(data).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def _build_attachment_content_items(uploaded_files) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    content_items: list[dict[str, object]] = []
    meta: list[dict[str, object]] = []

    for uploaded_file in uploaded_files:
        file_bytes = uploaded_file.getvalue()
        mime_type = getattr(uploaded_file, "type", "application/octet-stream")
        filename = getattr(uploaded_file, "name", "unknown_file")
        file_ext = os.path.splitext(filename)[1].lower()

        if "wordprocessingml" in mime_type or file_ext == ".docx":
            text_content = _extract_text_from_docx(file_bytes)
            content_items.append(
                {
                    "type": "input_text",
                    "text": f"[Attached Document: {filename}]\n{text_content}",
                }
            )
            meta.append({"name": filename, "type": "docx", "size": len(file_bytes)})
            continue

        if file_ext in (".ppt", ".pptx"):
            images = _convert_ppt_to_images_win32(file_bytes, filename)
            content_items.append(
                {"type": "input_text", "text": f"[Attached Presentation: {filename}]"}
            )
            for img_bytes, img_mime in images:
                content_items.append(
                    {
                        "type": "input_image",
                        "image_url": _bytes_to_data_url(img_bytes, img_mime),
                    }
                )
            meta.append({"name": filename, "type": "pptx(images)", "size": len(file_bytes)})
            continue

        if mime_type.startswith("image/"):
            content_items.append({"type": "input_text", "text": f"[Attached Image: {filename}]"})
            content_items.append(
                {
                    "type": "input_image",
                    "image_url": _bytes_to_data_url(file_bytes, mime_type),
                }
            )
            meta.append({"name": filename, "type": mime_type, "size": len(file_bytes)})
            continue

        if mime_type == "application/pdf" or file_ext == ".pdf":
            raise AzureContextBuildError(
                f"PDF attachments are not supported for high-compatibility Azure fallback: {filename}"
            )

        if mime_type.startswith("text/") or file_ext in (
            ".py",
            ".js",
            ".md",
            ".txt",
            ".json",
            ".csv",
            ".yaml",
            ".yml",
        ):
            try:
                text_content = file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    text_content = file_bytes.decode("cp932")
                except UnicodeDecodeError:
                    text_content = file_bytes.decode("utf-8", errors="replace")
            content_items.append(
                {
                    "type": "input_text",
                    "text": f"[Attached File: {filename}]\n```\n{text_content}\n```",
                }
            )
            meta.append({"name": filename, "type": "text", "size": len(file_bytes)})
            continue

        raise AzureContextBuildError(
            f"Unsupported attachment type for Azure fallback: {filename} ({mime_type})"
        )

    return content_items, meta


def _ensure_target_user_message(messages: list[dict[str, object]]) -> dict[str, object]:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message
    synthetic = {"role": "user", "content": []}
    messages.append(synthetic)
    state_manager.add_debug_log(
        "[Azure Context] No user message found. Inserted a synthetic user message.",
        "warning",
    )
    return synthetic


def build_materialized_context(
    *,
    target_messages,
    queue_files,
    python_canvases,
    canvas_enabled_flags,
    is_special_mode,
    auto_plot_enabled,
    data_manager_instance,
) -> AzureMaterializedContext:
    messages: list[dict[str, object]] = []
    system_instruction = ""

    for message in target_messages:
        role = message.get("role", "user")
        if role == "system":
            system_instruction = message.get("content", "")
            continue
        mapped_role = _message_content_role(role)
        content_text = message.get("content", "")
        messages.append(
            {
                "role": mapped_role,
                "content": [_content_item_text(mapped_role, content_text)],
            }
        )

    available_files_map: dict[str, str] = {}
    file_attachments_meta: list[dict[str, object]] = []

    if auto_plot_enabled and not is_special_mode and data_manager_instance:
        for queued_file in queue_files:
            try:
                file_path, file_name = data_manager_instance.save_file(queued_file)
                if file_path:
                    available_files_map[file_name] = file_path
            except Exception as exc:
                file_label = getattr(queued_file, "name", "unknown_file")
                state_manager.add_debug_log(
                    f"[Azure Context] Failed to save temp file {file_label}: {exc}",
                    "error",
                )

    target_user_message = _ensure_target_user_message(messages)

    if not is_special_mode and queue_files:
        attachment_items, file_attachments_meta = _build_attachment_content_items(queue_files)
        if attachment_items:
            target_user_message["content"] = attachment_items + list(
                target_user_message.get("content", [])
            )
            state_manager.add_debug_log(
                f"[Azure Context] Injected {len(attachment_items)} attachment content items."
            )

    if not is_special_mode:
        canvas_items = []
        injected_canvas_count = 0
        for index, code in enumerate(python_canvases):
            is_enabled = (
                canvas_enabled_flags[index]
                if index < len(canvas_enabled_flags)
                else True
            )
            if is_enabled and code.strip() and code != config.ACE_EDITOR_DEFAULT_CODE:
                canvas_items.append(
                    {
                        "type": "input_text",
                        "text": f"[Canvas-{index + 1}]\n```python\n{code}\n```",
                    }
                )
                injected_canvas_count += 1
        if canvas_items:
            target_user_message["content"] = canvas_items + list(
                target_user_message.get("content", [])
            )
            state_manager.add_debug_log(
                f"[Azure Context] Injected {injected_canvas_count} canvas snippet(s)."
            )

    retry_context_snapshot = copy.deepcopy(messages)
    return AzureMaterializedContext(
        messages=messages,
        system_instruction=system_instruction,
        available_files_map=available_files_map,
        file_attachments_meta=file_attachments_meta,
        retry_context_snapshot=retry_context_snapshot,
    )


def build_retry_messages_from_text_history(
    *,
    system_instruction: str,
    base_messages: list[dict[str, object]],
    assistant_text: str,
    user_feedback: str,
) -> tuple[str, list[dict[str, object]]]:
    retry_messages = copy.deepcopy(base_messages)
    retry_messages.append(
        {"role": "assistant", "content": [{"type": "output_text", "text": assistant_text}]}
    )
    retry_messages.append(
        {"role": "user", "content": [{"type": "input_text", "text": user_feedback}]}
    )
    return system_instruction, retry_messages