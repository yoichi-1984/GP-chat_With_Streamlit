import os
import sys
import asyncio
import json
import pydantic
from typing import List, Literal, Optional, Dict, Any
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from google.genai import types
from playwright.sync_api import sync_playwright

if sys.platform == 'win32':
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

try:
    from gp_chat import state_manager
    from gp_chat import llm_router
except ImportError:
    import state_manager
    import llm_router

# --- Pydantic DSL スキーマ定義 ---

class CropAreaSchema(pydantic.BaseModel):
    ymin: int = pydantic.Field(..., description="切り出し領域の上端 (0-1000)")
    xmin: int = pydantic.Field(..., description="切り出し領域の左端 (0-1000)")
    ymax: int = pydantic.Field(..., description="切り出し領域の下端 (0-1000)")
    xmax: int = pydantic.Field(..., description="切り出し領域の右端 (0-1000)")

class PlaceholderContent(pydantic.BaseModel):
    idx: int = pydantic.Field(..., description="流し込み先のプレースホルダーインデックス (テンプレート定義のもの)。")
    text_content: Optional[str] = pydantic.Field(
        None,
        description="流し込むテキスト。箇条書きの場合は各要素の先頭に '• ' を付けず、改行 '\\n' で区切って複数行のテキストとして記述してください（PowerPoint側で自動的に箇条書きが適用されるため）。"
    )
    image_prompt: Optional[str] = pydantic.Field(
        None,
        description="このプレースホルダーが IMAGE タイプの場合に、AI画像生成 (Imagen 3) でイラストを自動生成させるための英語プロンプト。"
    )
    use_user_image: bool = pydantic.Field(
        False,
        description="ユーザー添付画像を使用する枠である場合は True。"
    )
    crop_instruction: Optional[str] = pydantic.Field(
        None,
        description="ユーザー添付画像を使用する際のトリミング指示。"
    )

class SlideNode(pydantic.BaseModel):
    slide_number: int
    title: str = pydantic.Field(..., description="スライドのタイトル。")
    layout_name: str = pydantic.Field(..., description="使用するテンプレートのスライドレイアウト名（動的に指示された一覧から正確に一致するものを選択）。")
    placeholders: List[PlaceholderContent] = pydantic.Field(..., description="プレースホルダーごとの流し込みデータの一覧。タイトル(TITLE/CENTER_TITLE)のプレースホルダー(idx=0等)にも必ずタイトル文字列を指定してください。")

class PresentationDSLSchema(pydantic.BaseModel):
    presentation_title: str = pydantic.Field(..., max_length=30)
    slides: List[SlideNode]

# --- テンプレートレイアウトの自動解析スキャン ---

def scan_template_layouts(template_path: str) -> Dict[str, Any]:
    """PowerPointテンプレートを解析し、LLMに渡すためのレイアウト辞書情報を構築する"""
    layouts = {}
    if not os.path.exists(template_path):
        return layouts
        
    try:
        prs = Presentation(template_path)
        for i, layout in enumerate(prs.slide_layouts):
            placeholders = []
            for ph in layout.placeholders:
                ph_type = ph.placeholder_format.type
                ph_type_name = "TEXT"
                if ph_type == 18:  # PICTURE
                    ph_type_name = "IMAGE"
                elif ph_type == 12:  # TABLE
                    ph_type_name = "TABLE"
                
                placeholders.append({
                    "idx": ph.placeholder_format.idx,
                    "name": ph.name,
                    "type": ph_type_name,
                    "left_in": round(ph.left.inches, 3),
                    "top_in": round(ph.top.inches, 3),
                    "width_in": round(ph.width.inches, 3),
                    "height_in": round(ph.height.inches, 3)
                })
            layouts[layout.name] = {
                "layout_index": i,
                "placeholders": placeholders
            }
    except Exception as e:
        state_manager.add_debug_log(f"[PPTXAgent] Error scanning template layouts: {e}", "warning")
    return layouts

# --- 画像処理ユーティリティの実装 ---

