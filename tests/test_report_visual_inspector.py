# tests/test_report_visual_inspector.py
"""PDFレポートの視覚監査（VLM検査、Twemoji注入、バッチ分割並行処理）に関する単体テスト。"""
# pylint: disable=line-too-long,missing-function-docstring
from unittest.mock import MagicMock, patch
import inspect
import tempfile
import os
import unittest

from gp_chat import report_visual_inspector
from gp_chat.report_visual_inspector import (
    InspectionResult,
    chunk_slide_images,
    merge_inspection_results,
)


class TestReportVisualInspector(unittest.TestCase):
    """VLM視覚監査および関連機能のテストスイート。"""

    def test_inject_twemoji_and_fonts_standard_html(self):
        raw_html = """<!DOCTYPE html>
<html>
<head>
    <title>Test Slide</title>
</head>
<body>
    <div class="slide"><h1>🤖 テストスライド</h1></div>
</body>
</html>"""
        injected = report_visual_inspector.inject_twemoji_and_fonts(raw_html)

        # Twemoji CDNスクリプトが含まれているか
        self.assertIn("twemoji.min.js", injected)
        self.assertIn("twemoji.parse", injected)

        # 絵文字フォールバックCSSが含まれているか
        self.assertIn("Segoe UI Emoji", injected)
        self.assertIn("img.emoji", injected)

        # 元のコンテンツが保持されているか
        self.assertIn("<h1>🤖 テストスライド</h1>", injected)

    def test_inject_twemoji_and_fonts_no_head(self):
        raw_html = """<div class="slide"><h1>💡 タイトル</h1></div>"""
        injected = report_visual_inspector.inject_twemoji_and_fonts(raw_html)

        self.assertIn("twemoji.min.js", injected)
        self.assertIn("Segoe UI Emoji", injected)
        self.assertIn("<h1>💡 タイトル</h1>", injected)

    def test_inject_twemoji_no_duplicate(self):
        raw_html = """<!DOCTYPE html>
<html>
<head>
    <title>Test</title>
</head>
<body>
    <div class="slide">Hello</div>
</body>
</html>"""
        injected1 = report_visual_inspector.inject_twemoji_and_fonts(raw_html)
        injected2 = report_visual_inspector.inject_twemoji_and_fonts(injected1)

        # 2回適用しても重複しないこと
        self.assertEqual(injected1.count("twemoji.min.js"), 1)
        self.assertEqual(injected2.count("twemoji.min.js"), 1)

    def test_parse_vlm_inspection_response_pass(self):
        resp_text = '{"status": "PASS", "issues": [], "suggested_prompt_fix": ""}'
        res = report_visual_inspector.parse_vlm_inspection_response(resp_text)
        self.assertTrue(res.passed)
        self.assertEqual(len(res.issues), 0)

    def test_parse_vlm_inspection_response_fail_markdown(self):
        resp_text = """```json
{
    "status": "FAIL",
    "issues": [
        "スライド1の見出しで記号が四角枠に文字化けしています",
        "スライド2のテキストがカード枠からはみ出しています"
    ],
    "suggested_prompt_fix": "スライド1の記号を修正し、スライド2の文字量を削減して2スライドに分割してください。"
}
```"""
        res = report_visual_inspector.parse_vlm_inspection_response(resp_text)
        self.assertFalse(res.passed)
        self.assertEqual(len(res.issues), 2)
        self.assertIn("文字化け", res.issues[0])
        self.assertIn("2スライドに分割", res.suggested_prompt_fix)

    def test_parse_vlm_inspection_response_invalid_json(self):
        resp_text = "特に問題は見当たりませんでした。良好です。"
        res = report_visual_inspector.parse_vlm_inspection_response(resp_text)
        # パース失敗時は安全側に倒して PASS とする
        self.assertTrue(res.passed)

    def test_chunk_slide_images_various_counts(self):
        """スライド画像リストの最大4枚分割（チャンク化）テスト。"""
        # 空リスト
        self.assertEqual(chunk_slide_images([]), [])

        # 3枚 (4枚未満)
        slides_3 = [{"slide_number": i} for i in range(1, 4)]
        chunks_3 = chunk_slide_images(slides_3, chunk_size=4)
        self.assertEqual(len(chunks_3), 1)
        self.assertEqual(len(chunks_3[0]), 3)

        # 4枚 (境界値)
        slides_4 = [{"slide_number": i} for i in range(1, 5)]
        chunks_4 = chunk_slide_images(slides_4, chunk_size=4)
        self.assertEqual(len(chunks_4), 1)
        self.assertEqual(len(chunks_4[0]), 4)

        # 5枚 (4 + 1)
        slides_5 = [{"slide_number": i} for i in range(1, 6)]
        chunks_5 = chunk_slide_images(slides_5, chunk_size=4)
        self.assertEqual(len(chunks_5), 2)
        self.assertEqual(len(chunks_5[0]), 4)
        self.assertEqual(len(chunks_5[1]), 1)

        # 12枚 (4 + 4 + 4)
        slides_12 = [{"slide_number": i} for i in range(1, 13)]
        chunks_12 = chunk_slide_images(slides_12, chunk_size=4)
        self.assertEqual(len(chunks_12), 3)
        self.assertEqual(len(chunks_12[0]), 4)
        self.assertEqual(len(chunks_12[1]), 4)
        self.assertEqual(len(chunks_12[2]), 4)

    def test_merge_inspection_results(self):
        """バッチ検査結果のマージ集約処理のテスト。"""
        # 空リスト
        empty_res = merge_inspection_results([])
        self.assertTrue(empty_res.passed)
        self.assertEqual(empty_res.issues, [])

        # 全件PASS
        p1 = InspectionResult(passed=True, issues=[], suggested_prompt_fix="")
        p2 = InspectionResult(passed=True, issues=[], suggested_prompt_fix="")
        res_pass = merge_inspection_results([p1, p2])
        self.assertTrue(res_pass.passed)
        self.assertEqual(res_pass.issues, [])

        # 1件FAIL, 1件PASS
        f1 = InspectionResult(
            passed=False,
            issues=["スライド2の文字あふれ", "共通の余白不足"],
            suggested_prompt_fix="スライド2のフォント縮小"
        )
        f2 = InspectionResult(
            passed=False,
            issues=["共通の余白不足", "スライド6の重なり"],
            suggested_prompt_fix="スライド6の配置調整"
        )
        res_fail = merge_inspection_results([p1, f1, f2])
        self.assertFalse(res_fail.passed)
        # 重複排除の確認
        self.assertEqual(
            res_fail.issues,
            ["スライド2の文字あふれ", "共通の余白不足", "スライド6の重なり"]
        )
        # 修正アドバイスの結合確認
        self.assertIn("スライド2のフォント縮小", res_fail.suggested_prompt_fix)
        self.assertIn("スライド6の配置調整", res_fail.suggested_prompt_fix)

    def test_capture_slides_as_images_default_max_slides(self):
        """capture_slides_as_images のデフォルト max_slides が 12 であることの検証。"""
        sig = inspect.signature(report_visual_inspector.capture_slides_as_images)
        self.assertEqual(sig.parameters["max_slides"].default, 12)

    @patch("gp_chat.report_visual_inspector._inspect_single_chunk_gemini")
    def test_inspect_slides_with_gemini_batch_parallel(self, mock_chunk_inspect):
        """Gemini による12枚スライド（3バッチ並行監査）のモック検証。"""
        mock_chunk_inspect.side_effect = [
            InspectionResult(passed=True, issues=[], suggested_prompt_fix=""),
            InspectionResult(passed=False, issues=["スライド6の枠外はみ出し"], suggested_prompt_fix="文字量削減"),
            InspectionResult(passed=True, issues=[], suggested_prompt_fix=""),
        ]

        dummy_slides = [{"slide_number": i, "bytes": b"fake_png"} for i in range(1, 13)]
        mock_client = MagicMock()

        result = report_visual_inspector.inspect_slides_with_gemini(
            client=mock_client,
            model_id="gemini-4-argon",
            slide_images=dummy_slides,
        )

        self.assertEqual(mock_chunk_inspect.call_count, 3)
        self.assertFalse(result.passed)
        self.assertIn("スライド6の枠外はみ出し", result.issues)
        self.assertIn("文字量削減", result.suggested_prompt_fix)

    @patch("gp_chat.report_visual_inspector._inspect_single_chunk_azure")
    def test_inspect_slides_with_azure_batch_parallel(self, mock_chunk_inspect):
        """Azure による12枚スライド（3バッチ並行監査）のモック検証。"""
        mock_chunk_inspect.side_effect = [
            InspectionResult(passed=True, issues=[], suggested_prompt_fix=""),
            InspectionResult(passed=True, issues=[], suggested_prompt_fix=""),
            InspectionResult(passed=False, issues=["スライド11の文字化け"], suggested_prompt_fix="記号修正"),
        ]

        dummy_slides = [{"slide_number": i, "bytes": b"fake_png"} for i in range(1, 13)]
        mock_runtime = MagicMock()

        result = report_visual_inspector.inspect_slides_with_azure(
            runtime=mock_runtime,
            slide_images=dummy_slides,
        )

        self.assertEqual(mock_chunk_inspect.call_count, 3)
        self.assertFalse(result.passed)
        self.assertIn("スライド11の文字化け", result.issues)
        self.assertIn("記号修正", result.suggested_prompt_fix)

    def test_capture_slides_as_images_integration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            html_content = """<!DOCTYPE html>
<html>
<head><title>Slide Test</title></head>
<body>
    <div class="slide" style="width: 297mm; height: 210mm; background: #fff; padding: 20px;">
        <h1>Slide 1 🤖</h1>
    </div>
    <div class="slide" style="width: 297mm; height: 210mm; background: #fff; padding: 20px;">
        <h1>Slide 2 💡</h1>
    </div>
</body>
</html>"""
            html_path = os.path.join(tmpdir, "test.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)

            images = report_visual_inspector.capture_slides_as_images(html_path, tmpdir, max_slides=2)
            # ブラウザが起動可能な環境であれば画像が取得される
            if images:
                self.assertEqual(len(images), 2)
                self.assertTrue(os.path.exists(images[0]["path"]))
                self.assertGreater(len(images[0]["bytes"]), 0)


if __name__ == "__main__":
    unittest.main()
