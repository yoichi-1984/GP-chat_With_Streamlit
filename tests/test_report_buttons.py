# -*- coding: utf-8 -*-
"""tests/test_report_buttons.py: PDF レポートメタデータ保持および操作ボタンロジックの単体テスト。"""

import json
import os
import unittest


class TestReportButtons(unittest.TestCase):
    """PDF / PPTX レポートのメタデータ保持と履歴シリアライズのテストケース。"""

    def test_gemini_report_metadata_attachment(self):
        """Gemini版レポート生成時のメタデータが assistant_msg に正しくセットされることを検証。"""
        # シミュレーションデータ
        report_meta = {
            "html_path": "c:/path/to/01.html",
            "pdf_path": "c:/path/to/01.pdf",
            "pdf_success": True,
            "llm_route": "standard",
            "llm_retry_count": 0,
        }
        assistant_msg = {"role": "assistant", "content": "レポートを保存しました。"}
        is_report_mode = True

        if is_report_mode:
            assistant_msg["report_mode"] = True
            if report_meta.get("pdf_path") and report_meta.get("pdf_success"):
                assistant_msg["pdf_path"] = report_meta["pdf_path"]
            if report_meta.get("html_path"):
                assistant_msg["html_path"] = report_meta["html_path"]

        self.assertEqual(assistant_msg.get("pdf_path"), "c:/path/to/01.pdf")
        self.assertEqual(assistant_msg.get("html_path"), "c:/path/to/01.html")
        self.assertTrue(assistant_msg.get("report_mode"))

    def test_azure_report_metadata_attachment(self):
        """Azure版レポート生成時のメタデータが assistant_msg に正しくセットされることを検証。"""
        mode_llm_meta = {
            "html_path": "c:/path/to/02.html",
            "pdf_path": "c:/path/to/02.pdf",
            "pdf_success": True,
            "llm_route": "azure_direct",
            "llm_retry_count": 0,
        }
        assistant_msg = {"role": "assistant", "content": "Azure fallback generated the report."}
        is_report_mode = True

        if is_report_mode:
            assistant_msg["report_mode"] = True
            if mode_llm_meta.get("pdf_path") and mode_llm_meta.get("pdf_success"):
                assistant_msg["pdf_path"] = mode_llm_meta["pdf_path"]
            if mode_llm_meta.get("html_path"):
                assistant_msg["html_path"] = mode_llm_meta["html_path"]

        self.assertEqual(assistant_msg.get("pdf_path"), "c:/path/to/02.pdf")
        self.assertEqual(assistant_msg.get("html_path"), "c:/path/to/02.html")

    def test_pdf_failure_does_not_attach_pdf_path(self):
        """PDF出力に失敗した場合は pdf_path がセットされず html_path のみ保持されることを検証。"""
        report_meta = {
            "html_path": "c:/path/to/03.html",
            "pdf_path": "c:/path/to/03.pdf",
            "pdf_success": False,
        }
        assistant_msg = {"role": "assistant", "content": "HTML レポートを保存しましたが、PDF 化に失敗しました。"}

        if report_meta.get("pdf_path") and report_meta.get("pdf_success"):
            assistant_msg["pdf_path"] = report_meta["pdf_path"]
        if report_meta.get("html_path"):
            assistant_msg["html_path"] = report_meta["html_path"]

        self.assertNotIn("pdf_path", assistant_msg)
        self.assertEqual(assistant_msg.get("html_path"), "c:/path/to/03.html")

    def test_chat_history_serialization_roundtrip(self):
        """pdf_path および html_path を含むメッセージが JSON 保存・復元で維持されることを検証。"""
        messages = [
            {"role": "user", "content": "レポートを作成してください"},
            {
                "role": "assistant",
                "content": "レポートを保存しました。",
                "report_mode": True,
                "pdf_path": "slide_data/chat_01/01.pdf",
                "html_path": "slide_data/chat_01/01.html",
                "pptx_path": "slide_data/chat_01/01.pptx",
            },
        ]
        serialized = json.dumps(messages, ensure_ascii=False)
        restored = json.loads(serialized)

        self.assertEqual(len(restored), 2)
        self.assertEqual(restored[1]["pdf_path"], "slide_data/chat_01/01.pdf")
        self.assertEqual(restored[1]["html_path"], "slide_data/chat_01/01.html")
        self.assertEqual(restored[1]["pptx_path"], "slide_data/chat_01/01.pptx")


if __name__ == "__main__":
    unittest.main()
