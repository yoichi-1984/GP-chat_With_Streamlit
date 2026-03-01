import json
import time
import streamlit as st
from google.genai import types

# --- Local Module Imports ---
try:
    from gp_chat import state_manager
except ImportError:
    import state_manager

def run_deep_reasoning(client, model_id, gen_config, chat_contents, system_instruction, 
                       text_placeholder, thought_status, thought_placeholder):
    """
    推論特化モード (Deep Reasoning) 用のエージェント。
    提案A (自己批判) と 提案B (多角的仮説の検証) のハイブリッド。
    
    1. Brainstorming: 3つの異なるアプローチを生成
    2. Exploration & Critique: 各アプローチを深掘りし、弱点を自己批判
    3. Integration: 全評価を踏まえた最終結論の生成
    
    Returns:
        tuple: (full_response, usage_metadata, combined_grounding_metadata)
    """
    state_manager.add_debug_log("[Deep Reasoning] Starting hybrid reasoning agent...")
    
    total_usage = {"input": 0, "output": 0, "total": 0}
    combined_grounding = {"sources": [], "queries": []}
    full_thought_log = "### 🧠 Deep Reasoning Process\n\n"
    
    # Reasoningモードのベース設定 (Web検索がONの場合は gen_config.tools に引き継がれている)
    base_config = types.GenerateContentConfig(
        max_output_tokens=gen_config.max_output_tokens,
        temperature=gen_config.temperature,
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH, include_thoughts=True),
        tools=gen_config.tools # Web検索ツールを適用
    )

    def extract_grounding_info(candidate):
        """レスポンスからGrounding情報を抽出してcombined_groundingに追加するヘルパー"""
        if candidate and candidate.grounding_metadata:
            g_meta = candidate.grounding_metadata
            if g_meta.web_search_queries:
                combined_grounding["queries"].extend(g_meta.web_search_queries)
            if g_meta.grounding_chunks:
                for chunk in g_meta.grounding_chunks:
                    if chunk.web:
                        if not any(s['uri'] == chunk.web.uri for s in combined_grounding["sources"]):
                            combined_grounding["sources"].append({"title": chunk.web.title, "uri": chunk.web.uri})

    # ---------------------------------------------------------
    # Phase 1: Brainstorming (多角的なアプローチの立案)
    # ---------------------------------------------------------
    thought_status.update(label="🤔 多角的なアプローチを考案中 (Brainstorming)...", state="running")
    full_thought_log += "**[Phase 1: Brainstorming]**\n問題解決のための異なる3つのアプローチ（解法や視点）を立案しています...\n"
    thought_placeholder.markdown(full_thought_log)
    
    # 汎用化: コンサルタント縛りを外し、純粋な推論エンジンとして多角的なアプローチを要求
    brainstorm_prompt = (
        "あなたは世界最高峰の論理的推論能力を持つAIシステムです。\n"
        "ユーザーの直近の要求を解決するために、異なる3つのアプローチ（解法、設計、または視点）を立案してください。\n"
        "例えば、「処理効率・簡潔さを重視するアプローチ」「網羅性・堅牢性を重視するアプローチ」「前提条件そのものを疑うアプローチ」など、多角的な視点からアプローチを生成してください。"
    )
    
    brainstorm_contents = chat_contents[-3:] if len(chat_contents) > 3 else chat_contents
    brainstorm_contents = brainstorm_contents + [types.Content(role="user", parts=[types.Part.from_text(text=brainstorm_prompt)])]
    
    brainstorm_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema={
            "type": "OBJECT",
            "properties": {
                "approaches": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "name": {"type": "STRING", "description": "アプローチの短い名称"},
                            "description": {"type": "STRING", "description": "アプローチの概要と狙い"}
                        },
                        "required": ["name", "description"]
                    }
                }
            },
            "required": ["approaches"]
        },
        temperature=0.4, # アイデア出しのため少しだけ高めに
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH, include_thoughts=True),
        tools=gen_config.tools # Web検索ツールを適用
    )
    
    approaches = []
    try:
        bs_response = client.models.generate_content(
            model=model_id,
            contents=brainstorm_contents,
            config=brainstorm_config
        )
        
        if bs_response.usage_metadata:
            total_usage["input"] += (bs_response.usage_metadata.prompt_token_count or 0)
            total_usage["output"] += (bs_response.usage_metadata.candidates_token_count or 0)
            
        if bs_response.candidates:
            extract_grounding_info(bs_response.candidates[0])
            
        bs_data = json.loads(bs_response.text)
        approaches = bs_data.get("approaches", [])[:3] # 最大3つ
        
        for i, app in enumerate(approaches):
            full_thought_log += f"* **アプローチ{i+1} [{app['name']}]:** {app['description']}\n"
            
        thought_placeholder.markdown(full_thought_log)
        state_manager.add_debug_log(f"[Deep Reasoning] Brainstormed approaches: {[a['name'] for a in approaches]}")
        
    except Exception as e:
        state_manager.add_debug_log(f"[Deep Reasoning] Brainstorming failed: {e}", "error")
        approaches = [{"name": "論理的アプローチ", "description": "与えられた制約の中で論理的に問題を解決する標準的なアプローチ"}]
        full_thought_log += f"⚠️ アプローチの生成に失敗しました。標準的な推論で進行します。\n\n"

    # ---------------------------------------------------------
    # Phase 2: Exploration & Critique (深掘りと自己批判)
    # ---------------------------------------------------------
    full_thought_log += "\n**[Phase 2: Exploration & Critique]**\n各アプローチを深く検証し、潜在的な問題点を自己批判（Critique）します...\n"
    thought_placeholder.markdown(full_thought_log)
    
    critique_results = []
    
    critique_config = types.GenerateContentConfig(
        temperature=0.2, # 評価は厳密に
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH, include_thoughts=True),
        tools=gen_config.tools # Web検索ツールを適用
    )
    
    for i, app in enumerate(approaches):
        thought_status.update(label=f"⚖️ アプローチの検証・批判 {i+1}/{len(approaches)}...", state="running")
        full_thought_log += f"\n* 🔍 **検証中:** {app['name']}\n"
        thought_placeholder.markdown(full_thought_log)
        
        critique_prompt = (
            f"ユーザーの要求に対する解決策として、以下のアプローチを検討しています。\n"
            f"【アプローチ名】: {app['name']}\n"
            f"【概要】: {app['description']}\n\n"
            "このアプローチを深く推論して具体化し、その後に**あえて厳しく自己批判（潜在的なリスク、論理の飛躍、エッジケースでの破綻など）**を行ってください。\n"
            "「具体化された推論」と「自己批判・弱点」の2つを明確に分けて記述してください。"
        )
        
        try:
            cr_response = client.models.generate_content(
                model=model_id,
                contents=chat_contents + [types.Content(role="user", parts=[types.Part.from_text(text=critique_prompt)])],
                config=critique_config
            )
            
            if cr_response.usage_metadata:
                total_usage["input"] += (cr_response.usage_metadata.prompt_token_count or 0)
                total_usage["output"] += (cr_response.usage_metadata.candidates_token_count or 0)

            if cr_response.candidates:
                extract_grounding_info(cr_response.candidates[0])

            result_text = cr_response.text
            critique_results.append(f"【アプローチ: {app['name']} の検証と自己批判】\n{result_text}")
            
            # 長すぎる場合はUI表示を切り詰める
            disp_text = result_text[:120].replace('\n', ' ') + "..." if len(result_text) > 120 else result_text
            full_thought_log += f"  * 📝 評価: {disp_text}\n"
            thought_placeholder.markdown(full_thought_log)
            
            time.sleep(1) # APIレートリミット対策
            
        except Exception as e:
            state_manager.add_debug_log(f"[Deep Reasoning] Critique failed for '{app['name']}': {e}", "error")
            full_thought_log += f"  * ⚠️ エラーが発生したためスキップしました。\n"
            thought_placeholder.markdown(full_thought_log)

    # ---------------------------------------------------------
    # Phase 3: Integration & Refinement (統合と最終出力)
    # ---------------------------------------------------------
    thought_status.update(label="💡 全推論を統合して最終回答を生成中 (Integration)...", state="running")
    full_thought_log += "\n**[Phase 3: Integration]**\n全てのアプローチと自己批判を踏まえ、最も洗練された最終結論を構築しています...\n"
    thought_placeholder.markdown(full_thought_log)
    
    # 汎用化: 出力形式の縛りをなくし、タスクに最適化させる指示に変更
    compiled_reasoning = "\n\n".join(critique_results)
    synthesis_instruction = system_instruction + (
        "\n\n=================================\n"
        "【厳重な指示: 以下の「多角的なアプローチの検証と自己批判の記録」をベースにして、ユーザーの質問に対する最終的かつ最も洗練された回答を生成してください。】\n"
        "【推論のルール】\n"
        "- 全てのアプローチの良い部分を統合するか、あるいは最も批判に耐えうるアプローチを選択してください。\n"
        "- 最終的な回答のフォーマットは、ユーザーの要求（コード生成、レポート、解説、手順書など）に最も適した形式で出力してください。\n"
        "- 最終結論に至った論理的根拠を簡潔に含めつつ、ユーザーがそのまま利用できる実用的な成果物を提供してください。\n\n"
        "【検証と自己批判の記録】\n"
        f"{compiled_reasoning}\n"
        "=================================\n"
    )
    
    # Synthesis用コンフィグ (ここで改めてシステム指示をセット)
    synth_config = types.GenerateContentConfig(
        system_instruction=synthesis_instruction,
        max_output_tokens=gen_config.max_output_tokens,
        temperature=0.3,
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH, include_thoughts=True),
        tools=gen_config.tools # Web検索ツールを適用
    )
    
    full_response = ""
    synth_usage = None
    
    try:
        # ストリーミング生成
        stream = client.models.generate_content_stream(
            model=model_id,
            contents=chat_contents,
            config=synth_config
        )
        
        for chunk in stream:
            if chunk.usage_metadata:
                synth_usage = chunk.usage_metadata

            if not chunk.candidates: continue
            cand = chunk.candidates[0]
            
            # Synthesis時のGrounding情報も追加
            extract_grounding_info(cand)

            if cand.content and cand.content.parts:
                for part in cand.content.parts:
                    # Thought部分はUIに流す
                    is_thought = False
                    thought_text = ""
                    if hasattr(part, 'thought') and isinstance(part.thought, str) and part.thought:
                        is_thought = True
                        thought_text = part.thought
                    elif hasattr(part, 'thought') and part.thought is True:
                        is_thought = True
                        thought_text = part.text

                    if is_thought and thought_text:
                        full_thought_log += thought_text
                        thought_placeholder.markdown(full_thought_log)
                    elif part.text:
                        full_response += part.text
                        text_placeholder.markdown(full_response + "▌")
                        
        text_placeholder.markdown(full_response)
        
        if synth_usage:
            total_usage["input"] += (synth_usage.prompt_token_count or 0)
            total_usage["output"] += (synth_usage.candidates_token_count or 0)
        
    except Exception as e:
        state_manager.add_debug_log(f"[Deep Reasoning] Synthesis failed: {e}", "error")
        st.error(f"Synthesis failed: {e}")
        return "", None, None

    # 完了ステータス
    thought_status.update(label="推論特化処理完了 (Deep Reasoning Finished)", state="complete", expanded=False)
    state_manager.add_debug_log("[Deep Reasoning] Agent successfully finished.")

    # 返却用にUsageを整形
    final_usage_metadata = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=total_usage["input"],
        candidates_token_count=total_usage["output"],
        total_token_count=total_usage["input"] + total_usage["output"]
    )

    # Queriesの重複排除
    combined_grounding["queries"] = list(set(combined_grounding["queries"]))

    return full_response, final_usage_metadata, combined_grounding