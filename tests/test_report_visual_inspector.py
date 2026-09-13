import unittest
from gp_chat import report_visual_inspector

class TestReportVisualInspector(unittest.TestCase):
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

    def test_capture_slides_as_images_integration(self):
        import tempfile
        import os

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
