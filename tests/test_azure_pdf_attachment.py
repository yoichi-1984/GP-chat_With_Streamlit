import unittest
import base64
from gp_chat import azure_context_builder


class DummyUploadedFile:
    def __init__(self, name: str, mime_type: str, content: bytes):
        self.name = name
        self.type = mime_type
        self._content = content

    def getvalue(self) -> bytes:
        return self._content


class TestAzurePDFAttachment(unittest.TestCase):
    def test_pdf_attachment_generates_input_file(self):
        pdf_bytes = b"%PDF-1.4 sample pdf binary content for testing"
        pdf_file = DummyUploadedFile("sample.pdf", "application/pdf", pdf_bytes)

        target_messages = [
            {"role": "user", "content": "このPDFを要約してください。"}
        ]

        context = azure_context_builder.build_materialized_context(
            target_messages=target_messages,
            queue_files=[pdf_file],
            python_canvases=[],
            canvas_enabled_flags=[],
            is_special_mode=False,
            auto_plot_enabled=False,
            data_manager_instance=None,
        )

        # 添付メタデータ検証
        self.assertEqual(len(context.file_attachments_meta), 1)
        self.assertEqual(context.file_attachments_meta[0]["name"], "sample.pdf")
        self.assertEqual(context.file_attachments_meta[0]["type"], "pdf")
        self.assertEqual(context.file_attachments_meta[0]["size"], len(pdf_bytes))

        # ターゲットメッセージの content 検証
        user_message = context.messages[-1]
        self.assertEqual(user_message["role"], "user")
        content_items = user_message["content"]

        # input_file が存在することを確認
        pdf_item = next((item for item in content_items if item.get("type") == "input_file"), None)
        self.assertIsNotNone(pdf_item, "input_file content item should be present")
        self.assertEqual(pdf_item["filename"], "sample.pdf")
        
        expected_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
        self.assertEqual(pdf_item["file_data"], f"data:application/pdf;base64,{expected_b64}")

    def test_mixed_attachments_with_pdf(self):
        pdf_bytes = b"%PDF-1.4 test"
        pdf_file = DummyUploadedFile("doc.pdf", "application/pdf", pdf_bytes)

        txt_bytes = "こんにちは世界".encode("utf-8")
        txt_file = DummyUploadedFile("notes.txt", "text/plain", txt_bytes)

        img_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        img_file = DummyUploadedFile("image.png", "image/png", img_bytes)

        target_messages = [
            {"role": "user", "content": "マルチファイル分析をお願いします。"}
        ]

        context = azure_context_builder.build_materialized_context(
            target_messages=target_messages,
            queue_files=[pdf_file, txt_file, img_file],
            python_canvases=[],
            canvas_enabled_flags=[],
            is_special_mode=False,
            auto_plot_enabled=False,
            data_manager_instance=None,
        )

        self.assertEqual(len(context.file_attachments_meta), 3)
        user_message = context.messages[-1]
        content_items = user_message["content"]

        types_found = [item.get("type") for item in content_items]
        self.assertIn("input_file", types_found)
        self.assertIn("input_text", types_found)
        self.assertIn("input_image", types_found)


if __name__ == "__main__":
    unittest.main()
