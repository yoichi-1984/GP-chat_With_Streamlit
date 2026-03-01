import json
import time
import streamlit as st
from google.genai import types

# --- Local Module Imports ---
try:
    from gp_chat import state_manager
except ImportError:
    import state_manager

def run_deep_research(client, model_id, gen_config, chat_contents, system_instruction, 
                      text_placeholder, thought_status, thought_placeholder):
    """
    徹底調査モード (More Research) 用のエージェント。
    1. Dynamic Research: 情報の過不足を評価しながら、動的な検索ループ(ReAct)を実行
    2. Synthesis: 収集した全情報と推論ルールを用いて最終回答を生成
    
    Returns:
        tuple: (full_response, usage_metadata, combined_grounding_metadata)
    """
    state_manager.add_debug_log("[Deep Research] Starting dynamic ReAct agent...")
    
    total_usage = {"input": 0, "output": 0, "total": 0}
    combined_grounding = {"sources": [], "queries": []}
    full_thought_log = "### 🧠 Deep Research Process\n\n"
    
    # ---------------------------------------------------------
    # Phase 1: Dynamic Research Loop (ReAct型深掘り)
    # ---------------------------------------------------------
    full_thought_log += "**[Phase 1: Dynamic Research]**\n情報の過不足を評価しながら、動的に検索と深掘りを繰り返します...\n"
    thought_placeholder.markdown(full_thought_log)
    
    MAX_ITERATIONS = 3
    iteration = 0
    research_results = []
    executed_queries = set()
    
    # 評価・計画用のJSONスキーマ
    react_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema={
            "type": "OBJECT",
            "properties": {
                "status": {"type": "STRING", "description": "'needs_more_info' or 'sufficient'"},
                "next_queries": {"type": "ARRAY", "items": {"type": "STRING"}},
                "reasoning": {"type": "STRING", "description": "現在の状況と次のアクション(検索)を決定した理由"}
            },
            "required": ["status", "next_queries", "reasoning"]
        },
        temperature=0.2,
    )
    
    # 検索実行用のコンフィグ
    exec_config = types.GenerateContentConfig(
        temperature=0.1,
        tools=[types.Tool(google_search=types.GoogleSearch())]
    )

    while iteration < MAX_ITERATIONS:
        iteration += 1
        thought_status.update(label=f"🔄 調査サイクル {iteration}/{MAX_ITERATIONS} を実行中...", state="running")
        
        # --- 評価・計画 ---
        current_knowledge = "\n\n".join(research_results) if research_results else "（まだ調査結果はありません）"
        
        react_prompt = (
            "あなたは優秀なリサーチャーです。ユーザーの最新の要求に対して、完璧な裏付けのある回答を作成するための情報を集めています。\n"
            "これまでに以下の調査結果が得られています：\n"
            "-----------------\n"
            f"{current_knowledge}\n"
            "-----------------\n"
            "【あなたのタスク】\n"
            "上記の情報を踏まえ、ユーザーの要求に完全に答えるために情報が十分か判定してください。\n"
            "もし情報が不足している、事実の裏付けが弱い、または新たに深掘りすべき疑問点が浮上した場合は、"
            "それを解決するためのGoogle検索クエリを1〜3個提案してください。\n"
            "情報が十分に揃ったと判断した場合は、statusを'sufficient'にし、next_queriesは空にしてください。\n"
        )
        
        # 直近のやり取りを元にメッセージ構築
        react_contents = chat_contents[-3:] if len(chat_contents) > 3 else chat_contents
        react_contents = react_contents + [types.Content(role="user", parts=[types.Part.from_text(text=react_prompt)])]
        
        try:
            react_response = client.models.generate_content(
                model=model_id,
                contents=react_contents,
                config=react_config
            )
            if react_response.usage_metadata:
                total_usage["input"] += (react_response.usage_metadata.prompt_token_count or 0)
                total_usage["output"] += (react_response.usage_metadata.candidates_token_count or 0)
                
            react_data = json.loads(react_response.text)
            status = react_data.get("status", "needs_more_info")
            next_queries = react_data.get("next_queries", [])
            reasoning = react_data.get("reasoning", "")
            
            # AIの判断理由をUIに表示
            full_thought_log += f"\n**[Cycle {iteration}] AIの思考:** {reasoning}\n"
            thought_placeholder.markdown(full_thought_log)
            state_manager.add_debug_log(f"[Deep Research] Cycle {iteration} reasoning: {reasoning}")
            
            # 終了判定
            if status == "sufficient" or not next_queries:
                full_thought_log += "✅ 情報が十分に揃ったと判断しました。調査ループを終了します。\n"
                thought_placeholder.markdown(full_thought_log)
                break
                
            # --- 検索の実行 ---
            # 過去に実行したクエリはスキップし、最大3個までに制限
            queries_to_run = [q for q in next_queries if q not in executed_queries][:3]
            if not queries_to_run:
                full_thought_log += "⚠️ 新しい検索クエリがありません。調査ループを終了します。\n"
                thought_placeholder.markdown(full_thought_log)
                break
                
            for query in queries_to_run:
                executed_queries.add(query)
                full_thought_log += f"* 🔍 検索実行: `{query}`\n"
                thought_placeholder.markdown(full_thought_log)
                
                exec_prompt = f"以下のクエリでGoogle検索を行い、判明した重要な事実、データ、見解を詳細に要約してリストアップしてください。\nクエリ: {query}"
                exec_response = client.models.generate_content(
                    model=model_id,
                    contents=[types.Content(role="user", parts=[types.Part.from_text(text=exec_prompt)])],
                    config=exec_config
                )
                
                if exec_response.usage_metadata:
                    total_usage["input"] += (exec_response.usage_metadata.prompt_token_count or 0)
                    total_usage["output"] += (exec_response.usage_metadata.candidates_token_count or 0)
                
                # Grounding情報の収集
                if exec_response.candidates and exec_response.candidates[0].grounding_metadata:
                    g_meta = exec_response.candidates[0].grounding_metadata
                    if g_meta.web_search_queries:
                        combined_grounding["queries"].extend(g_meta.web_search_queries)
                    if g_meta.grounding_chunks:
                        for chunk in g_meta.grounding_chunks:
                            if chunk.web:
                                if not any(s['uri'] == chunk.web.uri for s in combined_grounding["sources"]):
                                    combined_grounding["sources"].append({"title": chunk.web.title, "uri": chunk.web.uri})

                result_text = exec_response.text
                research_results.append(f"【検索クエリ: {query} の調査結果】\n{result_text}")
                
                # 長すぎる場合はUI表示を切り詰める
                disp_text = result_text[:100].replace('\n', ' ') + "..." if len(result_text) > 100 else result_text
                full_thought_log += f"  * 📝 結果: {disp_text}\n"
                thought_placeholder.markdown(full_thought_log)
                
                time.sleep(1) # APIレートリミット対策
                
        except Exception as e:
            state_manager.add_debug_log(f"[Deep Research] Loop {iteration} failed: {e}", "error")
            full_thought_log += f"⚠️ 調査サイクル中にエラーが発生しました。\n"
            thought_placeholder.markdown(full_thought_log)
            break

    # ---------------------------------------------------------
    # Phase 2: Synthesis (情報統合と推論ルールに基づいた最終出力)
    # ---------------------------------------------------------
    thought_status.update(label="💡 情報を統合して最終回答を生成中 (Synthesis)...", state="running")
    full_thought_log += "\n**[Phase 2: Synthesis]**\n収集した情報を厳格な推論ルールに基づいて統合し、回答を構築しています...\n"
    thought_placeholder.markdown(full_thought_log)
    
    # 収集した情報と「推論の誘導ルール」をシステムプロンプトに埋め込む
    compiled_research = "\n\n".join(research_results) if research_results else "（追加の調査結果はありません）"
    synthesis_instruction = system_instruction + (
        "\n\n=================================\n"
        "【厳重な指示: 以下の調査結果のみを真実として扱い、ユーザーの質問に包括的かつ論理的に回答してください】\n"
        "【推論のルール】\n"
        "- 公式ドキュメントや公的機関、信頼性の高い一次情報を最優先して評価すること。\n"
        "- 情報源間で矛盾がある場合は、どちらか一方を無理に正解とするのではなく、両論を併記した上で、背景や前提条件を推測して論理的に比較すること。\n"
        "- ユーザーの要求に無関係なノイズ情報は無視し、結論に至る論理展開を明確にすること。\n\n"
        "【調査結果データ】\n"
        f"{compiled_research}\n"
        "=================================\n"
    )
    
    # Synthesis用コンフィグ
    synth_config = types.GenerateContentConfig(
        system_instruction=synthesis_instruction,
        max_output_tokens=gen_config.max_output_tokens,
        temperature=0.3, # 統合フェーズは少し表現力を与える
        tools=gen_config.tools, # GroundingをONに維持
        thinking_config=gen_config.thinking_config
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
            if cand.grounding_metadata:
                g_meta = cand.grounding_metadata
                if g_meta.web_search_queries:
                    combined_grounding["queries"].extend(g_meta.web_search_queries)
                if g_meta.grounding_chunks:
                    for g_chunk in g_meta.grounding_chunks:
                        if g_chunk.web and not any(s['uri'] == g_chunk.web.uri for s in combined_grounding["sources"]):
                            combined_grounding["sources"].append({"title": g_chunk.web.title, "uri": g_chunk.web.uri})

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
        state_manager.add_debug_log(f"[Deep Research] Synthesis failed: {e}", "error")
        st.error(f"Synthesis failed: {e}")
        return "", None, None

    # 完了ステータス
    thought_status.update(label="徹底調査完了 (Deep Research Finished)", state="complete", expanded=False)
    state_manager.add_debug_log("[Deep Research] Agent successfully finished.")

    # 返却用にUsageを整形
    final_usage_metadata = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=total_usage["input"],
        candidates_token_count=total_usage["output"],
        total_token_count=total_usage["input"] + total_usage["output"]
    )

    # Queriesの重複排除
    combined_grounding["queries"] = list(set(combined_grounding["queries"]))

    return full_response, final_usage_metadata, combined_grounding