def generate_ai_image_with_nano_banana(client, prompt: str, output_path: str) -> bool:
    """gemini-3.1-flash-lite-image (Nano Banana 2 Lite) を用いてオンデマンドで画像を生成し保存する。404エラーの場合は imagen-3.0-generate-002 へフォールバック。"""
    try:
        state_manager.add_debug_log(f"[PPTXAgent] Generating AI image using Nano Banana 2 Lite. Prompt: {prompt}")
        try:
            response = client.models.generate_images(
                model="gemini-3.1-flash-lite-image",
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    output_mime_type="image/png",
                    aspect_ratio="16:9",
                )
            )
        except Exception as e:
            err_msg = str(e)
            if "404" in err_msg or "NOT_FOUND" in err_msg or "permission" in err_msg.lower():
                state_manager.add_debug_log(f"[PPTXAgent] Nano Banana 2 Lite not available. Falling back to imagen-3.0-generate-002. Error: {e}", "warning")
                response = client.models.generate_images(
                    model="imagen-3.0-generate-002",
                    prompt=prompt,
                    config=types.GenerateImagesConfig(
                        number_of_images=1,
                        output_mime_type="image/png",
                        aspect_ratio="16:9",
                    )
                )
            else:
                raise
                
        if response.generated_images:
            img_data = response.generated_images[0].image.image_bytes
            with open(output_path, "wb") as f:
                f.write(img_data)
            state_manager.add_debug_log(f"[PPTXAgent] AI image generated and saved to {output_path}")
            return True
        else:
            state_manager.add_debug_log("[PPTXAgent] Image generation returned no images.", "warning")
    except Exception as e:
        state_manager.add_debug_log(f"[PPTXAgent] Image generation pipeline failed: {e}", "warning")
    return False

def crop_user_image_with_llm(client, image_bytes: bytes, image_mime_type: str, instruction: str, output_path: str) -> bool:
    """Geminiマルチモーダルで画像内の対象物を検出し、Pillowでトリミングして保存する"""
    try:
        from PIL import Image
        import io

        state_manager.add_debug_log(f"[PPTXAgent] Cropping user image based on instruction: {instruction}")

        # 1. 座標の推論要求
        system_instruction = (
            "あなたは画像認識および情報トリミングのスペシャリストです。\n"
            "入力された画像の中から、ユーザーの指示内容（切り出したい対象）に最も一致する部分のバウンディングボックスを決定してください。\n"
            "画像全体のサイズを縦横 1000 と仮定した相対座標（0〜1000の整数）で、[ymin, xmin, ymax, xmax] の形で座標を出力してください。"
        )

        gen_config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.1,
            response_mime_type="application/json",
            response_schema=CropAreaSchema,
        )

        image_part = types.Part.from_bytes(data=image_bytes, mime_type=image_mime_type)
        user_prompt = f"指示: 「{instruction}」\n上記指示に合致する要素の座標範囲 [ymin, xmin, ymax, xmax] をJSONで出力してください。"

        result = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=[image_part, user_prompt],
            config=gen_config
        )

        coords = CropAreaSchema.model_validate_json(result.text)
        state_manager.add_debug_log(f"[PPTXAgent] LLM detected crop area: {coords}")

        # 2. Pillowによる物理トリミング
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size

        # 境界値のクリッピング
        left = int(max(0, min(1000, coords.xmin)) / 1000 * w)
        top = int(max(0, min(1000, coords.ymin)) / 1000 * h)
        right = int(max(0, min(1000, coords.xmax)) / 1000 * w)
        bottom = int(max(0, min(1000, coords.ymax)) / 1000 * h)

        # 最低サイズ保証
        if right - left < 10: right = min(w, left + 10)
        if bottom - top < 10: bottom = min(h, top + 10)

        cropped_img = img.crop((left, top, right, bottom))
        cropped_img.save(output_path)
        state_manager.add_debug_log(f"[PPTXAgent] Image cropped and saved: {output_path}")
        return True
    except Exception as e:
        state_manager.add_debug_log(f"[PPTXAgent] User image cropping failed: {e}", "warning")
        return False

# --- HTML/CSS テンプレート生成ヘルパー (幾何学検証用) ---

