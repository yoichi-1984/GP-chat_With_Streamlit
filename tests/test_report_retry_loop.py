# tests/test_report_retry_loop.py
"""PDFレポート生成における視覚監査自己修復ループ（初回＋最大3回再作成）の単体テスト。"""
# pylint: disable=line-too-long,unused-argument,unused-variable,too-many-arguments,too-many-positional-arguments
from unittest.mock import MagicMock, patch
import os
import tempfile
import unittest

from gp_chat import report_agent, azure_report_agent
from gp_chat.report_visual_inspector import InspectionResult

REAL_JOIN = os.path.join


class TestReportRetryLoop(unittest.TestCase):
    """Gemini および Azure レポートエージェントのリトライループ検証スイート。"""

    def setUp(self):
        self.mock_placeholder = MagicMock()
        self.mock_thought = MagicMock()
        self.sample_messages = [{"role": "user", "content": "ビジネスレポートを作成してください。"}]
        self.sample_prompts = {"report_pdf": {"text": "HTMLスライドを作成してください。"}}
        self.sample_html = (
            "<!DOCTYPE html><html><head><title>Test</title></head>"
            "<body><div class='slide'><h1>Slide 1</h1></div></body></html>"
        )

    # --- Gemini (report_agent) Tests ---

    @patch("gp_chat.llm_router.coerce_llm_clients", return_value=MagicMock())
    @patch("gp_chat.report_agent._render_html_to_pdf", return_value=(True, None))
    @patch("gp_chat.report_visual_inspector.capture_slides_as_images")
    @patch("gp_chat.report_visual_inspector.inspect_slides_with_gemini")
    @patch("gp_chat.llm_router.generate_content_with_route")
    @patch("gp_chat.report_agent._resolve_report_folder_name", return_value="test_folder")
    def test_gemini_report_loop_first_pass(
        self, mock_folder, mock_generate, mock_inspect, mock_capture, mock_render, mock_coerce
    ):
        """Gemini: 初回で PASS した場合、再生成を行わずに即時終了すること。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("gp_chat.report_agent.os.path.join", side_effect=lambda *args: REAL_JOIN(tmpdir, *args[1:])):
                mock_resp = MagicMock()
                mock_resp.text = f"```html\n{self.sample_html}\n```"
                mock_resp.usage_metadata = {}
                mock_resp.route = "standard"
                mock_resp.app_retry_count = 0
                mock_generate.return_value = mock_resp

                mock_capture.return_value = [{"slide_number": 1, "bytes": b"fake"}]
                mock_inspect.return_value = InspectionResult(passed=True, issues=[], suggested_prompt_fix="")

                res_text, _, metadata = report_agent.run_report_generation(
                    client=MagicMock(),
                    model_id="gemini-4-argon",
                    prompts=self.sample_prompts,
                    chat_contents=[],
                    messages=self.sample_messages,
                    system_instruction="システム指示",
                    max_output_tokens=4096,
                    text_placeholder=self.mock_placeholder,
                    thought_status=self.mock_thought,
                )

                self.assertIn("レポートを保存しました", res_text)
                self.assertTrue(metadata["pdf_success"])
                # LLM 生成は初回 1 回のみ
                self.assertEqual(mock_generate.call_count, 1)
                # 視覚検査は初回 1 回のみ
                self.assertEqual(mock_inspect.call_count, 1)
                # PDF レンダリングが呼ばれること
                self.assertEqual(mock_render.call_count, 1)

    @patch("gp_chat.llm_router.coerce_llm_clients", return_value=MagicMock())
    @patch("gp_chat.report_agent._render_html_to_pdf", return_value=(True, None))
    @patch("gp_chat.report_visual_inspector.capture_slides_as_images")
    @patch("gp_chat.report_visual_inspector.inspect_slides_with_gemini")
    @patch("gp_chat.llm_router.generate_content_with_route")
    @patch("gp_chat.report_agent._resolve_report_folder_name", return_value="test_folder")
    def test_gemini_report_loop_retry_then_pass(
        self, mock_folder, mock_generate, mock_inspect, mock_capture, mock_render, mock_coerce
    ):
        """Gemini: 初回 FAIL 後、1回目の再作成で PASS した場合、早期終了すること。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("gp_chat.report_agent.os.path.join", side_effect=lambda *args: REAL_JOIN(tmpdir, *args[1:])):
                mock_resp = MagicMock()
                mock_resp.text = f"```html\n{self.sample_html}\n```"
                mock_resp.usage_metadata = {}
                mock_resp.route = "standard"
                mock_resp.app_retry_count = 0
                mock_generate.return_value = mock_resp

                mock_capture.return_value = [{"slide_number": 1, "bytes": b"fake"}]
                # 1回目 FAIL -> 2回目 PASS
                mock_inspect.side_effect = [
                    InspectionResult(passed=False, issues=["文字あふれ"], suggested_prompt_fix="文字量削減"),
                    InspectionResult(passed=True, issues=[], suggested_prompt_fix=""),
                ]

                res_text, _, metadata = report_agent.run_report_generation(
                    client=MagicMock(),
                    model_id="gemini-4-argon",
                    prompts=self.sample_prompts,
                    chat_contents=[],
                    messages=self.sample_messages,
                    system_instruction="システム指示",
                    max_output_tokens=4096,
                    text_placeholder=self.mock_placeholder,
                    thought_status=self.mock_thought,
                )

                self.assertTrue(metadata["pdf_success"])
                # LLM 生成: 初回 + 再作成1回 = 2回
                self.assertEqual(mock_generate.call_count, 2)
                # 視覚検査: 初回 + 再作成後 = 2回
                self.assertEqual(mock_inspect.call_count, 2)
                self.assertEqual(mock_render.call_count, 1)

    @patch("gp_chat.llm_router.coerce_llm_clients", return_value=MagicMock())
    @patch("gp_chat.report_agent._render_html_to_pdf", return_value=(True, None))
    @patch("gp_chat.report_visual_inspector.capture_slides_as_images")
    @patch("gp_chat.report_visual_inspector.inspect_slides_with_gemini")
    @patch("gp_chat.llm_router.generate_content_with_route")
    @patch("gp_chat.report_agent._resolve_report_folder_name", return_value="test_folder")
    def test_gemini_report_loop_max_retries_reached(
        self, mock_folder, mock_generate, mock_inspect, mock_capture, mock_render, mock_coerce
    ):
        """Gemini: 4回連続 FAIL（初回＋最大3回再作成）の場合、3回再試行でループを終了しPDF化すること。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("gp_chat.report_agent.os.path.join", side_effect=lambda *args: REAL_JOIN(tmpdir, *args[1:])):
                mock_resp = MagicMock()
                mock_resp.text = f"```html\n{self.sample_html}\n```"
                mock_resp.usage_metadata = {}
                mock_resp.route = "standard"
                mock_resp.app_retry_count = 0
                mock_generate.return_value = mock_resp

                mock_capture.return_value = [{"slide_number": 1, "bytes": b"fake"}]
                # 4回連続 FAIL
                mock_inspect.return_value = InspectionResult(
                    passed=False, issues=["改善不能な重なり"], suggested_prompt_fix="配置変更"
                )

                res_text, _, metadata = report_agent.run_report_generation(
                    client=MagicMock(),
                    model_id="gemini-4-argon",
                    prompts=self.sample_prompts,
                    chat_contents=[],
                    messages=self.sample_messages,
                    system_instruction="システム指示",
                    max_output_tokens=4096,
                    text_placeholder=self.mock_placeholder,
                    thought_status=self.mock_thought,
                )

                self.assertTrue(metadata["pdf_success"])
                # LLM 生成: 初回 + 3回再作成 = 4回
                self.assertEqual(mock_generate.call_count, 4)
                # 視覚検査: 初回 + 3回再作成後 = 4回
                self.assertEqual(mock_inspect.call_count, 4)
                self.assertEqual(mock_render.call_count, 1)

    # --- Azure (azure_report_agent) Tests ---

    @patch("gp_chat.azure_report_agent._render_html_to_pdf", return_value=(True, None))
    @patch("gp_chat.report_visual_inspector.capture_slides_as_images")
    @patch("gp_chat.report_visual_inspector.inspect_slides_with_azure")
    @patch("gp_chat.azure_responses_router.generate_response")
    @patch("gp_chat.azure_report_agent._resolve_report_folder_name", return_value="test_folder")
    def test_azure_report_loop_first_pass(
        self, mock_folder, mock_generate, mock_inspect, mock_capture, mock_render
    ):
        """Azure: 初回で PASS した場合、再生成を行わずに即時終了すること。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("gp_chat.azure_report_agent.os.path.join", side_effect=lambda *args: REAL_JOIN(tmpdir, *args[1:])):
                mock_resp = MagicMock()
                mock_resp.text = f"```html\n{self.sample_html}\n```"
                mock_resp.usage_metadata = {}
                mock_generate.return_value = mock_resp

                mock_capture.return_value = [{"slide_number": 1, "bytes": b"fake"}]
                mock_inspect.return_value = InspectionResult(passed=True, issues=[], suggested_prompt_fix="")

                mock_runtime = MagicMock()
                mock_context = MagicMock()
                mock_context.messages = []
                mock_context.system_instruction = "Azureシステム指示"

                res_text, _, metadata = azure_report_agent.run_report_generation(
                    runtime=mock_runtime,
                    prompts=self.sample_prompts,
                    context=mock_context,
                    messages=self.sample_messages,
                    max_output_tokens=4096,
                    text_placeholder=self.mock_placeholder,
                    thought_status=self.mock_thought,
                )

                self.assertIn("Azure fallback generated the report", res_text)
                self.assertTrue(metadata["pdf_success"])
                self.assertEqual(mock_generate.call_count, 1)
                self.assertEqual(mock_inspect.call_count, 1)
                self.assertEqual(mock_render.call_count, 1)

    @patch("gp_chat.azure_report_agent._render_html_to_pdf", return_value=(True, None))
    @patch("gp_chat.report_visual_inspector.capture_slides_as_images")
    @patch("gp_chat.report_visual_inspector.inspect_slides_with_azure")
    @patch("gp_chat.azure_responses_router.generate_response")
    @patch("gp_chat.azure_report_agent._resolve_report_folder_name", return_value="test_folder")
    def test_azure_report_loop_retry_then_pass(
        self, mock_folder, mock_generate, mock_inspect, mock_capture, mock_render
    ):
        """Azure: 初回 FAIL 後、1回目の再作成で PASS した場合、早期終了すること。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("gp_chat.azure_report_agent.os.path.join", side_effect=lambda *args: REAL_JOIN(tmpdir, *args[1:])):
                mock_resp = MagicMock()
                mock_resp.text = f"```html\n{self.sample_html}\n```"
                mock_resp.usage_metadata = {}
                mock_generate.return_value = mock_resp

                mock_capture.return_value = [{"slide_number": 1, "bytes": b"fake"}]
                mock_inspect.side_effect = [
                    InspectionResult(passed=False, issues=["豆腐文字化け"], suggested_prompt_fix="絵文字修正"),
                    InspectionResult(passed=True, issues=[], suggested_prompt_fix=""),
                ]

                mock_runtime = MagicMock()
                mock_context = MagicMock()
                mock_context.messages = []
                mock_context.system_instruction = "Azureシステム指示"

                res_text, _, metadata = azure_report_agent.run_report_generation(
                    runtime=mock_runtime,
                    prompts=self.sample_prompts,
                    context=mock_context,
                    messages=self.sample_messages,
                    max_output_tokens=4096,
                    text_placeholder=self.mock_placeholder,
                    thought_status=self.mock_thought,
                )

                self.assertTrue(metadata["pdf_success"])
                self.assertEqual(mock_generate.call_count, 2)
                self.assertEqual(mock_inspect.call_count, 2)
                self.assertEqual(mock_render.call_count, 1)

    @patch("gp_chat.azure_report_agent._render_html_to_pdf", return_value=(True, None))
    @patch("gp_chat.report_visual_inspector.capture_slides_as_images")
    @patch("gp_chat.report_visual_inspector.inspect_slides_with_azure")
    @patch("gp_chat.azure_responses_router.generate_response")
    @patch("gp_chat.azure_report_agent._resolve_report_folder_name", return_value="test_folder")
    def test_azure_report_loop_max_retries_reached(
        self, mock_folder, mock_generate, mock_inspect, mock_capture, mock_render
    ):
        """Azure: 4回連続 FAIL（初回＋最大3回再作成）の場合、3回再試行でループを終了しPDF化すること。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("gp_chat.azure_report_agent.os.path.join", side_effect=lambda *args: REAL_JOIN(tmpdir, *args[1:])):
                mock_resp = MagicMock()
                mock_resp.text = f"```html\n{self.sample_html}\n```"
                mock_resp.usage_metadata = {}
                mock_generate.return_value = mock_resp

                mock_capture.return_value = [{"slide_number": 1, "bytes": b"fake"}]
                mock_inspect.return_value = InspectionResult(
                    passed=False, issues=["枠外はみ出し"], suggested_prompt_fix="縮小"
                )

                mock_runtime = MagicMock()
                mock_context = MagicMock()
                mock_context.messages = []
                mock_context.system_instruction = "Azureシステム指示"

                res_text, _, metadata = azure_report_agent.run_report_generation(
                    runtime=mock_runtime,
                    prompts=self.sample_prompts,
                    context=mock_context,
                    messages=self.sample_messages,
                    max_output_tokens=4096,
                    text_placeholder=self.mock_placeholder,
                    thought_status=self.mock_thought,
                )

                self.assertTrue(metadata["pdf_success"])
                self.assertEqual(mock_generate.call_count, 4)
                self.assertEqual(mock_inspect.call_count, 4)
                self.assertEqual(mock_render.call_count, 1)


if __name__ == "__main__":
    unittest.main()
