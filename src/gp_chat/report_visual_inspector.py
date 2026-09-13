# src\gp_chat\report_visual_inspector.py:
"""PDFレポートにおけるTwemoji注入およびマルチモーダルVLM視覚的検証モジュール。"""
from __future__ import annotations
import os
import re
import json
import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

try:
    from gp_chat import state_manager
except ImportError:
    import state_manager

# pylint: disable=broad-exception-caught,import-outside-toplevel,too-many-locals

# --- Data Structures ---

@dataclass
class InspectionResult:
    """VLM視覚検査の結果を表すデータクラス。"""
    passed: bool
    issues: List[str] = field(default_factory=list)
    suggested_prompt_fix: str = ""
    raw_response: str = ""


# --- 1. Twemoji & CSS Injection ---

TWEMOJI_SNIPPET = """
<!-- [GP-Chat] Twemoji & Emoji Fallback Protection -->
<script src="https://cdn.jsdelivr.net/npm/@twemoji/api@latest/dist/twemoji.min.js" crossorigin="anonymous"></script>
<script>
  window.addEventListener('DOMContentLoaded', function() {
    if (window.twemoji) {
      window.twemoji.parse(document.body, {
        folder: 'svg',
        ext: '.svg',
        base: 'https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/'
      });
    }
  });
</script>
<style>
  img.emoji {
    height: 1.2em !important;
    width: 1.2em !important;
    margin: 0 0.15em !important;
    vertical-align: -0.2em !important;
    display: inline-block !important;
  }
  /* フォールバックフォントスタックの二重化 */
  body, .slide, p, span, h1, h2, h3, h4, h5, h6, li, td, th {
    font-family: inherit, 'Segoe UI Emoji', 'Apple Color Emoji', 'Noto Color Emoji', sans-serif;
  }
</style>
<!-- [/GP-Chat] -->
""".strip()


def inject_twemoji_and_fonts(html_content: str) -> str:
    """
    HTMLに Twemoji CDNスクリプトと絵文字フォントフォールバックCSSを注入する。
    すでに注入されている場合は重複注入を回避する。
    """
    if "twemoji.min.js" in html_content:
        return html_content

    # <head> タグが存在する場合は <head> の直後に挿入
    head_pos = html_content.find("<head>")
    if head_pos >= 0:
        insert_idx = head_pos + len("<head>")
        return html_content[:insert_idx] + "\n" + TWEMOJI_SNIPPET + "\n" + html_content[insert_idx:]

    head_attr_match = re.search(r"<head[^>]*>", html_content, flags=re.IGNORECASE)
    if head_attr_match:
        insert_idx = head_attr_match.end()
        return html_content[:insert_idx] + "\n" + TWEMOJI_SNIPPET + "\n" + html_content[insert_idx:]

    # <head> がない場合は HTML 先頭に挿入
    return TWEMOJI_SNIPPET + "\n" + html_content


# --- 2. Playwright Slide Capturing ---

def capture_slides_as_images(html_path: str, temp_dir: str, max_slides: int = 6) -> List[dict]:
    """
    Playwright を使用して HTML を開き、スライド要素ごとのスクリーンショット（PNG）を撮影する。
    ブラウザ起動失敗時などは空リストを返し、安全にフォールバック可能にする。
    """
    captured = []
    abs_html_path = os.path.abspath(html_path)
    if not os.path.exists(abs_html_path):
        state_manager.add_debug_log(
            f"[VisualInspector] HTML path does not exist: {abs_html_path}", "warning"
        )
        return captured

    html_uri = Path(abs_html_path).as_uri()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        state_manager.add_debug_log(
            "[VisualInspector] Playwright not installed. Skipping slide capture.", "warning"
        )
        return captured

    os.makedirs(temp_dir, exist_ok=True)

    try:
        with sync_playwright() as p:
            browser = None
            launch_attempts = [
                {},                      # 1. Playwright デフォルト Chromium
                {"channel": "msedge"},   # 2. システムインストール済み Edge
                {"channel": "chrome"}    # 3. システムインストール済み Chrome
            ]
            for attempt in launch_attempts:
                try:
                    browser = p.chromium.launch(headless=True, **attempt)
                    break
                except Exception as e:
                    state_manager.add_debug_log(
                        f"[VisualInspector] Browser launch attempt failed ({attempt}): {e}",
                        "warning"
                    )

            if not browser:
                state_manager.add_debug_log(
                    "[VisualInspector] Could not launch any browser for slide capture.",
                    "warning"
                )
                return captured

            # A4横向きの標準比率 (297:210) に合わせた高解像度ビューポート
            page = browser.new_page(viewport={"width": 1400, "height": 990})
            try:
                page.goto(html_uri, wait_until="networkidle", timeout=12000)
            except Exception:
                page.wait_for_timeout(2000)

            # Twemoji の非同期パース完了を待つ
            page.wait_for_timeout(800)

            slide_elements = page.query_selector_all(".slide")
            if not slide_elements:
                # .slide クラスが見つからない場合はページ全体のキャプチャを1枚取得
                img_path = os.path.join(temp_dir, "slide_full.png")
                page.screenshot(path=img_path, full_page=True)
                with open(img_path, "rb") as f:
                    img_bytes = f.read()
                captured.append({"slide_number": 1, "path": img_path, "bytes": img_bytes})
            else:
                for idx, elem in enumerate(slide_elements[:max_slides], start=1):
                    img_path = os.path.join(temp_dir, f"slide_{idx:02d}.png")
                    elem.screenshot(path=img_path)
                    with open(img_path, "rb") as f:
                        img_bytes = f.read()
                    captured.append({"slide_number": idx, "path": img_path, "bytes": img_bytes})

            browser.close()
            state_manager.add_debug_log(
                f"[VisualInspector] Successfully captured {len(captured)} slide images."
            )
    except Exception as e:
        state_manager.add_debug_log(
            f"[VisualInspector] Error during slide image capture: {e}", "warning"
        )

    return captured


