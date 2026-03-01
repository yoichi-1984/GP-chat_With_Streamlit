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
    1. Planning: 検索クエリの立案
    2. Execution: 各クエリでの並列/直列検索の実行
    3. Synthesis: 情報の統合と最終回答のストリーミング生成
    
    Returns:
        tuple: (full_response, usage_metadata, combined_grounding_metadata)
    """
    state_manager.add_debug_log("[Deep Research] Starting agent...")
    
    total_usage = {"input": 0, "output": 0, "total": 0}
    combined_grounding = {"sources": [], "queries": []}
    full_thought_log = "### 🧠 Deep Research Process\n\n"
    
    # ---------------------------------------------------------
    # Phase 1: Planning (クエリの立案)
    # ---------------------------------------------------------
    thought_status.update(label="📋 調査計画を立案中 (Planning)...", state="running")
    full_thought_log += "**[Phase 1: Planning]**\n質問を分析し、必要な検索クエリを生成しています...\n"
    thought_placeholder.markdown(full_thought_log)
    
    plan_prompt = (
        "あなたは優秀なリサーチャーです。ユーザーの最新の要求に対して、完璧な裏付けのある回答を作成するために、"
        "Google検索で調査すべき具体的なクエリを3〜5個作成してください。\n"
        "多角的な視点（最新動向、技術仕様、事例など）を含めるようにしてください。\n"
    )
    
    # Planning用のメッセージ構築（直近のやり取りのみを考慮してトークン節約）
    plan_contents = chat_contents[-3:] if len(chat_contents) > 3 else chat_contents
    plan_contents = plan_contents + [types.Content(role="user", parts=[types.Part.from_text(text=plan_prompt)])]
    
    # JSONスキーマの定義 (確実にリストで受け取るため)
    response_schema = {
        "type": "OBJECT",
        "properties": {
            "queries": {
                "type": "ARRAY",
                "items": {"type": "STRING"}
            }
        },
        "required": ["queries"]
    }
    
    plan_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=response_schema,
        temperature=0.2, # クエリ生成は決定論的に
    )
    
    search_queries = []
    try:
        plan_response = client.models.generate_content(
            model=model_id,
            contents=plan_contents,
            config=plan_config
        )
        
        # 修正: or 0 を付与して None によるクラッシュを防止
        if plan_response.usage_metadata:
            total_usage["input"] += (plan_response.usage_metadata.prompt_token_count or 0)
            total_usage["output"] += (plan_response.usage_metadata.candidates_token_count or 0)
            
        plan_data = json.loads(plan_response.text)
        search_queries = plan_data.get("queries", [])
        
        full_thought_log += f"立案されたクエリ: {', '.join(search_queries)}\n\n"
        thought_placeholder.markdown(full_thought_log)
        state_manager.add_debug_log(f"[Deep Research] Planned queries: {search_queries}")
        
    except Exception as e:
        state_manager.add_debug_log(f"[Deep Research] Planning failed: {e}", "error")
        search_queries = ["現在の最新情報"] # フェイルセーフ
        full_thought_log += f"⚠️ 計画立案に失敗しました。デフォルトのクエリで進行します。\n\n"


    # ---------------------------------------------------------
    # Phase 2: Execution (リサーチの実行)
    # ---------------------------------------------------------
    full_thought_log += "**[Phase 2: Execution]**\n各クエリについて詳細な調査を実行します...\n"
    thought_placeholder.markdown(full_thought_log)
    
    research_results = []
    
    # 検索用の設定 (Google Searchツールを強制有効化)
    exec_config = types.GenerateContentConfig(
        temperature=0.1,
        tools=[types.Tool(google_search=types.GoogleSearch())]
    )
    
    for i, query in enumerate(search_queries):
        thought_status.update(label=f"🔍 調査中: {query} ({i+1}/{len(search_queries)})...", state="running")
        full_thought_log += f"* 🔍 検索実行: `{query}`\n"
        thought_placeholder.markdown(full_thought_log)
        
        exec_prompt = f"以下のクエリでGoogle検索を行い、判明した重要な事実、データ、見解を詳細に要約してリストアップしてください。\nクエリ: {query}"
        
        try:
            exec_response = client.models.generate_content(
                model=model_id,
                contents=[types.Content(role="user", parts=[types.Part.from_text(text=exec_prompt)])],
                config=exec_config
            )
            
            # 修正: or 0 を付与
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
                            # 重複排除しながら追加
                            if not any(s['uri'] == chunk.web.uri for s in combined_grounding["sources"]):
                                combined_grounding["sources"].append({"title": chunk.web.title, "uri": chunk.web.uri})

            result_text = exec_response.text
            research_results.append(f"【検索クエリ: {query} の調査結果】\n{result_text}")
            
            # 長すぎる場合はUI表示を切り詰める
            disp_text = result_text[:100].replace('\n', ' ') + "..." if len(result_text) > 100 else result_text
            full_thought_log += f"  * 📝 結果: {disp_text}\n"
            thought_placeholder.markdown(full_thought_log)
            
            time.sleep(1) # APIレートリミット対策の短いウェイト
            
        except Exception as e:
            state_manager.add_debug_log(f"[Deep Research] Execution failed for query '{query}': {e}", "error")
            full_thought_log += f"  * ⚠️ エラーが発生したためスキップしました。\n"
            thought_placeholder.markdown(full_thought_log)

    # ---------------------------------------------------------
    # Phase 3: Synthesis (情報統合と最終出力)
    # ---------------------------------------------------------
    thought_status.update(label="💡 情報を統合して最終回答を生成中 (Synthesis)...", state="running")
    full_thought_log += "\n**[Phase 3: Synthesis]**\n収集した情報を統合し、最終回答を構築しています...\n"
    thought_placeholder.markdown(full_thought_log)
    
    # 収集した情報をシステムプロンプト（指示）に埋め込む
    compiled_research = "\n\n".join(research_results)
    synthesis_instruction = system_instruction + (
        "\n\n=================================\n"
        "【厳重な指示: 以下の調査結果のみを真実として扱い、ユーザーの質問に包括的かつ論理的に回答してください】\n"
        f"{compiled_research}\n"
        "=================================\n"
    )
    
    # Synthesis用コンフィグ (元のgen_configをベースにするが、システム指示を差し替える)
    synth_config = types.GenerateContentConfig(
        system_instruction=synthesis_instruction,
        max_output_tokens=gen_config.max_output_tokens,
        temperature=0.3, # 統合フェーズは少し表現力を与える
        tools=gen_config.tools, # GroundingをONにしておく
        thinking_config=gen_config.thinking_config
    )
    
    full_response = ""
    synth_usage = None # ストリーミング用のメタデータ保持変数
    
    try:
        # ストリーミング生成
        stream = client.models.generate_content_stream(
            model=model_id,
            contents=chat_contents,
            config=synth_config
        )
        
        for chunk in stream:
            # 修正: ストリーミング中は毎回加算せず、最後のメタデータを保持するだけ
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
        
        # 修正: ループ終了後に1回だけ、安全に加算を行う
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