def generate_slide_html(slide: SlideNode, layouts_info: Dict[str, Any], font_size_offset: int = 0) -> str:
    """テンプレートのレイアウト実座標から幾何学検証用HTMLを動的に生成する"""
    bullet_fs = 18 + font_size_offset
    
    layout = layouts_info.get(slide.layout_name)
    layout_html = ""
    
    if layout:
        for ph in layout["placeholders"]:
            idx = ph["idx"]
            left_in = ph["left_in"]
            top_in = ph["top_in"]
            width_in = ph["width_in"]
            height_in = ph["height_in"]
            
            # 対応するコンテンツをLLM出力から探す
            content_text = ""
            for content in slide.placeholders:
                if content.idx == idx:
                    if content.text_content:
                        bullets = content.text_content.split("\n")
                        content_text = "<ul>" + "".join(f"<li>{b}</li>" for b in bullets if b) + "</ul>"
                    break
            
            layout_html += f"""
            <div class="dynamic-text-block" id="ph_{idx}_{slide.slide_number}" style="position: absolute; left: {left_in}in; top: {top_in}in; width: {width_in}in; height: {height_in}in; font-size: {bullet_fs}pt; overflow: hidden; line-height: 1.5; color: #374151;">
              {content_text}
            </div>
            """
    else:
        # テンプレートがない場合のシンプルなフォールバック
        layout_html = f"""
        <div class="dynamic-text-block" id="fallback_bullets_{slide.slide_number}" style="position: absolute; left: 1.0in; top: 2.2in; width: 11.333in; height: 4.0in; font-size: {bullet_fs}pt; overflow: hidden; line-height: 1.5; color: #374151;">
          {slide.title}
        </div>
        """

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{
      margin: 0;
      padding: 0;
      background: #ffffff;
      font-family: 'Meiryo', 'Malgun Gothic', sans-serif;
    }}
    .slide-container {{
      width: 13.333in;
      height: 7.5in;
      position: relative;
      background: #ffffff;
      box-sizing: border-box;
      overflow: hidden;
    }}
    .title {{
      position: absolute;
      left: 1.0in;
      top: 0.6in;
      width: 11.333in;
      height: 1.0in;
      font-size: 32pt;
      font-weight: bold;
      color: #111827;
      margin: 0;
      padding: 0;
      line-height: 1.2;
      display: flex;
      align-items: center;
    }}
    .dynamic-text-block {{
      box-sizing: border-box;
      overflow: hidden;
      word-wrap: break-word;
    }}
    ul {{
      margin: 0;
      padding-left: 20pt;
    }}
    li {{
      margin-bottom: 10pt;
    }}
  </style>
</head>
<body>
  <div class="slide-container">
    <div class="title dynamic-text-block" id="title_{slide.slide_number}">{slide.title}</div>
    {layout_html}
  </div>