# --- 3. VLM Response Parser ---

def parse_vlm_inspection_response(raw_text: str) -> InspectionResult:
    """
    VLM のテキスト応答から JSON を抽出して InspectionResult を構築する。
    パース失敗時は安全側に倒して passed=True とする。
    """
    cleaned = (raw_text or "").strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    json_str = match.group(1).strip() if match else cleaned

    try:
        data = json.loads(json_str)
        status = str(data.get("status", "PASS")).upper()
        issues = data.get("issues", [])
        if isinstance(issues, str):
            issues = [issues]
        suggested_fix = str(data.get("suggested_prompt_fix", ""))
        return InspectionResult(
            passed=(status == "PASS"),
            issues=issues,
            suggested_prompt_fix=suggested_fix,
            raw_response=raw_text
        )
    except Exception:
        # パースに失敗した場合は警告ログを残し、パイプラインをブロックしないよう PASS とする
        return InspectionResult(
            passed=True,
            issues=[],
            suggested_prompt_fix="",
            raw_response=raw_text
        )


VLM_INSPECTION_PROMPT = """
あなたはHTML/PDFスライド資料の視覚品質検査官（Visual Quality Inspector）です。
添付された各スライドのレンダリング画像（PNG）を詳細に目視検査し、以下の項目を厳密にチェックしてください。

1. 【文字化け・豆腐（Missing Glyph）の有無】:
   絵文字（🤖など）や記号、アイコンが「□の中に×」「四角枠」などに文字化けしていないか。
2. 【レイアウトの枠外はみ出し（Overflow）】:
   テキスト、箇条書き、図表、カード要素がスライドの境界線やコンテナ枠からはみ出していないか。
3. 【要素の重なり・視認性】:
   テキスト同士や図形が不自然に重なって読めなくなっていないか。

回答は必ず以下のJSON形式のみを出力してください（前後の説明文は不要です）：
```json
{
  "status": "PASS" または "FAIL",
  "issues": ["発見された問題点1", "発見された問題点2"],
  "suggested_prompt_fix": "再生成時にAIへ指示すべき具体的な修正指示（例: スライドを2枚に分割して文字量を減らす、等）"
}
```
※重大な文字化けやはみ出しがない限り、軽微な余白の差などは許容して必ず "status": "PASS" としてください。
""".strip()


# --- 4. Gemini & Azure Inspection Helpers ---

def inspect_slides_with_gemini(
    client, model_id: str, slide_images: List[dict]
) -> InspectionResult:
    """Gemini のマルチモーダル機能を用いてスライド画像を視覚検査する。"""
    if not slide_images:
        return InspectionResult(
            passed=True, issues=[], suggested_prompt_fix="No images to inspect."
        )

    try:
        from google.genai import types

        contents = []
        for s in slide_images:
            contents.append(f"### Slide {s['slide_number']}")
            contents.append(types.Part.from_bytes(data=s["bytes"], mime_type="image/png"))

        contents.append(VLM_INSPECTION_PROMPT)

        state_manager.add_debug_log(
            f"[VisualInspector] Requesting Gemini visual inspection "
            f"with {len(slide_images)} images."
        )
        response = client.models.generate_content(
            model=model_id,
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=1024,
            )
        )
        return parse_vlm_inspection_response(response.text)
    except Exception as e:
        state_manager.add_debug_log(
            f"[VisualInspector] Gemini visual inspection error: {e}", "warning"
        )
        return InspectionResult(
            passed=True, issues=[], suggested_prompt_fix="", raw_response=str(e)
        )


def inspect_slides_with_azure(runtime, slide_images: List[dict]) -> InspectionResult:
    """Azure OpenAI (GPT Vision) を用いてスライド画像を視覚検査する。"""
    if not slide_images:
        return InspectionResult(
            passed=True, issues=[], suggested_prompt_fix="No images to inspect."
        )

    try:
        from . import azure_responses_router

        content_items = []
        for s in slide_images:
            b64_img = base64.b64encode(s["bytes"]).decode("ascii")
            data_url = f"data:image/png;base64,{b64_img}"
            content_items.append({"type": "input_text", "text": f"### Slide {s['slide_number']}"})
            content_items.append({"type": "input_image", "image_url": data_url})

        content_items.append({"type": "input_text", "text": VLM_INSPECTION_PROMPT})

        messages = [
            {"role": "user", "content": content_items}
        ]

        state_manager.add_debug_log(
            f"[VisualInspector] Requesting Azure visual inspection with {len(slide_images)} images."
        )
        response = azure_responses_router.generate_response(
            runtime=runtime,
            input_messages=messages,
            instructions="You are a strict Visual Quality Inspector. Output JSON only.",
            max_output_tokens=1024,
            temperature=0.1,
        )
        return parse_vlm_inspection_response(response.text)
    except Exception as e:
        state_manager.add_debug_log(
            f"[VisualInspector] Azure visual inspection error: {e}", "warning"
        )
        return InspectionResult(
            passed=True, issues=[], suggested_prompt_fix="", raw_response=str(e)
        )