</body>
</html>
"""
    return html

# --- PPTX 物理レンダリングヘルパー ---

def render_pptx_slide(prs: Presentation, slide_data: SlideNode, font_size_offset: int = 0, current_index: int = 0, total_slides: int = 0, image_paths: Dict[int, str] = None, has_template: bool = False, blank_layout = None):
    """SlideNodeデータから テンプレートのプレースホルダーへ直接データを流し込みレンダリングする"""
    if blank_layout is None:
        blank_layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank_layout)

    # テンプレートを使用している場合
    if has_template:
        ph_map = {ph.placeholder_format.idx: ph for ph in slide.placeholders}
        
        # 共通要素：スライド番号の書き込み (SLIDE_NUMBER タイプ)
        for ph in slide.placeholders:
            if ph.placeholder_format.type == 13:  # SLIDE_NUMBER
                ph.text = f"{current_index + 1} / {total_slides}"
                for p in ph.text_frame.paragraphs:
                    p.font.name = "Meiryo"
                    p.font.size = Pt(10)
        
        # LLMから出力されたプレースホルダー情報を処理
        for content in slide_data.placeholders:
            idx = content.idx
            if idx not in ph_map:
                continue
                
            ph = ph_map[idx]
            
            # テキストコンテンツの流し込み
            if content.text_content:
                ph.text = content.text_content
                # フォントのメイリオ統一とサイズ調整
                for paragraph in ph.text_frame.paragraphs:
                    paragraph.font.name = "Meiryo"
                    if font_size_offset != 0 and paragraph.font.size:
                        paragraph.font.size = Pt(max(10, paragraph.font.size.pt + font_size_offset))
            
            # 画像コンテンツの流し込み
            elif image_paths and idx in image_paths:
                img_path = image_paths[idx]
                if os.path.exists(img_path):
                    try:
                        # プレースホルダーの物理的な位置とサイズを取得
                        left = ph.left
                        top = ph.top
                        width = ph.width
                        height = ph.height
                        
                        # プレースホルダーの位置に画像を挿入
                        slide.shapes.add_picture(img_path, left, top, width, height)
                        
                        # 元のプレースホルダー（ゴースト）を削除
                        sp = ph._element
                        sp.getparent().remove(sp)
                    except Exception as e:
                        state_manager.add_debug_log(f"[PPTXAgent] Failed to insert image to placeholder idx={idx}: {e}", "warning")

        # AIが使用しなかった不要なプレースホルダー（「タイトルを追加」や「画像を追加」の枠線）を完全に消去する
        used_idxs = set(content.idx for content in slide_data.placeholders)
        content_ph_types = {1, 2, 3, 4, 7, 12, 18} # 主要なコンテンツ用プレースホルダータイプ
        for shape in list(slide.shapes):
            if shape.is_placeholder:
                ph_type = shape.placeholder_format.type
                idx = shape.placeholder_format.idx
                if ph_type in content_ph_types and idx not in used_idxs:
                    try:
                        sp = shape._element
                        sp.getparent().remove(sp)
                    except Exception as e:
                        pass
    else:
        # フォールバック: テンプレートがない場合のマニュアル簡易レンダリング
        from pptx.dml.color import RGBColor
        COLOR_BG = RGBColor(0xff, 0xff, 0xff)
        COLOR_TEXT_MAIN = RGBColor(0x0f, 0x17, 0x2a)
        
        bg_shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
        bg_shape.fill.solid()
        bg_shape.fill.fore_color.rgb = COLOR_BG
        bg_shape.line.fill.background()

        tx_title = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(11.733), Inches(0.8))
        tx_title.text_frame.text = slide_data.title
        tx_title.text_frame.paragraphs[0].font.name = "Meiryo"
        tx_title.text_frame.paragraphs[0].font.size = Pt(32)
        tx_title.text_frame.paragraphs[0].font.bold = True
        tx_title.text_frame.paragraphs[0].font.color.rgb = COLOR_TEXT_MAIN

        tx_body = slide.shapes.add_textbox(Inches(0.8), Inches(1.8), Inches(11.733), Inches(4.5))
        tf = tx_body.text_frame
        tf.word_wrap = True
        for content in slide_data.placeholders:
            if content.text_content:
                p = tf.add_paragraph()
                p.text = content.text_content
                p.font.name = "Meiryo"
                p.font.size = Pt(18 + font_size_offset)

# --- Playwright 同期バリデーション実行ヘルパー ---

def validate_slide_overflow(temp_dir: str, slides: List[SlideNode], offsets: List[int]) -> List[dict]:
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for slide in slides:
            html_path = os.path.join(temp_dir, f"{slide.slide_number:02d}.html")
            res = validate_single_slide(browser, html_path, slide.slide_number)
            results.append(res)
        browser.close()
    return results

def validate_single_slide(browser, html_path: str, slide_number: int) -> dict:
    page = browser.new_page()
    page.set_viewport_size({"width": 1280, "height": 720})
    file_uri = Path(os.path.abspath(html_path)).as_uri()
    
    page.goto(file_uri)
    page.wait_for_load_state("networkidle")
    
    overflow_js = """
    () => {
        const targets = document.querySelectorAll('.dynamic-text-block');
        for (let el of targets) {
            if (el.scrollHeight > el.clientHeight || el.scrollWidth > el.clientWidth) {
                return {
                    overflowed: true,
                    element_id: el.id,
                    text_content: el.innerText,
                    available_height: el.clientHeight,
                    required_height: el.scrollHeight
                };
            }
        }
        return { overflowed: false };
    }
    """
    res = page.evaluate(overflow_js)
    res["slide_number"] = slide_number
    page.close()
    return res

# --- PPTXAgent 本体クラス ---

class PPTXAgent:
    def __init__(self, client):
        self.llm_clients = llm_router.coerce_llm_clients(client)
        state_manager.add_debug_log("[PPTXAgent] Initialized successfully.")

    def generate_presentation_pipeline(self, chat_history: List[dict], session_id: str, model_id: str = "gemini-3.5-flash", user_images: List[dict] = None) -> str:
        """会話履歴およびユーザー添付画像リストからPowerPoint資料を作成する同期メインパイプライン。"""
        import streamlit as st
        
        current_report_folder = st.session_state.get("current_report_folder")
        if not current_report_folder:
            current_chat_filename = st.session_state.get("current_chat_filename")
            if current_chat_filename:
                folder_name = os.path.splitext(os.path.basename(current_chat_filename))[0]
            else:
                folder_name = f"pptx_{session_id[:8]}"
            folder_name = folder_name[:80] or "pptx_chat"
        else:
            folder_name = current_report_folder
            
        output_dir = os.path.join("slide_data", folder_name)
        os.makedirs(output_dir, exist_ok=True)
        
        temp_dir = os.path.join("temp_workspace", session_id)
        os.makedirs(temp_dir, exist_ok=True)
        
        pptx_number = 1
        for filename in os.listdir(output_dir):
            stem, ext = os.path.splitext(filename)
            if ext.lower() == ".pptx" and stem.isdigit():
                pptx_number = max(pptx_number, int(stem) + 1)
        
        final_pptx_path = os.path.abspath(os.path.join(output_dir, f"{pptx_number:02d}.pptx"))

        # --- テンプレートの自動ロードと解析スキャン ---
        current_dir = os.path.dirname(os.path.abspath(__file__))
        template_pptx = os.path.join(current_dir, "format.pptx")
        template_potx = os.path.join(current_dir, "format.potx")
        
        template_path = None
        if os.path.exists(template_pptx):
            template_path = template_pptx
        elif os.path.exists(template_potx):
            template_path = template_potx

        layouts_info = {}
        has_template = False
        if template_path:
            try:
                # 3枚以上のスライドがあることを確認
                check_prs = Presentation(template_path)
                if len(check_prs.slides) >= 3:
                    layouts_info = scan_template_layouts(template_path)
                    has_template = True
                    state_manager.add_debug_log(f"[PPTXAgent] Scanned {len(layouts_info)} layouts from format.pptx template.")
                else:
                    state_manager.add_debug_log("[PPTXAgent] Template does not have at least 3 slides.", "warning")
            except Exception as e:
                state_manager.add_debug_log(f"[PPTXAgent] Error inspecting template at start: {e}", "warning")

        # --- 第1層: 構造化 JSON 生成 ---
        state_manager.add_debug_log("[PPTXAgent] Step 1: Requesting Presentation Structure (JSON Schema)")
        
        # テンプレートレイアウト情報をプロンプトに注入
        template_instruction = ""
        if has_template:
            template_instruction = (
                "\n\n【利用可能なスライドテンプレートレイアウト情報】\n"
                "現在読み込まれている format.pptx テンプレートには以下のスライドレイアウトが定義されています。\n"
                "スライドごとに、'layout_name' には以下のいずれかのレイアウト名（大文字小文字・日本語含め【完全に一致する文字列】）を指定してください。\n"
                "また、'placeholders' の中では、指定したレイアウトの 'placeholders' に定義されている 'idx' を指定し、流し込むデータを指定してください。\n"
            )
            for name, details in layouts_info.items():
                ph_desc = []
                for ph in details["placeholders"]:
                    ph_desc.append(f"  * idx={ph['idx']} (タイプ: {ph['type']}, 名前: '{ph['name']}')")
                template_instruction += f"- レイアウト名: '{name}'\n  使用可能な入力枠 (placeholders):\n" + "\n".join(ph_desc) + "\n"
        else:
            template_instruction = (
                "\n\n(テンプレートがロードされなかったため、デフォルトの白紙レイアウトで生成します。)\n"
                "layout_name には 'blank' などの仮の文字列を入れ、placeholders は idx=0 などのダミーのテキストを流し込んでください。"
            )

        system_instruction = (
            "あなたはPowerPoint資料の構造化プロのデザイナーです。\n"
            "これまでの会話履歴を参照して、最終報告書やプレゼンテーション用の構成ストーリーを作成してください。\n"
            "提示された PresentationDSLSchema に従って、論理的に厳格で情報の引き算がなされたスライド構成をJSONとして出力してください。\n"
            "スライド枚数は3〜6枚が適切です。\n"
            "各箇条書きは文字溢れを防ぐため必ず30文字以内で要約してください。\n"
            "スライド全体のタイトルも placeholders の中に適切な TITLE または CENTER_TITLE タイプがある場合は必ず含めて出力してください。"
            + template_instruction
        )
        
        gen_config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=65536,
            temperature=0.2,
            response_mime_type="application/json",
            response_schema=PresentationDSLSchema,
        )
        
        chat_contents = []
        for msg in chat_history:
            if msg["role"] == "system":
                continue
            chat_contents.append(
                types.Content(
                    role=msg["role"],
                    parts=[types.Part.from_text(text=msg["content"])]
                )
            )
        
        chat_contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text="これまでのすべての議論を踏まえて、最高品質のスライド資料構成案JSONを出力してください。")]
            )
        )

        result = llm_router.generate_content_with_route(
            llm_clients=self.llm_clients,
            model_id=model_id,
            contents=chat_contents,
            config=gen_config,
            mode="pptx_structure",
            logger=state_manager.add_debug_log
        )
        
        presentation_data = PresentationDSLSchema.model_validate_json(result.text)
        state_manager.add_debug_log(f"[PPTXAgent] Storyline established. Title: {presentation_data.presentation_title}, Slides: {len(presentation_data.slides)}")

        # --- 第2層 & 第3層: 物理マッピング & 幾何学バリデーションループ ---
        
        slides = presentation_data.slides
        offsets = [0] * len(slides)
        
        for retry_loop in range(3):
            state_manager.add_debug_log(f"[PPTXAgent] Validation Round {retry_loop + 1}")
            
            for i, slide in enumerate(slides):
                html_content = generate_slide_html(slide, layouts_info, font_size_offset=offsets[i])
                html_path = os.path.join(temp_dir, f"{slide.slide_number:02d}.html")
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
            
            validation_results = validate_slide_overflow(temp_dir, slides, offsets)
            overflowed_slides = [res for res in validation_results if res.get("overflowed")]
            
            if not overflowed_slides:
                state_manager.add_debug_log("[PPTXAgent] Geometry validation passed. No overflows detected!")
                break
                
            if retry_loop == 2:
                state_manager.add_debug_log("[PPTXAgent] Retries exhausted. Applying emergency font size shrink (-2pt) for overflowed slides.")
                for res in overflowed_slides:
                    idx = next(idx for idx, s in enumerate(slides) if s.slide_number == res["slide_number"])
                    offsets[idx] = -2
                break
                
            state_manager.add_debug_log(f"[PPTXAgent] Overflows detected on {len(overflowed_slides)} slides. Starting Self-Correction...")
            
            for res in overflowed_slides:
                slide_num = res["slide_number"]
                idx = next(idx for idx, s in enumerate(slides) if s.slide_number == slide_num)
                target_slide = slides[idx]
                
                scale = res["available_height"] / max(res["required_height"], 1)
                
                # エラーのあるプレースホルダーを取得
                target_ph_idx = int(res["element_id"].split("_")[1])
                target_ph = next((p for p in target_slide.placeholders if p.idx == target_ph_idx), None)
                target_text = target_ph.text_content if target_ph else ""
                
                retry_prompt = (
                    f"【レイアウトエラー検知】\n"
                    f"スライド番号: {slide_num}\n"
                    f"エラー要素 (プレースホルダー idx): {target_ph_idx}\n"
                    f"現在のテキスト: \"{target_text}\"\n"
                    f"物理的許容高さ: {res['available_height']}px\n"
                    f"要求高さ: {res['required_height']}px\n\n"
                    f"上記要素で文字溢れ（Overflow）が発生しました。原因は文字数が多すぎるか、要素幅に対して改行数が多すぎることです。\n"
                    f"現在のスライド「{target_slide.title}」のプレースホルダー(idx={target_ph_idx})の箇条書きテキストを、情報密度を削ぎ落として約 {scale:.2f} 倍（文字数として30%〜50%削減）に要約・圧縮し、"
                    f"文字溢れが絶対に発生しない新しい PlaceholderContent を生成してください。\n"
                    f"出力は以下のJSON構造（Schema）に従うこと。"
                )
                
                correction_config = types.GenerateContentConfig(
                    system_instruction="あなたは短縮・要約のスペシャリストです。指定されたPydanticスキーマに厳密に準拠したJSONを返してください。",
                    max_output_tokens=4096,
                    temperature=0.2,
                    response_mime_type="application/json",
                    response_schema=PlaceholderContent,
                )
                
                correction_result = llm_router.generate_content_with_route(
                    llm_clients=self.llm_clients,
                    model_id="gemini-3.5-flash",
                    contents=[types.Content(role="user", parts=[types.Part.from_text(text=retry_prompt)])],
                    config=correction_config,
                    mode="pptx_correction",
                    logger=state_manager.add_debug_log
                )
                
                new_content = PlaceholderContent.model_validate_json(correction_result.text)
                # プレースホルダーの置き換え
                for p_idx, p_item in enumerate(slides[idx].placeholders):
                    if p_item.idx == target_ph_idx:
                        slides[idx].placeholders[p_idx] = new_content
                        break

        # --- 画像処理（生成 & トリミング）の実行 ---
        # スライド番号 -> プレースホルダーidx -> 画像ファイルパス の2重辞書
        slide_images = {}
        for slide in slides:
            slide_num = slide.slide_number
            slide_images[slide_num] = {}
            
            for content in slide.placeholders:
                # 画像の自動生成
                if content.image_prompt:
                    out_path = os.path.join(temp_dir, f"ai_gen_{slide_num}_{content.idx}.png")
                    success = generate_ai_image_with_nano_banana(
                        client=self.llm_clients.standard_client,
                        prompt=content.image_prompt,
                        output_path=out_path
                    )
                    if success:
                        slide_images[slide_num][content.idx] = out_path
                        
                # ユーザー画像の処理
                elif content.use_user_image and user_images:
                    # 最初の画像をデフォルトで使用
                    user_img = user_images[0]
                    img_bytes = user_img["bytes"]
                    img_mime = user_img["type"]
                    
                    out_path = os.path.join(temp_dir, f"user_processed_{slide_num}_{content.idx}.png")
                    
                    if content.crop_instruction:
                        # クロップ処理
                        success = crop_user_image_with_llm(
                            client=self.llm_clients.standard_client,
                            image_bytes=img_bytes,
                            image_mime_type=img_mime,
                            instruction=content.crop_instruction,
                            output_path=out_path
                        )
                        if success:
                            slide_images[slide_num][content.idx] = out_path
                    else:
                        # そのまま保存
                        try:
                            with open(out_path, "wb") as f:
                                f.write(img_bytes)
                            slide_images[slide_num][content.idx] = out_path
                        except Exception as e:
                            state_manager.add_debug_log(f"[PPTXAgent] Saving user image failed: {e}", "warning")

        # --- 第4層: 物理 PowerPoint 生成 ---
        state_manager.add_debug_log("[PPTXAgent] Step 4: Generating physical PowerPoint presentation")
        
        if has_template:
            try:
                prs = Presentation(template_path)
            except Exception as e:
                state_manager.add_debug_log(f"[PPTXAgent] Failed to load template, using default blank: {e}", "warning")
                prs = Presentation()
                has_template = False
        else:
            prs = Presentation()
            
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)
        
        # 適切なレイアウト（白紙/タイトル）を探すヘルパー関数
        def find_layout_by_name(prs, name_str, fallback_idx):
            for l in prs.slide_layouts:
                if l.name == name_str:
                    return l
            if len(prs.slide_layouts) > fallback_idx:
                return prs.slide_layouts[fallback_idx]
            return prs.slide_layouts[0]

        # テンプレートに合わせたレイアウト選定
        title_layout = find_layout_by_name(prs, "タイトルのみ", 0)
        blank_layout = find_layout_by_name(prs, "コンテンツ 2", 6)

        # --- 表紙（1枚目）の生成 & テキスト流し込み ---
        COLOR_PRIMARY = RGBColor(0x1e, 0x3a, 0x8a)     # 深青
        COLOR_WHITE = RGBColor(0xff, 0xff, 0xff)       # 白
        COLOR_TEXT_MUTED = RGBColor(0x64, 0x74, 0x8b)  # 中グレー

        if has_template:
            # 1枚目をそのまま表紙スライドとして再利用
            title_slide = prs.slides[0]
            title_written = False
            for shape in title_slide.shapes:
                if shape.is_placeholder:
                    ph_type = shape.placeholder_format.type
                    if ph_type == 1 or ph_type == 3:  # TITLE / CENTER_TITLE
                        shape.text = presentation_data.presentation_title
                        for paragraph in shape.text_frame.paragraphs:
                            paragraph.font.name = "Meiryo"
                            paragraph.font.bold = True
                        title_written = True
                    elif ph_type == 2:  # SUBTITLE
                        shape.text = "R&D Technical Presentation  |  Generated by GP-Chat"
                        for paragraph in shape.text_frame.paragraphs:
                            paragraph.font.name = "Meiryo"
            
            if not title_written:
                tx_main_title = title_slide.shapes.add_textbox(Inches(1.0), Inches(2.3), Inches(11.333), Inches(1.1))
                tf_main_title = tx_main_title.text_frame
                tf_main_title.word_wrap = True
                p_main = tf_main_title.paragraphs[0]
                p_main.alignment = PP_ALIGN.CENTER
                p_main.text = presentation_data.presentation_title
                p_main.font.name = "Meiryo"
                p_main.font.size = Pt(44)
                p_main.font.bold = True
                p_main.font.color.rgb = COLOR_PRIMARY
        else:
            title_slide = prs.slides.add_slide(title_layout)
            bg_title = title_slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
            bg_title.fill.solid()
            bg_title.fill.fore_color.rgb = COLOR_WHITE
            bg_title.line.fill.background()

            accent_line = title_slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(3.666), Inches(3.6), Inches(6.0), Inches(0.02))
            accent_line.fill.solid()
            accent_line.fill.fore_color.rgb = COLOR_PRIMARY
            accent_line.line.fill.background()

            tx_main_title = title_slide.shapes.add_textbox(Inches(1.0), Inches(2.3), Inches(11.333), Inches(1.1))
            tf_main_title = tx_main_title.text_frame
            tf_main_title.word_wrap = True
            p_main = tf_main_title.paragraphs[0]
            p_main.alignment = PP_ALIGN.CENTER
            p_main.text = presentation_data.presentation_title
            p_main.font.name = "Meiryo"
            p_main.font.size = Pt(44)
            p_main.font.bold = True
            p_main.font.color.rgb = COLOR_PRIMARY

            tx_sub_title = title_slide.shapes.add_textbox(Inches(1.0), Inches(3.9), Inches(11.333), Inches(1.2))
            tf_sub_title = tx_sub_title.text_frame
            tf_sub_title.word_wrap = True
            p_sub = tf_sub_title.paragraphs[0]
            p_sub.alignment = PP_ALIGN.CENTER
            p_sub.text = "R&D Technical Presentation  |  Generated by GP-Chat"
            p_sub.font.name = "Meiryo"
            p_sub.font.size = Pt(18)
            p_sub.font.color.rgb = COLOR_TEXT_MUTED

        # 各コンテンツスライドのレンダリング
        for i, slide_data in enumerate(slides):
            # このスライドのレイアウトを動的に特定
            layout_to_use = blank_layout
            if has_template and slide_data.layout_name in layouts_info:
                # テンプレート内のレイアウト名から完全一致で取得
                layout_to_use = prs.slide_layouts[layouts_info[slide_data.layout_name]["layout_index"]]
            
            img_paths_for_slide = slide_images.get(slide_data.slide_number, {})
            
            render_pptx_slide(
                prs=prs,
                slide_data=slide_data,
                font_size_offset=offsets[i],
                current_index=i,
                total_slides=len(slides),
                image_paths=img_paths_for_slide,
                has_template=has_template,
                blank_layout=layout_to_use
            )

        # --- テンプレート適用時の後処理 (見本スライド削除 & 裏表紙スライドの末尾移動) ---
        if has_template:
            slide_id_list = prs.slides._sldIdLst
            
            # 初期状態で「見本スライド」は2枚目(インデックス1)に位置しているため、これを削除
            del slide_id_list[1]
            
            # 初期状態で「裏表紙スライド」は3枚目（2枚目が消えたので現在はインデックス1）に位置している
            # これを一度リストから外し、最後に作成されたAIコンテンツスライドのさらに後ろ（最末尾）に追加する
            back_cover_id = slide_id_list[1]
            slide_id_list.remove(back_cover_id)
            slide_id_list.append(back_cover_id)
            state_manager.add_debug_log("[PPTXAgent] Template cleanup: Removed Content mockup slide and moved BackCover slide to the end.")
            
        prs.save(final_pptx_path)
        state_manager.add_debug_log(f"[PPTXAgent] PowerPoint file successfully saved: {final_pptx_path}")
        
        try:
            for filename in os.listdir(temp_dir):
                os.remove(os.path.join(temp_dir, filename))
            os.rmdir(temp_dir)
        except Exception as e:
            state_manager.add_debug_log(f"[PPTXAgent] Non-critical cleanup warning: {e}", "warning")
            
        return final_pptx_path
