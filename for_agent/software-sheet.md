# GP-Chat 完全システム設計仕様書 (software-sheet.md)

本ドキュメントは、GCP (Vertex AI) および Azure OpenAI の大規模言語モデル（LLM）APIを統合・最適化した、StreamlitベースのAI駆動型統合ワークステーション「GP-Chat」の**完全システム設計仕様書**です。
本仕様書のみを参照することで、システムの全体アーキテクチャ、全30以上のモジュールの責務と公開インターフェース、関数間呼び出し関係（Call Graph）、データモデル/スキーマ定義、UI状態遷移と連動排他制御マトリクス、5大特化型自律エージェントの内部アルゴリズム（PowerPointネイティブ生成の4層パイプライン、幾何学バリデーション、自己修復ループ含む）、二重化ルーティングと障害耐性、コンテキスト構築パイプライン、全セッション状態変数、および例外処理方針を1行単位で完全に理解し、本システムをゼロから再実装・保守・拡張・デバッグできる詳細な設計情報を記述しています。

---

## 📑 目次 (Table of Contents)

1. [第1章: システム憲章 & 設計思想 (System Charter & Architecture Principles)](#第1章-システム憲章--設計思想-system-charter--architecture-principles)
2. [第2章: システムアーキテクチャ & ファイル・モジュール完全一覧 (System Architecture & Module Breakdown)](#第2章-システムアーキテクチャ--ファイルモジュール完全一覧-system-architecture--module-breakdown)
3. [第3章: データモデル & スキーマ完全リファレンス (Data Models & Schemas)](#第3章-データモデル--スキーマ完全リファレンス-data-models--schemas)
4. [第4章: セッション状態 (Session State) 変数 & クリーンアップ完全仕様 (Session State Management)](#第4章-セッション状態-session-state-変数--クリーンアップ完全仕様-session-state-management)
5. [第5章: UI / UX 状態遷移 & 画面制御ロジック (UI State Machine & Interaction Flows)](#第5章-ui--ux-状態遷移--画面制御ロジック-ui-state-machine--interaction-flows)
6. [第6章: コンテキスト構築 & マルチモーダルパースパイプライン (Context Materialization & Multimodal Parsing)](#第6章-コンテキスト構築--マルチモーダルパースパイプライン-context-materialization--multimodal-parsing)
7. [第7章: LLMルーティング・二重化 & 障害耐性仕様 (LLM Routing & Fault Tolerance)](#第7章-llmルーティング二重化--障害耐性仕様-llm-routing--fault-tolerance)
8. [第8章: 5大特化型エージェント完全内部アルゴリズム (Specialized Autonomous Agents)](#第8章-5大特化型エージェント完全内部アルゴリズム-specialized-autonomous-agents)
9. [第9章: Azure OpenAI 専用エージェント群仕様 (Azure Agent Implementations)](#第9章-azure-openai-専用エージェント群仕様-azure-agent-implementations)
10. [第10章: 関数間呼び出し関係 & シーケンス詳細 (Function Call Graphs & Sequence Diagrams)](#第10章-関数間呼び出し関係--シーケンス詳細-function-call-graphs--sequence-diagrams)
11. [第11章: 例外処理方針 & エラーハンドリングマトリクス (Exception Handling Matrix)](#第11章-例外処理方針--エラーハンドリングマトリクス-exception-handling-matrix)
12. [第12章: 設定ファイル & プロンプト定義完全仕様 (Configuration & Prompts)](#第12章-設定ファイル--プロンプト定義完全仕様-configuration--prompts)
13. [第13章: 改訂履歴 (Revision History)](#第13章-改訂履歴-revision-history)

---

## 第1章: システム憲章 & 設計思想 (System Charter & Architecture Principles)

### 1.1 システムの目的と開発思想
GP-Chat は、単一のAIモデルや単純なチャットUIの制約を克服し、実務における高度な意思決定、データ分析、コード開発、Webリサーチ、および高品質なプレゼンテーション資料作成を完全自律型で支援する「AI駆動型統合ワークステーション」です。

### 1.2 コア設計原則 (Core Architecture Principles)
1. **ハイブリッド＆ゼロダウンタイム (Hybrid & Zero Downtime)**:
   - GCP Vertex AI (最新フラッグシップ `gemini-3.8-flash` を主軸) を主系とし、API レートリミット（429）や障害発生時には即座に Azure OpenAI へ自動フォールバックする。
   - 特定のモデル群（`gpt-5.3-codex`, `gpt-5.6`, `gpt-6`）は最初から Azure への直接接続（GCPバイパス）を行い、最適なモデル適材適所を実現する。
2. **決定論的 UI 制御 & 厳格な排他ロック (Deterministic UI & Mutual Exclusion)**:
   - Streamlit の再実行（Rerun）モデルにおいて、競合するモード（例: 徹底調査とDeep Reasoning、PDFレポートとPPTXレポート）の同時選択をサイドバーの真理値マトリクスで完全に排他・連動ロックする。
3. **自己修復ループの標準化 (Self-Healing by Default)**:
   - Pythonコード実行エラー時の自動修正（Auto-Fix: 最大2回）および PowerPoint スライドの幾何学テキスト溢れ検知時の自動要約リライト（最大3回）を標準装備し、AI生成物の破綻を自律的に解消する。
4. **ステートレスなデータ変換とポインタ保護 (Stateless Parsing & Safe Pointer Management)**:
   - ファイルアップロード処理において、`temp_workspace/<Session-UUID>/` への隔離保存とファイルポインタ位置の保護（`seek(0)` / `tell()`）を徹底し、再実行時のデータ破損を防止する。
5. **完全な履歴可逆性 (History Reversibility & Branching)**:
   - 会話の任意の時点から分岐（Fork）して新しいチャットスレッドを開始できるツリー型対話を可能にし、試行錯誤の巻き戻しを完全に保証する。
6. **HTTP/2 多重化 & 適応型ハイブリッド推論 (HTTP/2 Multiplexing & Adaptive Reasoning)**:
   - Azure OpenAI の最新推論モデル（`gpt-5.6`, `gpt-6`）を高推論モード（`high`/`deep`）で実行する際、OpenAI SDK v3.x の新通信基盤 `httpx2`（HTTP/2 多重化）によりサブタスクを並行実行し、プロキシ/APIM の無通信タイムアウト（504 Gateway Timeout）を完全に回避しつつ、思考プロセスを逐次ストリーミング描画する。

---

## 第2章: システムアーキテクチャ & ファイル・モジュール完全一覧 (System Architecture & Module Breakdown)

### 2.1 リポジトリ全体構造ツリー

```text
gp-chat/
├── pyproject.toml              # パッケージビルド定義、依存パッケージメタデータ
├── requirements.txt            # ローカル環境用依存定義
├── mail.txt                    # ユーザーメールアドレス一時保存用
├── Plan.md                     # タスク計画・開発履歴ドキュメント
├── AICHANGELOG.md              # AIによる変更履歴（Before/After/理由/影響範囲）
├── CHANGELOG.md                # ユーザー向けリリースノート
├── LICENSE                     # Apache 2.0 ライセンス
├── START.bat                   # ワンクリック起動バッチ (Windows)
├── install.bat                 # 仮想環境セットアップ・依存更新バッチ
├── sample_of.env               # 環境変数設定サンプル
├── for_agent/
│   └── software-sheet.md       # 本システム設計仕様書
├── dev/
│   └── fault_injection.local.toml # 疑似エラー注入・フォールバック検証用設定
├── env/
│   └── *.env                   # 環境変数定義ファイル群（UI上で動的切替可能）
├── prompts/
│   └── prompts.yaml            # UI編集・永続化用システムプロンプト設定（カレント優先）
├── slide_data/
│   └── <チャットタイトル>/      # 生成されたHTML/PDF/PPTXスライドの格納ディレクトリ
├── chat_log/
│   └── *.json                  # 会話履歴の自動保存・分岐データ格納ディレクトリ
├── temp_workspace/
│   └── <Session-UUID>/         # セッション固有のデータファイル・画像一時保存領域
└── src/
    └── gp_chat/
        ├── __init__.py
        ├── main_runner.py      # CLIエントリーポイント (`gp-chat`)
        ├── main.py             # メインロジック（画面制御、セッション連携、ストリーミング）
        ├── sidebar.py          # サイドバーUI（モデル選択、モード切替、Canvas、履歴管理）
        ├── config.py           # 定数・UIテキスト・選択可能モデル定義
        ├── config.yaml         # Canvas許可拡張子等の静的設定
        ├── prompts.yaml        # デフォルトシステムプロンプト定義
        ├── utils.py            # ファイルパース、プロンプト読込、Geminiコンテキスト構築
        ├── state_manager.py    # 会話履歴の自動保存・復元、クリーンアップ、デバッグ収集
        ├── data_manager.py     # セッション別一時ファイル管理（ポインタ位置保護機能付き）
        ├── llm_router.py       # Vertex AI クライアント初期化、Standard/Priority切替、リトライ
        ├── execution_engine.py # ローカルPython実行、標準出力回収、matplotlibグラフキャプチャ
        ├── code_agent.py       # コード実行監視 & 自己修復ループ制御
        ├── reasoning_agent.py  # Deep Reasoning エージェント（立案・自己批判・統合）
        ├── research_agent.py   # ReAct 型自律反復検索エージェント
        ├── report_agent.py     # HTML/PDF レポート生成エージェント
        ├── pptx_agent.py       # PowerPoint ネイティブ生成 & 幾何学バリデーションエージェント
        ├── format.pptx         # PowerPoint スライド生成用デザインテンプレート
        ├── azure_runtime.py    # Azure OpenAI クライアント初期化 & ランタイム管理
        ├── azure_context_builder.py # Azure API 向けコンテキスト変換
        ├── azure_supervisor_helpers.py # GCPエラー検知 & Azure切替判定
        ├── azure_fault_injection.py # フォールバック検証用エラー注入
        ├── azure_common_types.py # Azure共通データ型定義
        ├── azure_history_utils.py # Azure用履歴変換ユーティリティ
        ├── azure_normal_chat.py # Azure用通常チャットハンドラ
        ├── azure_responses_router.py # Azure用レスポンスルーティング (httpx2 HTTP/2 対応)
        ├── azure_deep_orchestrator.py # GPT-5.6/6 専用 HTTPX2並行ハイブリッドオーケストレーター
        ├── azure_code_agent.py # Azure用コード実行・修復エージェント
        ├── azure_reasoning_agent.py # Azure用Deep Reasoningエージェント
        ├── azure_research_agent.py # Azure用徹底調査エージェント
        ├── azure_report_agent.py # Azure用レポート生成エージェント
        └── cloud_logging_utils.py # GCP Cloud Logging 送信ユーティリティ
```

### 2.2 全モジュール詳細仕様（関数シグネチャ・入出力・責務対照表）

#### ① `src/gp_chat/main_runner.py`
- **責務**: CLI コマンド `gp-chat` のエントリポイント。
- **主要関数**:
  - `run() -> None`: `sys.argv` を `["streamlit", "run", str(main_path)]` に再構築し、`streamlit.web.cli.main()` を呼び出してアプリを起動する。

#### ② `src/gp_chat/main.py`
- **責務**: アプリケーションのメインライフサイクル管理、UIレイアウト描画、チャット入力受付、ストリーミング応答制御、モデル別ルーティング分岐、Azure Fallback スーパーバイズ、思考ログ折りたたみ描画。
- **主要関数**:
  - `_resolve_mode_name(*, is_special_mode: bool, is_more_research: bool, is_deep_reasoning: bool, is_report_mode: bool) -> str`: 現在のUI状態から実行すべきモード識別名（`"report"`, `"research"`, `"reasoning"`, `"special"`, `"normal"`）を判定して返す。
  - `_run_azure_mode(...) -> AzureModeResult`: Azure OpenAI を使用して各種モード（Normal, Reasoning, Research, Report, Code）を実行する統合ディスパッチャ。
  - `main() -> None`: 初期セッション構築、メールアドレス入力ガード、システムプロンプト設定画面、サイドバー描画、履歴メッセージ描画（`thought_log` のアコーディオン表示含む）、ユーザー入力処理、AI応答ストリーミング、Cloud Logging 送信、自動保存までを一括制御。

#### ③ `src/gp_chat/sidebar.py`
- **責務**: サイドバーUIコンポーネントの描画と設定変更ハンドリング、排他制御マトリクスの適用、Canvasエディタ描画、履歴JSONのロード/リセット。
- **主要関数**:
  - `render_sidebar(data_manager_instance) -> dict`: サイドバー全体を描画し、選択された設定値の辞書を返す。
  - `_render_environment_selector() -> None`: `env/` 配下の `.env` ファイル一覧を取得し、セレクトボックスを描画。
  - `_render_model_selector() -> None`: 利用可能なモデル一覧（Gemini 3.8 Flash, GPT-6 等を含む9モデル）を描画し、選択値をセッションに同期。
  - `_render_thinking_level_selector(is_locked: bool) -> None`: `high` / `medium` / `low` / `deep` の推論レベル選択セレクトボックスを描画。
  - `_render_canvas_section(data_manager_instance) -> None`: 最大40スロットの Ace Editor、トグルボタン、Pylint検証ボタン、レビューボタンを描画。
  - `_render_history_section() -> None`: 過去の `chat_log/*.json` 一覧からの選択ロード、JSONファイルアップロード、および会話リセットボタンを描画。

#### ④ `src/gp_chat/config.py`
- **責務**: アプリケーション全体の定数定義、デフォルトセッションステート、UI文言定義、オーケストレーター設定。
- **主要定数・クラス**:
  - `MAX_CANVASES = 40`: 最大Canvasスロット数。
  - `EXECUTION_TIMEOUT = 30`: Pythonコード実行タイムアウト（秒）。
  - `LLM_RETRYABLE_STATUS_CODES = (408, 429, 500, 502, 503, 504)`: リトライ対象ステータスコード。
  - `PRIORITY_APP_RETRY_COUNT = 3`, `PRIORITY_APP_RETRY_WAIT_SECONDS = (2.0, 4.0, 8.0)`: リトライ設定。
  - `AVAILABLE_MODELS`: 選択可能な全9モデルのリスト（`"gemini-3.8-flash"`, `"gemini-3.7-flash"`, `"gemini-3.6-flash"`, `"gemini-3.5-flash"`, `"gemini-3.1-pro-preview"`, `"gemini-3.5-flash-lite"`, `"gpt-5.3-codex"`, `"gpt-5.6"`, `"gpt-6"`）。
  - `AZURE_DIRECT_MODELS`: Azure OpenAI へ直接ルーティング（GCPバイパス）するモデルタプル（`("gpt-5.3-codex", "gpt-5.6", "gpt-6")`）。
  - `SESSION_STATE_DEFAULTS`: 初期 `st.session_state` 辞書（`current_model_id` のデフォルトは `"gemini-3.8-flash"`, `reasoning_effort` は `"high"`）。
  - `AZURE_DEEP_MAX_CONCURRENCY`: GPT-5.6 / GPT-6 並行サブタスクの最大同時実行数（環境変数 `AZURE_DEEP_MAX_CONCURRENCY`、デフォルト 3）。
  - `AZURE_DEEP_PLANNER_PROMPT`: タスク分解・実行計画立案用システムプロンプト。
  - `AZURE_DEEP_PLANNER_SCHEMA`: タスク分解出力用 JSON スキーマ（`needs_parallel_subtasks`, `plan_summary`, `subtasks`）。
  - `AZURE_DEEP_SUBTASK_PROMPT`: 並行サブタスク実行用システムプロンプト。
  - `class UITexts`: UI上に表示する全静的テキストを管理するクラス。

#### ⑤ `src/gp_chat/utils.py`
- **責務**: ファイルのマルチモーダルパース、プロンプトYAMLのロード、Gemini API用の `types.Content` および `Part` リストの構築、OSクリップボードコピー連携、LaTeX数式デリミタ正規化。
- **主要関数**:
  - `copy_to_clipboard(text: str) -> bool`: Windows クリップボード (`win32clipboard`, `win32con.CF_UNICODETEXT`) を介して指定文字列を安全にコピー。
  - `load_prompts() -> dict`: `prompts/prompts.yaml`（不在時はパッケージ内デフォルト）をロードして辞書化。
  - `save_prompts(prompts: dict) -> None`: `prompts/prompts.yaml` にプロンプト設定を永続化。
  - `format_latex_delimiters(text: str) -> str`: コードブロックやインラインコードを安全に保護した上で、`\(` / `\)` を `$`、`\[` / `\]` や行中 `$$` を独立行 `$$` に正規化し、Streamlit (KaTeX) での正常表示を保証。
  - `parse_file(uploaded_file) -> tuple[str, Any]`: アップロードファイル（画像, PDF, Word, Excel, PPT, テキスト）をパースし、`(mime_type, data)` を返す。
  - `_extract_docx(file_bytes: bytes) -> str`: `python-docx` で全段落テキストを抽出。
  - `_extract_excel(file_bytes: bytes, filename: str) -> str`: `python-calamine`（不在時 `openpyxl`）で全シートを読み込み、Markdown テーブル形式の文字列に変換。
  - `_convert_ppt_to_images_win32(file_bytes: bytes, filename: str) -> list[tuple[bytes, str]]`: Windows COM (`pywin32`) を使用して PowerPoint を起動し、全スライドを PNG 画像バイナリのリストとして抽出（キャッシュ機構付き）。
  - `build_materialized_chat_context(...) -> list[types.Content]`: 会話履歴、Canvasコードスニペット、添付ファイル Part をマージして Gemini 形式の完全なコンテキストを構築。

#### ⑥ `src/gp_chat/state_manager.py`
- **責務**: 会話履歴の永続化、手動ロード、セッション分岐、中断リカバリー、セッションクリーンアップ。
- **主要関数**:
  - `save_chat_history(messages, current_filename, total_usage, ...) -> str`: 会話履歴を `chat_log/yymmdd_タイトル.json` に保存。
  - `load_chat_history(filepath) -> dict`: JSONファイルを読み込み、セッションステートに展開可能な辞書を返す。
  - `fork_chat_history(messages, current_filename, target_index) -> tuple[str, list]`: 特定のメッセージ時点までの履歴を切り出し、連番ファイル名（`-02.json` 等）を採番して保存。
  - `check_interrupted_draft(messages, is_generating) -> str | None`: 未完了のユーザー入力を検知してドラフトテキストとして復元。
  - `cleanup_session_on_load(loaded_data) -> None`: 履歴ロード時の一時ウィジェットステート消去、添付キュー初期化、Canvas送信フラグの自動再構築。

#### ⑦ `src/gp_chat/data_manager.py`
- **責務**: セッションごとの一時作業ディレクトリ（`temp_workspace/<Session-UUID>/`）の作成・管理、アップロードファイルの保存とファイルポインタ保護。
- **主要関数・クラス**:
  - `class DataManager`: セッション管理クラス。
  - `save_uploaded_file(uploaded_file) -> str`: アップロードファイルを安全に一時ディレクトリに書き出し、ポインタ位置を元の位置にリストア（`seek(0)` / `tell()` 保護）。
  - `cleanup_temp_workspace() -> None`: セッション固有の一時ファイルを安全に一括削除。

#### ⑧ `src/gp_chat/llm_router.py`
- **責務**: Google GenAI SDK (`genai.Client`) の初期化、Standard / Priority クライアントの二重化制御、指数バックオフ＋Jitterリトライの実装。
- **主要関数**:
  - `get_gemini_client(route_type: str = "standard") -> genai.Client`: Standard（通常）または Priority（高負荷対策ヘッダー付き）のクライアントを取得。
  - `generate_content_with_retry(client, model, contents, config, stream=False) -> Any`: 429等のリトライ対象エラー検知時に Priority クライアントへ切り替え、指数バックオフ（2.0s, 4.0s, 8.0s + 0~1s Jitter）で最大3回リトライを実行するラッパー。

#### ⑨ `src/gp_chat/execution_engine.py`
- **責務**: ローカル環境スコープでの Python コードの安全な実行、標準出力・エラー出力のキャプチャ、matplotlib グラフ画像の回収。
- **主要関数**:
  - `execute_code(code_str: str, timeout: int = 30) -> tuple[str, list[str]]`: OSに応じた日本語フォント（Meiryo / Hiragino / Noto Sans）を動的に設定し、`matplotlib.use('Agg')` のもとで `exec()` を実行。標準出力文字列と Base64 エンコードされた PNG 画像のリストを返す。

#### ⑩ `src/gp_chat/code_agent.py`
- **責務**: AIが生成したコードブロックの実行監視、エラー（Traceback）検知、AIへの自己修復依頼ループ制御。
- **主要関数**:
  - `run_code_agent(...) -> tuple[str, list[str], dict]`: チャット応答内の ```python ... ``` ブロックを抽出し、`execution_engine` で実行。エラー発生時はエラーログをフィードバックして修正コードを要求（最大2回ループ）。

#### ⑪ `src/gp_chat/reasoning_agent.py`
- **責務**: Deep Reasoning モードのマルチターン思考パイプライン。
- **主要関数**:
  - `run_reasoning_agent(...) -> tuple[str, dict]`:
    1. Phase 1: 3アプローチ立案 (`temperature=0.4`, JSON出力)。
    2. Phase 2: 各アプローチへの厳格な自己批判 (`temperature=0.2`)。
    3. Phase 3: 自己批判をマージした最終結論ストリーミング統合 (`temperature=0.3`)。

#### ⑫ `src/gp_chat/research_agent.py`
- **責務**: 徹底調査（More Research）モードの ReAct 型自律反復検索ループ。
- **主要関数**:
  - `run_research_agent(...) -> tuple[str, dict]`:
    1. Dynamic Research ループ（最大3サイクル）: 情報十分性を JSON 判定 (`temperature=0.2`)。
    2. 不足時は提案クエリで Google 検索（Groundingツール）を実行し、事実を蓄積。
    3. Synthesis: 全収集事実を統合し、包括的レポートをストリーミング生成 (`temperature=0.3`)。

#### ⑬ `src/gp_chat/report_agent.py`
- **責務**: 会話履歴からのプレゼンテーション用 HTML スライド生成および Headless ブラウザによる PDF 自動エクスポート。
- **主要関数**:
  - `run_report_agent(...) -> tuple[str, str, dict]`: 会話履歴から A4横向きカードUI HTML を生成し、`slide_data/<フォルダ>/<連番>.html` に保存。
  - `_find_pdf_browser() -> str | None`: Edge / Chrome の実行ファイルパスを自動探索。
  - `_render_html_to_pdf(html_path: str, pdf_path: str) -> bool`: Headless ブラウザを `subprocess.run` で起動し、`--print-to-pdf` で PDF を保存。

#### ⑭ `src/gp_chat/pptx_agent.py`
- **責務**: PowerPoint ネイティブプレゼンテーション自動生成、Playwright幾何学バリデーション、AI画像自動生成/トリミング、Marp設計思想の適用、4層パイプラインの実行。
- **主要関数・クラス**:
  - `class PresentationDSLSchema`, `class SlideNode`, `class PlaceholderContent`, `class CropAreaSchema`: Pydantic スキーマ定義。
  - `run_pptx_agent(...) -> tuple[str, str, dict]`: 4層パイプラインを実行し、生成された `.pptx` ファイルパスとサマリーテキストを返す。
  - `_validate_and_fix_slide_overflow(...)`: Playwright (Chromium) でスライドモック HTML を描画し、スクロール溢れ (`scrollHeight > clientHeight`) を検知して Gemini で要約修復（最大3回ループ）。
  - `_generate_ai_image_with_imagen(...)`: `gemini-3.1-flash-lite-image` または `imagen-3.0-generate-002` を呼び出して 16:9 画像をオンデマンド生成（最大4枚）。
  - `_detect_bounding_box_and_crop(...)`: Gemini でバウンディングボックス相対座標（`CropAreaSchema`）を検出し、Pillow で物理トリミング。
  - `_render_slide_to_pptx(...)`: `python-pptx` を使用して `format.pptx` のプレースホルダーに流し込み描画（全30種以上の描画パーツ関数）。

#### ⑮ `src/gp_chat/azure_runtime.py`
- **責務**: Azure OpenAI API クライアント初期化パラメータの管理、環境変数（`.env` および `AZURE_OPENAI_ENV_FILE`）の解決、Codex / GPT-5.6 / GPT-6 専用デプロイメント名のマッピング。
- **主要関数・クラス**:
  - `class AzureRuntime`: `endpoint`, `api_key`, `deployment`, `base_url`, `codex_deployment`, `sol_deployment`, `gpt6_deployment` を保持するイミュータブルデータクラス。
  - `load_azure_runtime_from_env(...) -> AzureRuntime | None`: 環境変数または外部環境設定ファイルから認証情報と各デプロイ名をロードして検証。
  - `is_azure_runtime_available(runtime) -> bool`: エンドポイント・APIキー・デプロイ名が正しく設定されているかを検証。

#### ⑯ `src/gp_chat/azure_responses_router.py`
- **責務**: OpenAI Python SDK v3.x による Azure OpenAI API への通信統括。同期通信（httpx）および HTTP/2 多重化非同期通信（httpx2）の二重化、ストリーミングイベントの正規化パース。
- **主要関数**:
  - `_build_client(runtime: AzureRuntime) -> OpenAI`: 同期クライアント生成（推論モデルの長時間思考に耐えうるタイムアウト3600秒設定）。
  - `_build_async_client(runtime: AzureRuntime) -> AsyncOpenAI`: `httpx2.AsyncClient(http2=True, timeout=httpx2.Timeout(3600.0, connect=60.0))` による HTTP/2 多重化非同期クライアント生成。
  - `generate_response(...) -> AzureRouterResult`: 同期的な一括レスポンス生成。
  - `stream_response(...) -> Iterator[AzureStreamChunk]`: 同期的なイベントストリーミング（思考デルタ `thought_delta`、本文デルタ `text_delta`、Usage、Groundingメタデータを逐次送出）。
  - `async_generate_response(...) -> AzureRouterResult`: 非同期的な一括レスポンス生成（オーケストレーターの Phase 1 および Phase 2 で使用）。
  - `async_stream_response(...) -> AsyncIterator[AzureStreamChunk]`: 非同期的なイベントストリーミング（オーケストレーターの Phase 3 で使用）。

#### ⑰ `src/gp_chat/azure_deep_orchestrator.py`
- **責務**: GPT-5.6 / GPT-6 専用 HTTPX2並行・細切れハイブリッドオーケストレーター。重推論時の APIM / プロキシタイムアウト（504）を回避し、HTTP/2 多重化による並行情報収集とリアルタイム思考ストリーミングを実現。
- **主要関数**:
  - `run_orchestrated_generation(...) -> AzureModeResult`: Streamlit 同期ワーカーから呼び出される公開エントリポイント。`_run_coroutine` を介して非同期処理を実行。
  - `_run_async_orchestrated_generation(...) -> AzureModeResult`: 3フェーズパイプラインの実行本体。
    - **Phase 1 (Planner)**: `reasoning_effort="low"` でタスクを独立した並行サブタスクに分解（`needs_parallel_subtasks=False` またはパース失敗時は Phase 3 へ Early Exit）。
    - **Phase 2 (HTTP/2 Multiplexing)**: `asyncio.Semaphore(AZURE_DEEP_MAX_CONCURRENCY)`（デフォルト 3）で並行数を制限しつつ、単一 TCP 接続上で `httpx2` によりサブタスクを並行実行し、材料を高速回収。
    - **Phase 3 (Synthesizer)**: 収集材料を統合し、`reasoning_effort=effort` で思考推論（`thought_delta`）および本文を逐次ストリーミング描画。
  - `_safe_json_loads(raw_text: str) -> dict[str, Any]`: Markdown コードブロック（```json）や前後のテキストを自動除去して JSON を堅牢にパース。
  - `_run_coroutine(coro)`: 既存のイベントループが稼働中の場合は `ThreadPoolExecutor`、非稼働時は `asyncio.run` で実行する安全な同期/非同期ブリッジ。

#### ⑱ `src/gp_chat/azure_normal_chat.py`
- **責務**: Azure OpenAI を用いた通常チャットおよび Special モードのストリーミング応答制御、推論モデル・高推論時のオーケストレーターディスパッチ。
- **主要関数**:
  - `run_normal_generation(...) -> AzureModeResult`: 通常チャットの生成処理。`model_id` が `5.6` または `6` を含み、かつ `effort in ("high", "deep")` かつ通常モードの場合に、`azure_deep_orchestrator.run_orchestrated_generation` へ自動ディスパッチ。それ以外は `stream_response` でストリーミング実行。
  - `run_special_generation(...) -> AzureModeResult`: Special モード（Canvas コード検証・リファクタリング）のストリーミング実行。

#### ⑲ `src/gp_chat/azure_context_builder.py`
- **責務**: Gemini 形式のコンテキストオブジェクトから Azure OpenAI API 形式（`messages` リスト、Base64 画像、システム指示文）への変換。PDF 添付時は Azure 未対応として `AzureContextBuildError` を送出。

#### ⑳ `src/gp_chat/azure_supervisor_helpers.py`
- **責務**: GCP 側のエラー（レートリミット 429 や 5xx、クォータ超過）を検査し、Azure OpenAI へのフォールバック要否を判定。

#### ㉑ `src/gp_chat/azure_fault_injection.py`
- **責務**: `dev/fault_injection.local.toml` から疑似エラー設定をロードし、テスト・検証用の擬似的な終端 429 例外を注入。

#### ㉒ `src/gp_chat/azure_common_types.py`
- **責務**: Azure 関連モジュール間で共有されるデータクラス群の定義（`AzureModeResult`, `AzureUsageMetadata`, `AzureStreamChunk`, `AzureRouterResult`, `AzureMaterializedContext`）。

#### ㉓ `src/gp_chat/azure_history_utils.py`
- **責務**: 会話履歴メッセージから Azure 呼び出し用の辞書形式リストへの変換ユーティリティ。

#### ㉔ `src/gp_chat/azure_reasoning_agent.py` / `azure_research_agent.py` / `azure_report_agent.py` / `azure_code_agent.py`
- **責務**: 主系（Gemini）に対応する Azure 側の特化型自律エージェント群（Deep Reasoning、徹底調査、HTML/PDFレポート生成、コード実行監視＆自己修復）。

#### ㉕ `src/gp_chat/cloud_logging_utils.py`
- **責務**: Google Cloud Logging への監査ログ送信。
- **主要関数**:
  - `send_cloud_log(user_email: str, model_id: str, prompt_text: str, response_text: str, usage_metadata: dict, ...) -> None`: GCP Cloud Logging に構造化ログを非同期送信。Azure 直接接続時やフォールバック時は 403 エラー防止のため自動スキップ。

---

## 第3章: データモデル & スキーマ完全リファレンス (Data Models & Schemas)

### 3.1 PowerPoint DSL スキーマ (`pptx_agent.py`)

```python
import pydantic
from typing import List, Literal, Optional

class CropAreaSchema(pydantic.BaseModel):
    """画像トリミング領域の相対座標 (0-1000スケール)"""
    ymin: int = pydantic.Field(..., description="切り出し領域の上端 (0-1000)")
    xmin: int = pydantic.Field(..., description="切り出し領域の左端 (0-1000)")
    ymax: int = pydantic.Field(..., description="切り出し領域の下端 (0-1000)")
    xmax: int = pydantic.Field(..., description="切り出し領域の右端 (0-1000)")

class PlaceholderContent(pydantic.BaseModel):
    """スライド内プレースホルダーへの流し込みデータ"""
    idx: int = pydantic.Field(..., description="テンプレート定義のプレースホルダーインデックス (0, 1, 2...)")
    text_content: Optional[str] = pydantic.Field(
        None,
        description="流し込むテキスト。箇条書きは先頭の '• ' を除き、改行 '\\n' で区切る。"
    )
    image_prompt: Optional[str] = pydantic.Field(
        None,
        description="IMAGE 枠の場合の AI 画像生成 (Imagen 3) 用英語プロンプト。"
    )
    use_user_image: bool = pydantic.Field(
        False,
        description="ユーザー添付画像を使用する場合は True。"
    )
    crop_instruction: Optional[str] = pydantic.Field(
        None,
        description="添付画像を使用する際のトリミング指示。"
    )

class SlideNode(pydantic.BaseModel):
    """1枚のスライドの論理構造"""
    slide_number: int = pydantic.Field(..., description="スライド番号 (1始まり)")
    title: str = pydantic.Field(..., description="スライドタイトル")
    layout_name: str = pydantic.Field(..., description="テンプレートから選択したスライドレイアウト名")
    placeholders: List[PlaceholderContent] = pydantic.Field(..., description="各プレースホルダーの流し込みデータ")
    visual_type: Literal["auto", "none", "summary", "timeline", "process", "comparison", "kpi", "matrix", "risk"] = "auto"
    visual_variant: str = "auto"
    color_theme: Literal["light", "dark", "corporate", "creative", "warm", "cool"] = pydantic.Field(
        "corporate",
        description="スライド全体のカラーデザインテーマ"
    )
    accent_color_hex: Optional[str] = pydantic.Field(
        None,
        description="キーポイント・KPI数値・強調矢印等に適用する16進数アクセントカラー (例: '#FF2A2A')"
    )
    coverage_refs: List[str] = pydantic.Field(
        default_factory=list,
        description="反映元のソース事実・要件リファレンス"
    )

class PresentationDSLSchema(pydantic.BaseModel):
    """プレゼンテーション全体の論理構成ルートスキーマ"""
    presentation_title: str = pydantic.Field(..., max_length=30, description="プレゼンテーション全体のタイトル")
    slides: List[SlideNode] = pydantic.Field(..., description="スライドのリスト")
```

### 3.2 Azure 共通データ型 (`azure_common_types.py`)

```python
from __future__ import annotations
import copy
from dataclasses import dataclass, field
from typing import Any

@dataclass
class AzureUsageMetadata:
    prompt_token_count: int = 0
    candidates_token_count: int = 0
    total_token_count: int = 0
    thoughts_token_count: int = 0
    cached_content_token_count: int = 0
    traffic_type: str | None = None

@dataclass
class AzureStreamChunk:
    text_delta: str = ""
    thought_delta: str = ""
    usage_metadata: AzureUsageMetadata | None = None
    grounding_metadata: dict[str, object] | None = None
    route: str = "azure_fallback"
    app_retry_count: int = 0
    sdk_http_headers: dict[str, str] | None = None
    provider: str = "azure"

@dataclass
class AzureRouterResult:
    text: str = ""
    usage_metadata: AzureUsageMetadata | None = None
    grounding_metadata: dict[str, object] | None = None
    route: str = "azure_fallback"
    app_retry_count: int = 0
    sdk_http_headers: dict[str, str] | None = None
    provider: str = "azure"
    response: Any = None

@dataclass
class AzureMaterializedContext:
    messages: list[dict[str, object]]
    system_instruction: str
    available_files_map: dict[str, str] = field(default_factory=dict)
    file_attachments_meta: list[dict[str, object]] = field(default_factory=list)
    retry_context_snapshot: list[dict[str, object]] = field(default_factory=list)

    def clone_retry_context(self) -> list[dict[str, object]]:
        return copy.deepcopy(self.retry_context_snapshot)

@dataclass
class AzureModeResult:
    full_response: str = ""
    thought_log: str = ""
    system_instruction: str = ""
    usage_metadata: AzureUsageMetadata | None = None
    grounding_metadata: dict[str, object] | None = None
    mode_meta: dict[str, object] = field(default_factory=dict)
    available_files_map: dict[str, str] = field(default_factory=dict)
    file_attachments_meta: list[dict[str, object]] = field(default_factory=list)
    retry_context_snapshot: list[dict[str, object]] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
```

### 3.3 GPT-5.6 / GPT-6 並行タスク分解スキーマ (`config.py`)

```python
AZURE_DEEP_PLANNER_SCHEMA = {
    "type": "object",
    "properties": {
        "needs_parallel_subtasks": {
            "type": "boolean",
            "description": "Whether parallel subtask execution is needed."
        },
        "plan_summary": {
            "type": "string",
            "description": "Brief summary of the overall execution approach."
        },
        "subtasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "description": {"type": "string"},
                    "query": {"type": "string"}
                },
                "required": ["id", "description", "query"],
                "additionalProperties": False
            },
            "description": "List of independent subtasks to run in parallel."
        }
    },
    "required": ["needs_parallel_subtasks", "plan_summary", "subtasks"],
    "additionalProperties": False
}
```

### 3.4 会話履歴 JSON スキーマ (`chat_log/*.json`)

```json
{
  "system_role": "You are Gemini, a helpful and versatile AI assistant...",
  "current_model_id": "gemini-3.8-flash",
  "reasoning_effort": "high",
  "enable_google_search": true,
  "enable_more_research": false,
  "report_mode_pdf": false,
  "report_mode_pptx": false,
  "auto_plot_enabled": false,
  "total_usage": {
    "input_tokens": 1250,
    "output_tokens": 3400,
    "total_tokens": 4650
  },
  "messages": [
    {
      "role": "user",
      "content": "最新のAIアーキテクチャについて教えてください。"
    },
    {
      "role": "assistant",
      "content": "GP-Chatの最新アーキテクチャでは...",
      "model_info": "gemini-3.8-flash",
      "thought_log": "### 📋 実行計画 (Phase 1: Task Breakdown)\n...\n### ⚡ サブタスク収集結果 (Phase 2)\n...\n### 🧠 思考推論 & 統合回答生成 (Phase 3)\n...",
      "usage_metadata": {
        "prompt_token_count": 120,
        "candidates_token_count": 350,
        "total_token_count": 470
      },
      "grounding_metadata": {
        "web_search_queries": ["..."]
      }
    }
  ],
  "python_canvases": [
    "# Canvas 1 code...\n",
    "# Canvas 2 code...\n"
  ],
  "canvas_enabled": [true, false]
}
```

---

## 第4章: セッション状態 (Session State) 変数 & クリーンアップ完全仕様 (Session State Management)

### 4.1 全 Session State 変数一覧リファレンス

| 変数名 | 型 | デフォルト値 | 変更契機 | 参照・利用モジュール |
| :--- | :---: | :--- | :--- | :--- |
| `messages` | `list[dict]` | `[]` | ユーザー送信、AIストリーミング完了、会話分岐 (※assistantメッセージ内に `thought_log` を永続化) | `main.py`, `state_manager.py`, 全エージェント |
| `system_role_defined` | `bool` | `False` | 初回プロンプト確定ボタン押下 | `main.py`, `sidebar.py` |
| `current_model_id` | `str` | `gemini-3.8-flash` | サイドバーのモデル選択セレクトボックス | `main.py`, `sidebar.py`, `llm_router.py` |
| `reasoning_effort` | `str` | `high` | サイドバーの推論レベルラジオボタン | `main.py`, `reasoning_agent.py` |
| `enable_google_search` | `bool` | `True` | サイドバーの Web検索チェックボックス | `main.py`, `utils.py`, `research_agent.py` |
| `enable_more_research` | `bool` | `False` | サイドバーの徹底調査トグル | `main.py`, `sidebar.py`, `research_agent.py` |
| `report_mode_pdf` | `bool` | `False` | サイドバーの レポート機能(pdf) トグル | `main.py`, `sidebar.py`, `report_agent.py` |
| `report_mode_pptx` | `bool` | `False` | サイドバーの レポート機能(pptx) トグル | `main.py`, `sidebar.py`, `pptx_agent.py` |
| `auto_plot_enabled` | `bool` | `False` | サイドバーの グラフ描画・データ分析トグル | `main.py`, `code_agent.py` |
| `auto_save_enabled` | `bool` | `True` | サイドバーの自動保存トグル | `main.py`, `state_manager.py` |
| `python_canvases` | `list[str]` | `["# コードはここに \n"]` | Ace Editor への入力、ファイル読込、クリア | `sidebar.py`, `utils.py` |
| `canvas_enabled` | `list[bool]`| `[False]` | 各 Canvas の AI送信トグル、動的ON化 | `sidebar.py`, `utils.py` |
| `always_send_all_canvases`| `bool`| `False` | 全送信トグル切替 | `sidebar.py`, `state_manager.py` |
| `canvas_key_counter` | `int` | `0` | 履歴ロード時・フルリセット時にインクリメント | `sidebar.py`, `state_manager.py` |
| `toggle_keys` | `list[int]` | `[0]` | 個別 Canvas トグルリセット時にインクリメント | `sidebar.py`, `state_manager.py` |
| `uploaded_file_queue` | `list` | `[]` | ファイルアップローダーでのファイル選択/削除 | `sidebar.py`, `utils.py`, `data_manager.py` |
| `clipboard_queue` | `list` | `[]` | クリップボード貼付検知 | `sidebar.py`, `utils.py` |
| `current_chat_filename` | `str` | `None` | 初回保存時、履歴ロード時、分岐時 | `main.py`, `state_manager.py` |
| `current_report_folder` | `str` | `None` | レポート生成時、履歴ロード時 | `report_agent.py`, `pptx_agent.py` |
| `total_usage` | `dict` | `{"input_tokens": 0...}`| API応答完了時にトークン加算 | `main.py`, `state_manager.py` |
| `last_usage_info` | `dict` | `None` | 直近の API 呼び出し完了時 | `main.py` |
| `is_generating` | `bool` | `False` | 生成開始時に `True`、完了/エラー時に `False` | `main.py`, `sidebar.py` (UIロック) |
| `stop_generation` | `bool` | `False` | 停止ボタン押下時に `True` | `main.py`, ストリーミングループ |
| `debug_logs` | `list[dict]`| `[]` | APIリクエスト・レスポンス発生時 | `llm_router.py`, `main.py` |
| `_canvas_reset_pending` | `bool`| `False` | 履歴ロード直後にセット、次フレームで解除 | `sidebar.py` (巻き戻り防止) |

### 4.2 履歴ロード・リセット時の6段階クリーンアップアルゴリズム
`state_manager.cleanup_session_on_load()` は、セッション汚染による誤動作を完全に排除するため、以下の順序でクリーンアップを実行します。

```text
[履歴ロード / 会話リセットトリガー]
   │
   ├─ 1. 【キュー消去】: uploaded_file_queue = [], clipboard_queue = []
   ├─ 2. 【アップローダー初期化】: file_uploader_key += 1 (キャッシュ強制フラッシュ)
   ├─ 3. 【Canvas 送信フラグ再構築】:
   │       ├─ always_send_all_canvases == True  ──▶ 全 Canvas を True
   │       └─ always_send_all_canvases == False ──▶ 意味のあるコードが存在する Canvas のみ True
   ├─ 4. 【一時ウィジェットキー消去】:
   │       └─ session_state 内の ace_*, up_*, cvs_tog_* で始まる全キーを del
   ├─ 5. 【巻き戻り防止フラグセット】:
   │       ├─ _canvas_reset_pending = True
   │       └─ canvas_key_counter += 1, toggle_keys の各要素 += 1
   └─ 6. 【レポートフォルダ整合性確認】:
           └─ ロードデータに存在しない場合は current_report_folder = None
```

---

## 第5章: UI / UX 状態遷移 & 画面制御ロジック (UI State Machine & Interaction Flows)

### 5.1 サイドバー設定の連動・排他ロック制御マトリクス (真理値表)

| モード / 設定状態 | Thinking Level | Web検索 | 徹底調査 | レポート(pdf) | レポート(pptx) | auto_plot |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **通常対話** | 任意選択 (`high`/`medium`/`low`/`deep`) | 任意 (ON/OFF) | 選択可 | 選択可 | 選択可 | 任意 (ON/OFF) |
| **Thinking Level: deep** | `deep` (選択中) | 任意 (ON/OFF) | **ロック (選択不可)** | **ロック (選択不可)** | **ロック (選択不可)** | 任意 (ON/OFF) |
| **徹底調査 (More Research) ON** | **`high` に固定 (ロック)** | **強制 ON (ロック)** | ON (選択中) | **ロック (選択不可)** | **ロック (選択不可)** | 任意 (ON/OFF) |
| **レポート機能 (pdf) ON** | **`high` に固定 (ロック)** | 任意 (ON/OFF) | **ロック (選択不可)** | ON (選択中) | **ロック (選択不可)** | 任意 (ON/OFF) |
| **レポート機能 (pptx) ON** | **`high` に固定 (ロック)** | 任意 (ON/OFF) | **ロック (選択不可)** | **ロック (選択不可)** | ON (選択中) | 任意 (ON/OFF) |
| **生成中 (`is_generating=True`)** | **全設定ロック** | **全設定ロック** | **全設定ロック** | **全設定ロック** | **全設定ロック** | **全設定ロック** |

### 5.2 会話分岐（`✂️ この会話から分岐`）アルゴリズム
1. ユーザーが過去メッセージ $M_k$ の分岐ボタンを押下。
2. 履歴リストを先頭から $M_k$ までスライス: $\text{forked\_messages} = \text{messages}[0 : k+1]$。
3. 累積トークン数を $M_k$ までの合計値に再計算。
4. ファイル名の自動採番（`state_manager.fork_chat_history`）:
   - 元ファイル名が `260823_テーマ.json` の場合 ──▶ `260823_テーマ-02.json`
   - 既に `-02.json` が存在する場合は末尾インクリメント（`-03.json`, `-04.json`...）。
5. 新しいファイル名で保存し、`st.session_state.current_chat_filename` を更新して再実行（`st.rerun()`）。

### 5.3 Markdownコピー（`📋 Markdownをコピー`）仕様
1. **目的**: チャットプレビュー（リッチテキストレンダリング）表示されたAI応答から、元のMarkdown書式テキスト（raw Markdown）を忠実にクリップボードへ取得する。
2. **ボタン配置**: アシスタントメッセージ（`msg["role"] == "assistant"`）の下部アクション領域に、「✂️ この会話から分岐」ボタンと横並び（`st.columns([1, 1])`）で配置。生成中（`is_generating=True`）は非表示。
3. **コピー制御ロジック**:
   - `utils.copy_to_clipboard(msg["content"])` を呼び出し。
   - Windows API (`win32clipboard`, `win32con.CF_UNICODETEXT`) を介してUnicodeテキストをクリップボードに設定。
   - 成功時は `st.toast("📋 クリップボードにMarkdownをコピーしました", icon="✅")` をポップアップ表示。
   - 空文字または例外発生時はエラーハンドリングを行い、UIのクラッシュを防止。

### 5.4 思考プロセスの折りたたみ永続化表示仕様 (`st.expander`)
1. **目的**:
   - 回答生成中のストリーミング一時領域（`st.status`）は、完了後の画面再描画（`st.rerun()`）によって消失する。
   - 回答完了後もユーザーが「どのようなタスク分割が行われたか」「並行サブタスクでどんな材料が集まったか」「モデルがどう推論したか」をいつでも振り返れるよう、思考ログをアコーディオン形式で永続表示する。
2. **データ永続化**:
   - GCP 通常ルート、Deep Reasoning、徹底調査、および Azure オーケストレーターの全ルートにおいて、生成された全思考ログ文字列（`full_thought_log`）をアシスタントメッセージ辞書に `msg["thought_log"] = full_thought_log` として格納し、JSON 自動保存の対象とする。
3. **UI レンダリング仕様**:
   - チャット履歴描画ループにおいて、`msg["role"] == "assistant"` かつ `msg.get("thought_log")` が存在する場合、回答本文の上部に `st.expander("🧠 思考プロセス (Thinking Process)", expanded=False)` を描画。
   - 初期状態は折りたたまれており、回答本文の視認性を妨げない。ユーザーがクリックした際のみ展開され、Phase 1〜3 の思考過程・サブタスク収集結果が Markdown 形式で表示される。

### 5.5 LaTeX数式レンダリング & デリミタ正規化仕様
1. **背景と課題**:
   - Streamlit の `st.markdown()` は内部で KaTeX (`remark-math`) を使用しており、`$`（インライン）および独立行の `$$`（ディスプレイ）のみをデリミタとして解釈する。
   - 一方、LLM（Gemini / GPT）は標準で `\(` / `\)` や `\[` / `\]`、あるいは前後に改行のない埋め込み `$$` を出力することが多く、そのままでは数式としてレンダリングされずに生の構文文字列が表示崩れを起こす。
2. **自動正規化パイプライン (`utils.format_latex_delimiters`)**:
   - 描画直前に以下の多段階フィルターを通過させる：
     1. **コードブロックの完全保護**: Markdown のフェンスコードブロック（```` ```...``` ````, `~~~...~~~`）およびインラインコード（`` `...` ``）を一時プレースホルダーに退避し、コード内の記号（`\(` や `\[` 等）の誤変換を防止。
     2. **ディスプレイ数式変換**: `\[ ... \]` を `\n\n$$\n...\n$$\n\n` に変換。
     3. **独立行化補正**: 行中に埋め込まれた `$$...$$` の前後に改行を補正。
     4. **インライン数式変換**: `\( ... \)` を `$ ... $` に変換。
     5. **コードブロックの復元**: 退避しておいたコードブロックを元の位置にリストア。
3. **適用範囲**:
   - チャット履歴描画ループ（回答本文および思考プロセスアコーディオン）。
   - 全エージェント（通常、Azure、Deep Reasoning、徹底調査等）のリアルタイムストリーミング一時描画領域（`text_placeholder`, `thought_placeholder`）。
   - 「📋 Markdownをコピー」機能（他ツールでの数式互換性向上）。
4. **ユーザー設定との非干渉（プロンプト非依存設計）**:
   - `prompts/prompts.yaml` はユーザー自身がUI等を通じてカスタマイズ・編集する領域であるため、プロンプト本文への制約追加を行わず、描画層（`utils.format_latex_delimiters`）がモデルの出力を自動吸収・正規化するステートレスな設計を採用。これにより、既存のプロンプト資産やユーザーの独自設定に一切影響を与えることなく、高いレンダリング互換性を実現。

---

## 第6章: コンテキスト構築 & マルチモーダルパースパイプライン (Context Materialization & Multimodal Parsing)

### 6.1 各ファイル形式のパース処理詳細

```text
[アップロードファイル]
   │
   ├── 画像形式 (.png, .jpg, .jpeg, .gif, .bmp)
   │    ├─ GCP Vertex AI : types.Part.from_bytes(data=bytes, mime_type=mime)
   │    └─ Azure OpenAI  : data:image/{mime};base64,{base64_str}
   │
   ├── PDF (.pdf)
   │    ├─ GCP Vertex AI : types.Part.from_bytes(data=bytes, mime_type="application/pdf")
   │    └─ Azure OpenAI  : AzureContextBuildError 例外スロー (フォールバック抑止)
   │
   ├── Word (.docx)
   │    └─ python-docx で全段落抽出 ──▶ "[Attached Document: filename]\n" + text
   │
   ├── Excel (.xlsx, .xlsm, .xls)
   │    ├─ python-calamine (高速Rustエンジン) で全シート走査
   │    ├─ pandas.DataFrame.to_markdown() で Markdown テーブル化
   │    └─ "### Sheet: {sheet_name}\n" + table_markdown
   │
   ├── PowerPoint (.ppt, .pptx)
   │    ├─ Windows COM (pywin32) バックグラウンド起動 (POWERPNT.EXE)
   │    ├─ ppSaveAsPNG (18) で各スライドを PNG 抽出
   │    ├─ ハッシュ値による ppt_conversion_cache キャッシュ保存
   │    └─ 各スライド PNG を画像 Part として送信
   │
   └── テキスト / ソースコード (.py, .js, .md, .txt, .json, .csv, .yaml 等)
        ├─ UTF-8 デコード試行
        ├─ 失敗時: CP932 (Shift-JIS) デコード試行
        └─ 失敗時: errors="replace" で文字化け許容デコード ──▶ ```{ext}\n{text}\n```
```

### 6.2 Canvas コードのプロンプトインジェクション仕様
有効な Canvas のコードは、ユーザーメッセージのテキストの**先頭**に以下のフォーマットで注入されます。

```text
[Canvas-1]
```python
# Canvas 1 のコード
import pandas as pd
...
```

[Canvas-3]
```python
# Canvas 3 のコード
def calculate():
    pass
```

ユーザーの入力メッセージテキスト...
```

---

## 第7章: LLMルーティング・二重化 & 障害耐性仕様 (LLM Routing & Fault Tolerance)

### 7.1 二重化クライアント制御フロー (`llm_router.py`)

最新フラッグシップモデル `gemini-3.8-flash` をはじめとする GCP Vertex AI 呼び出しは、`google-genai==2.22.0`（遅延インポート高速化・安定通信）を基盤に、Standard / Priority の二重化クライアント制御と自動フォールバックを備えています。

```mermaid
sequenceDiagram
    autonumber
    participant Main as main.py / Agent
    participant Router as llm_router.py
    participant StdClient as Vertex AI (Standard)
    participant PrioClient as Vertex AI (Priority)
    participant Azure as Azure OpenAI

    Main->>Router: generate_content_with_retry(contents, config)
    Router->>StdClient: リクエスト送信 (Standard)
    
    alt 正常応答 (200 OK)
        StdClient-->>Router: ストリーミングチャンク
        Router-->>Main: 応答返却
    else 一時エラー (429 RateLimit / 500 / 503 等)
        StdClient-->>Router: 429 Too Many Requests
        Note over Router: Priority クライアントへ即時切替
        loop 最大 3 回リトライ (指数バックオフ + Jitter: 2s, 4s, 8s)
            Router->>PrioClient: ヘッダー付与リクエスト (Priority)
            alt リトライ成功
                PrioClient-->>Router: 正常応答
                Router-->>Main: 応答返却
            else リトライ失敗 (429継続)
                PrioClient-->>Router: エラー継続
            end
        end
        Note over Router: GCP 全試行失敗
        Router-->>Main: 例外スロー / エラーログ記録
        
        opt visible_output_started == False かつ Azure有効
            Note over Main: Azure OpenAI 自動フォールバック発動
            Main->>Azure: コンテキストスナップショットで再送
            Azure-->>Main: シームレス応答継続
        end
    end
```

### 7.2 Azure Direct ルーティング & GCPバイパス仕様 (`AZURE_DIRECT_MODELS`)

GP-Chat は、GCP 上に存在しない特殊な機能・モデルを直接 Azure OpenAI へルーティングするバイパスアーキテクチャを備えています。

1. **対象モデル群**:
   - `config.AZURE_DIRECT_MODELS = ("gpt-5.3-codex", "gpt-5.6", "gpt-6")`
2. **バイパス制御ロジック (`main.py`)**:
   - ユーザーが選択した `model_id` が `AZURE_DIRECT_MODELS` に含まれる場合、GCP 側のクライアント初期化およびリクエスト試行を完全にスキップ。
   - `azure_fault_injection.build_synthetic_terminal_429(mode_name)` を介して直接 `_run_azure_mode` へディスパッチ。
3. **デプロイメント名の動的解決 (`azure_runtime.py`)**:
   - `gpt-5.3-codex` ──▶ `AZURE_OPENAI_CODEX_DEPLOYMENT`（デフォルト: `deployment`）
   - `gpt-5.6` ──▶ `AZURE_OPENAI_SOL_DEPLOYMENT`（`gpt-5.6-sol`）
   - `gpt-6` ──▶ `AZURE_OPENAI_GPT6_DEPLOYMENT`（`gpt-6-astra`）
4. **Cloud Logging の安全スキップ (`cloud_logging_utils.py`)**:
   - Azure 直接接続時およびフォールバック時は、GCP リソースへの不要な書き込みや権限エラー（403 Forbidden）を避けるため、Cloud Logging 送信を自動抑止。

---

## 第8章: 5大特化型エージェント完全内部アルゴリズム (Specialized Autonomous Agents)

### 8.1 Deep Reasoning（思考レベル: deep）
- **Brainstorming フェーズ**: `temperature=0.4`, `response_mime_type="application/json"` を指定し、3つの異なるアプローチを立案。
- **Critique フェーズ**: `temperature=0.2` で、各アプローチの論理的欠陥・エッジケース破綻をあえて批判。
- **Integration フェーズ**: 自己批判を `synthesis_instruction` に埋め込み、`temperature=0.3` で最終解をストリーミング合成。

### 8.2 More Research（徹底調査モード）
- **Dynamic Research ループ**: 最大3サイクル。サイクルごとに情報十分性を JSON 判定（`temperature=0.2`）。不足時は提案クエリで Google 検索（Grounding ツール）を実行し、事実情報を蓄積。
- **Synthesis フェーズ**: 全事実を「一次情報優先ルール」とともに統合し、`temperature=0.3` で最終レポートを出力。

### 8.3 Auto-Plot（データ分析・グラフ描画 & 自己修復）
- **コード実行**: 応答内の Python コードを抽出し、OS別フォントを設定したローカルスコープで `exec()`。matplotlib Agg バックエンドで Figure を回収し Base64 インライン表示。
- **自己修復**: `Traceback` 発生時はエラーログをフィードバックして修正コードを要求（最大2回反復）。

### 8.4 Report PDF（HTML/PDF スライド自動生成）
- **HTML 生成**: `prompts.yaml` の `report_pdf` テンプレートに基づき、A4横カードUI HTML を生成。
- **PDF 変換**: ローカルの Edge/Chrome を探索し、`--headless=new --print-to-pdf --virtual-time-budget=5000` で高精度印刷保存。

### 8.5 Report PPTX（PowerPoint ネイティブ生成 4層パイプライン）

```text
【第1層: 構造化 JSON 生成】 (temperature=0.2)
   ├─ PresentationDSLSchema (タイトル, 各スライドノード, color_theme, accent_color_hex)
   └─ format.pptx のレイアウト・プレースホルダー idx 動的マッピング
   │
   ▼
【第2層 & 第3層: 幾何学バリデーション & 要約自己修復】
   ├─ HTMLモック生成 ──▶ Playwright (Chromium headless) レンダリング
   ├─ スクロール溢れ判定 (scrollHeight > clientHeight)
   ├─ 溢れ検出時: Gemini (gemini-3.5-flash) で文字数を 30~50% 削減要約リライト (最大3回)
   └─ ループ上限時フォールバック: フォントサイズ -2pt 強制縮小
   │
   ▼
【画像処理パイプライン】
   ├─ AI画像生成: gemini-3.1-flash-lite-image / imagen-3 (最大4枚)
   └─ 添付画像トリミング: Gemini でバウンディングボックス検知 (CropAreaSchema) ──▶ Pillow トリミング
   │
   ▼
【第4層: 物理 PPTX 生成 & テンプレート後処理】
   ├─ python-pptx でプレースホルダー idx にコンテンツ流し込み
   ├─ 未使用プレースホルダー自動削除
   └─ 表紙タイトル書換、2枚目見本スライド削除、裏表紙の最末尾移動
```

---

## 第9章: Azure OpenAI 専用エージェント群仕様 (Azure Agent Implementations)

| モジュール名 | 役割・対応機能 |
| :--- | :--- |
| `azure_normal_chat.py` | 通常チャットストリーミングおよび Special モードストリーミング。対象推論モデル（`gpt-5.6`, `gpt-6`）かつ高推論時はオーケストレーターへディスパッチ。 |
| `azure_deep_orchestrator.py` | 【新設】GPT-5.6 / GPT-6 専用 HTTPX2並行・細切れハイブリッドオーケストレーター。Phase 1（タスク分解）→ Phase 2（HTTP/2 多重化並行実行）→ Phase 3（思考ストリーミング統合推論）。 |
| `azure_responses_router.py` | OpenAI Python SDK v3.x ベースの同期（httpx）/非同期（httpx2 HTTP/2 多重化）二重化クライアント・通信ルーター。 |
| `azure_reasoning_agent.py` | Azure OpenAI を用いた 3 段階 Deep Reasoning パイプライン。 |
| `azure_research_agent.py` | Azure OpenAI を用いた ReAct 型徹底調査ループ。 |
| `azure_report_agent.py` | Azure OpenAI を用いた HTML プレゼン生成 & PDF 印刷。 |
| `azure_code_agent.py` | Azure OpenAI を用いた Python コード自動実行 & 自己修復ループ。 |

### 9.1 GPT-5.6 / GPT-6 専用 HTTPX2並行・細切れハイブリッドオーケストレーター仕様 (`azure_deep_orchestrator.py`)

#### 9.1.1 開発背景と解決課題 (Gateway Timeout 回避)
1. **タイムアウト問題の根本原因**:
   - Azure API Management (APIM) やリバースプロキシ環境では、アイドル通信タイムアウト（通常 120 秒〜240 秒）が設定されています。
   - `gpt-5.6-sol` や `gpt-6-astra` などのフロンティア推論モデルをコンテキストが肥大化した状態で高推論モード（`reasoning_effort="high"` または `"deep"`）で実行すると、思考トークン生成が完了して最初の応答トークン（First Token）が返るまでに数分〜十数分を要し、中間プロキシによって `504 Gateway Timeout` で切断される障害が発生します。
2. **解決アプローチ (HTTP/2 多重化並行分割 + 思考ストリーミング)**:
   - OpenAI Python SDK v3.x の新トランスポート基盤である `httpx2`（HTTP/2 多重化）を採用。
   - 重大な課題を軽量プロンプトで細切れの独立サブタスクに分解（Phase 1）。
   - 単一 TCP コネクション上で HTTP/2 多重化ストリームを用いて並行して材料を高速収集（Phase 2）。
   - 収集した材料を統合し、高推論モードで思考ログ（`response.reasoning_summary_text.delta`）をストリーミング送出しながら統合推論（Phase 3）。ストリーミングにより常にパケットが流れるため、プロキシの無通信タイムアウトが完全に回避されます。

#### 9.1.2 厳格な発動条件マトリクス
本ハイブリッド・オーケストレーターは、局所化原則に基づき、以下の**すべての条件**を満たす場合のみに限定して自動発動します。

| 判定項目 | 発動条件 | 備考 |
| :--- | :---: | :--- |
| **対象モデル (`model_id`)** | `gpt-5.6` または `gpt-6` | `any(tok in model_id.lower() for tok in ("5.6", "6"))` |
| **推論レベル (`effort`)** | `high` または `deep` | `effort in ("high", "deep")` |
| **動作モード** | 通常チャットモード (`not is_special_mode`) | Specialモード、レポートモード、徹底調査等は除外 |

※ `gpt-5.3-codex` や推論レベル `low` / `medium` 選択時、あるいは GCP 側の通常チャットでは本オーケストレーターは発動せず、既存の単一ストリーミングまたは各特化エージェントが動作します。

#### 9.1.3 3層パイプラインの内部アルゴリズム詳細

```mermaid
sequenceDiagram
    autonumber
    participant UI as Streamlit UI (main.py)
    participant Normal as azure_normal_chat.py
    participant Orch as azure_deep_orchestrator.py
    participant Router as azure_responses_router.py
    participant Azure as Azure OpenAI (HTTP/2)

    UI->>Normal: run_normal_generation (model=gpt-6, effort=high)
    Normal->>Orch: run_orchestrated_generation
    Note over Orch: _run_coroutine による非同期ブリッジ起動
    
    rect rgb(240, 248, 255)
        Note over Orch: 【Phase 1: タスク分解 (Planner)】
        Orch->>Router: async_generate_response (effort=low, JSON Schema)
        Router->>Azure: Task Breakdown Request
        Azure-->>Router: JSON Plan Result
        Router-->>Orch: Plan Response
        Note over Orch: _safe_json_loads によるマークダウン剥ぎ取りパース
    end

    alt needs_parallel_subtasks == True かつ subtasks 存在
        rect rgb(255, 250, 240)
            Note over Orch: 【Phase 2: サブタスク並行実行 (HTTP/2 多重化)】
            Note over Orch: asyncio.Semaphore(AZURE_DEEP_MAX_CONCURRENCY=3)
            par サブタスク 1〜N 並行実行
                Orch->>Router: async_generate_response (sub_1, effort=low)
                Router->>Azure: HTTP/2 Stream 1
                and
                Orch->>Router: async_generate_response (sub_2, effort=low)
                Router->>Azure: HTTP/2 Stream 2
            end
            Azure-->>Router: サブタスク完了応答群
            Router-->>Orch: 各サブタスク材料回収
            Note over Orch: UI進捗更新 (k/N) & thought_log アコーディオン蓄積
        end
    else 単一質問 / Early Exit
        Note over Orch: Phase 2 をスキップして直接 Phase 3 へ移行
    end

    rect rgb(245, 255, 245)
        Note over Orch: 【Phase 3: 思考ストリーミング & 統合推論 (Synthesizer)】
        Note over Orch: 収集材料を synthesis_instruction に統合
        Orch->>Router: async_stream_response (effort=high/deep, stream=True)
        loop 思考デルタ & 本文ストリーミング
            Router->>Azure: Reasoning Stream
            Azure-->>Router: thought_delta / text_delta
            Router-->>Orch: Chunk
            Orch-->>UI: 思考ログ & 本文リアルタイム描画 (504タイムアウト回避)
        end
    end
    Orch-->>Normal: AzureModeResult (thought_log 保持)
    Normal-->>UI: 応答完了 & thought_log をメッセージに永続化
```

1. **Phase 1: タスク分解 (Planner)**:
   - 呼び出しパラメータ: `reasoning_effort="low"`, `temperature=0.2`, `max_output_tokens=4096`, `response_schema=AZURE_DEEP_PLANNER_SCHEMA`。
   - `_safe_json_loads(raw_text)`: モデルが返答の先頭・末尾に ````json ... ```` のフェンス記号や解説文を付与した場合でも、最初の `{` から最後の `}` を正確にスライスしてパース。
   - **Early Exit 条件**: `needs_parallel_subtasks` が `False`、`subtasks` が空リスト、またはパース例外時は、直ちに単一推論モードとして Phase 3 へ移行。
2. **Phase 2: サブタスク並行実行 (HTTP/2 多重化)**:
   - 多重化クライアント: `_build_async_client(runtime)` により `httpx2.AsyncClient(http2=True, timeout=httpx2.Timeout(3600.0, connect=60.0))` を生成。
   - 同時実行制御: `asyncio.Semaphore(AZURE_DEEP_MAX_CONCURRENCY)`（デフォルト 3、環境変数 `AZURE_DEEP_MAX_CONCURRENCY` で変更可能）により API レートリミット（429）を防止。
   - UI 進捗表示: `thought_status.update(label="Executing parallel subtasks (k/N)...")` でリアルタイム通知。
   - 耐障害性: サブタスクが例外を送出した場合でも `state_manager.add_debug_log` に記録し、エラーメッセージを材料として Phase 3 に引き継ぐ（ベストエフォート救済）。
3. **Phase 3: 思考ストリーミング & 統合推論 (Synthesizer)**:
   - サブタスクで収集した全材料を Markdown 形式でフォーマットし、システム指示文（`synthesis_instruction`）に結合。
   - `async_stream_response` をユーザー指定の `reasoning_effort`（`high` または `deep`）でストリーミング呼び出し。
   - `thought_delta`（モデルの思考過程）および `text_delta`（回答本文）を Streamlit の UI プレースホルダーへ逐次描画。

#### 9.1.4 同期・非同期ブリッジ機構 (`_run_coroutine`)
- Streamlit の実行スレッドは同期ブロッキングモデルです。
- `_run_coroutine` は `asyncio.get_running_loop()` を検査し、すでにイベントループが実行されている環境では `concurrent.futures.ThreadPoolExecutor(max_workers=1)` を生成して別スレッドで `asyncio.run(coro)` を実行。イベントループ非稼働環境では直接 `asyncio.run(coro)` を呼び出すことで、スレッド競合やデッドロックを完全に防止しています。

---

## 第10章: 関数間呼び出し関係 & シーケンス詳細 (Function Call Graphs & Sequence Diagrams)

```mermaid
graph LR
    subgraph UI Layer
        main[main.py]
        sidebar[sidebar.py]
    end

    subgraph Router & Context
        builder[utils.build_materialized_chat_context]
        az_builder[azure_context_builder.build_materialized_context]
        router[llm_router.generate_content_with_retry]
        az_router[azure_normal_chat.run_normal_generation]
        az_orch[azure_deep_orchestrator.run_orchestrated_generation]
        az_resp_router[azure_responses_router.async_stream/generate]
    end

    subgraph Agents
        reasoning[reasoning_agent.py]
        research[research_agent.py]
        report[report_agent.py]
        pptx[pptx_agent.py]
        code[code_agent.py]
    end

    subgraph Engine & State
        engine[execution_engine.execute_code]
        state[state_manager.save_chat_history]
        data[data_manager.save_uploaded_file]
        logging[cloud_logging_utils.send_cloud_log]
    end

    main --> sidebar
    main --> builder
    main --> az_builder
    main --> router
    main --> az_router
    az_router -- "gpt-5.6/6 & high/deep" --> az_orch
    az_orch --> az_resp_router
    main --> reasoning
    main --> research
    main --> report
    main --> pptx
    main --> code
    code --> engine
    pptx --> engine
    main --> state
    main --> data
    main --> logging
```

---

## 第11章: 例外処理方針 & エラーハンドリングマトリクス (Exception Handling Matrix)

| 発生例外 / エラー種別 | 発生箇所 | システムの回復アクション | ユーザーへの通知 |
| :--- | :--- | :--- | :--- |
| **`429 Rate Limit (Vertex AI)`** | `llm_router.py` | Priorityクライアント切替 → 指数バックオフトライ → Azure Fallback | トースト警告 / Azure切替表示 |
| **`AzureContextBuildError`** | `azure_context_builder.py`| PDF添付時等、Azure非対応コンテキストを検知しフォールバック抑止 | UIにGCPエラーをそのまま通知 |
| **`Orchestrator Phase 1 JSONDecodeError`** | `azure_deep_orchestrator.py` | `_safe_json_loads` でフェンス除去後もパース失敗時は Phase 2 をスキップし単一直接推論（Early Exit） | UIクラッシュ回避、シームレス回答生成 |
| **`Orchestrator Phase 2 Subtask Error`** | `azure_deep_orchestrator.py` | サブタスク例外をログ記録し、エラー文を材料として Phase 3 へ引き継ぐ（ベストエフォート救済） | UI進捗更新、総合回答内で分析補完 |
| **`Python Execution Syntax/Runtime Error`**| `execution_engine.py` | TracebackをAIにフィードバックし自己修復ループ（最大2回） | 修復中スピナー / 最終エラー表示 |
| **`Playwright Overflow Error`** | `pptx_agent.py` | 文字数30~50%削減要約リライト（最大3回） → フォント-2pt縮小 | スライド自動調整中メッセージ |
| **`PowerPoint COM Error`** | `utils.py` | プロセス強制クリーンアップ、テキストのみ抽出フォールバック | 警告メッセージ表示 |
| **`mail.txt 未設定 / 不正`** | `main.py` | アプリ操作をブロックし、メールアドレス入力画面を表示 | 入力フォーム表示 |

---

## 第12章: 設定ファイル & プロンプト定義完全仕様 (Configuration & Prompts)

### 12.1 プロンプト設定ファイル (`prompts/prompts.yaml`)
- `default_system_prompt`: 汎用AIアシスタントプロンプト（汎用知識、コーディング、ドキュメント解析、画像理解、データ分析）。
- `engineer`: エンジニア特化型プロンプト。
- `translator`: 翻訳アシスタントプロンプト。
- `report_pdf`: A4横カードUI HTMLスライド生成用テンプレートプロンプト。
- `pptx_system_instruction`: Marp設計思想を統合したPowerPointスライド生成プロンプト。

### 12.2 静的構成設定 (`config.yaml`)
- Canvasへのファイル読込で許可する拡張子リスト（`.py`, `.js`, `.md`, `.txt`, `.yaml`, `.json`, `.csv`, `.sql` 等）。

### 12.3 環境変数設定サンプル (`sample_of.env`)
- **GCP / Vertex AI**:
  - `GCP_PROJECT_ID`: Google Cloud プロジェクトID。
  - `GCP_LOCATION`: Vertex AI のリージョン（デフォルト: `global`）。
  - `GOOGLE_APPLICATION_CREDENTIALS`: サービスアカウントキーのファイルパス。
  - `GEMINI_MODEL_ID`: デフォルトのモデルID（デフォルト: `gemini-3.8-flash`）。
  - `MAX_TOKEN`: 生成最大トークン数（デフォルト: `65536`）。
- **Azure OpenAI**:
  - `AZURE_OPENAI_ENV_FILE`: 外部環境変数ファイルの参照パス（任意）。
  - `AZURE_OPENAI_ENDPOINT`: リソースのエンドポイントURL。
  - `AZURE_OPENAI_API_KEY`: APIアクセスキー。
  - `AZURE_OPENAI_GPT54_DEPLOYMENT`: 標準GPTモデル用デプロイ名。
  - `AZURE_OPENAI_CODEX_DEPLOYMENT`: コーディング専用Codex用デプロイ名（例: `gpt-5.3-codex`）。
  - `AZURE_OPENAI_SOL_DEPLOYMENT`: 専用用途推論モデル用デプロイ名（例: `gpt-5.6-sol`）。
  - `AZURE_OPENAI_GPT6_DEPLOYMENT`: 最新フロンティアモデル用デプロイ名（例: `gpt-6-astra`）。
  - `AZURE_DEEP_MAX_CONCURRENCY`: GPT-5.6 / GPT-6 並行サブタスクの最大同時実行数（デフォルト: `3`）。
- **Cloud Logging**:
  - `GP_CHAT_CLOUD_LOGGING_ENABLED`: 監査ログ送信フラグ（デフォルト: `"true"`）。
  - `GP_CHAT_LOG_SERVICE_NAME`: サービス識別名（デフォルト: `"gp-chat-app"`）。

### 12.4 依存パッケージ仕様 (`pyproject.toml` / `requirements.txt`)
システムの完全な再現性と長期稼働安定性を保証するため、全22個の依存パッケージが実績値（`==`）で完全固定されています。
- `streamlit==1.52.2`
- `google-genai==2.22.0`（Gemini 3.8 Flash 公式対応、遅延インポート高速化）
- `google-auth==2.57.1`
- `openai==3.8.0`（OpenAI Python SDK v3.x）
- `httpx2==2.12.0` および `h2==4.4.1`（HTTP/2 多重化通信エンジン）
- `python-pptx==1.0.2`, `playwright==1.61.0`（PowerPoint ネイティブ生成 & 幾何学バリデーション）
- `python-calamine==0.6.2`, `openpyxl==3.1.5`, `python-docx==1.2.0`（Officeファイル高速パース）
- `pillow==11.1.0`, `matplotlib==3.10.8`, `pandas==2.3.3`, `pylint==4.0.4` 等

---

## 第13章: 改訂履歴 (Revision History)

* **2026-09-08 / 2026-09-09**
  * AI記述エリアにおけるLaTeX数式レンダリング最適化 (KaTeX対応 & デリミタ自動正規化):
    * Streamlit (`st.markdown`) 内の KaTeX パーサーが `$` / `$$` のみをサポートし、LLM標準の `\(` / `\)` や `\[` / `\]`、改行なし埋め込み `$$` を解釈できず生テキスト表示される問題を解消。
    * `src/gp_chat/utils.py` に `format_latex_delimiters` を実装。コードブロック（```` ```...``` ````, `` `...` ``）を完全保護した上で、`\[` / `\]` を独立行 `$$`、`\(` / `\)` を `$` に正規化する安全な変換パイプラインを確立。
    * `main.py`、`azure_normal_chat.py`、`azure_deep_orchestrator.py`、`azure_research_agent.py`、`azure_reasoning_agent.py`、`reasoning_agent.py`、`research_agent.py` の全描画部（履歴・ストリーミング・思考ログ・Markdownコピー）に正規化処理を適用。
    * ユーザーによるプロンプトカスタマイズ資産との競合を防ぐため、`prompts.yaml` は変更せず、描画層（`utils.format_latex_delimiters`）がモデルの出力を自動吸収・正規化するステートレス設計を採用。
    * `tests/test_latex_formatter.py` を新設し、インライン・ディスプレイ・コードブロック保護・通貨記号共存等の10件の網羅的単体テスト（Pylint 10.00/10）を配備。
    * 第2章（utils.py責務一覧）および第5章（5.5節）に仕様を追記。
* **2026-09-05**
  * システム設計仕様書 (software-sheet.md) の完全最新化:
    * アプリケーションの直近の全アップデート（GPT-6対応、httpx2によるHTTP/2通信基盤、GPT-5.6/6高推論限定のAPI並行処理オーケストレーター、Gemini 3.8 Flash対応、思考プロセスの折りたたみ永続化、全依存関係完全固定）を仕様書全体（第1章〜第13章）に整合・反映。
    * 第1章（コア設計原則）に GPT-6 直接接続および HTTP/2 多重化推論アーキテクチャを追加。
    * 第2章（モジュール一覧）に `azure_deep_orchestrator.py` を追加し、各モジュール詳細仕様を個別セクションに拡充。
    * 第3章に `azure_common_types.py` の最新スキーマおよび `AZURE_DEEP_PLANNER_SCHEMA` を反映。
    * 第4章・第5章に `gemini-3.8-flash` 初期値および思考プロセスのアコーディオン折りたたみ表示仕様（`st.expander`）を追記。
    * 第7章に Gemini 3.8 Flash の主系運用および Azure Direct ルーティング（GCPバイパス）を追記。
    * 第9章に GPT-5.6 / GPT-6 専用ハイブリッド・オーケストレーターの完全仕様（3層パイプライン、シーケンス図、セマフォ制御、JSONパース保護、非同期ブリッジ）を詳細記述。
    * 第10章（Call Graph）および第11章（エラーハンドリングマトリクス）にオーケストレーターの通信経路・例外回復アクションを反映。
    * 第12章に環境変数（`AZURE_OPENAI_GPT6_DEPLOYMENT`, `AZURE_DEEP_MAX_CONCURRENCY` 等）および全22パッケージ完全固定仕様を追記。
  * 思考プロセスの折りたたみ永続化 & 全依存関係の完全固定（==化）:
    * `main.py` において、回答完了後もタスク分割や思考過程をいつでも振り返れるよう、メッセージデータに `thought_log` を永続化し、チャット履歴描画ループに `st.expander("🧠 思考プロセス (Thinking Process)", expanded=False)` を追加。
    * アプリケーションの動作再現性と長期稼働安定性を高めるため、`pyproject.toml` および `requirements.txt` の全依存パッケージ（22個＋build）を動作検証済みの実績バージョン（`==`）に統一・完全固定。
* **2026-09-05**
  * 第三者レビュー & 堅牢化検証 (/review):
    * `azure_deep_orchestrator.py` のタスク分解（Phase 1）において、マークダウンコードブロックや前後の解説文が混入した場合でも確実に JSON を抽出・復元する `_safe_json_loads` を実装。
    * 不要な `import streamlit as st` の削除、構文・型チェックおよび Pylint 静的解析（10.00/10 達成）の実施。
    * LF 改行コードの統一および Windows 環境における文字化け・エンコーディング例外の予防措置を確認。
* **2026-09-05**
  * GPT-5.6 / GPT-6 専用 HTTPX2並行・細切れハイブリッドオーケストレーターの導入:
    * `pyproject.toml` の `openai` 依存を `>=3.0.0` へ上限解除・更新し、`httpx2>=0.1.0` および `h2>=4.1.0` を追加。
    * `azure_responses_router.py` に `httpx2.AsyncClient(http2=True)` を用いた `_build_async_client`、`async_generate_response`、`async_stream_response` を実装。
    * `azure_deep_orchestrator.py` を新設し、Phase 1（タスク分解）→ Phase 2（HTTP/2 並行実行）→ Phase 3（思考ストリーミング統合）の3層アーキテクチャを実装。
    * `azure_normal_chat.py` にて `gpt-5.6` / `gpt-6` かつ `effort in ("high", "deep")` 時のディスパッチ処理を追加。
* **2026-09-05**
  * `install.bat` の改善: ユーザー環境での `.whl` 上書きインストール時に依存パッケージを `pyproject.toml`（.whl 内の METADATA）通りに自動更新できるよう、`pip install` コマンドに `--upgrade` オプションを追加。
* **2026-09-05**
  * `pyproject.toml` の依存定義更新: `google-genai` を最新の `2.22.0`（Gemini 3.8 Flash対応・遅延インポート高速化）に更新。それに伴い、依存要件を満たすよう `google-auth` を `google-auth>=2.56.0, <3.0.0` に緩和・更新（仮想環境には最新 2.57.1 が適合）。
* **2026-09-05**
  * `pyproject.toml` の依存定義修正: OpenAI Python SDK 3.0.0（HTTPX2移行）による破壊的変更からシステムを保護するため、依存定義を `openai>=2.45.0, <3.0.0` に厳格化。
* **2026-08-23**
  * チャット画面のUI改修: 各AI返答メッセージ下部に「📋 Markdownをコピー」ボタンを追加。`utils.copy_to_clipboard`（Windows `win32clipboard` による Unicode コピー）および `st.toast` 通知との連携仕様を策定・実装。
* **2026-08-23**
  * システム全体を1行単位で完全に把握・再構築・保守・拡張できる「完全システム設計仕様書（全13章・超詳細版）」として全面刷新・拡充。全モジュール責務対照表、Pydantic/Azureスキーマ、UI制御真理値表、関数間Call Graph、例外処理マトリクスを完全統合。
* **2026-07-05**
  * PowerPointネイティブ生成機能（Report PPTX）において、Marp用の `SKILL.md` のデザイン設計思想を統合。One idea per slide原則、リストの最大6行制限、データの強調を主としたカラーデザイン階層化（`color_theme`、`accent_color_hex`の動的制御）、および枠線廃止による共通描画パーツのフラットモダン化を実施。
* **2026-07-05**
  * PowerPointレポート自動生成において、スライドの創造性向上のため `gemini-3.1-flash-lite-image` を用いたAI画像生成の積極的活用（目安枚数を最大4枚程度へ引き上げ、概念図やアイコンビジュアルの生成を促進）を行うようプロンプト指示を調整。
* **2026-07-04**
  * 最新の PowerPoint ネイティブ生成機能（`pptx_agent.py`, `format.pptx` 等）の導入に伴い、ファイル構成ツリー、主要な依存パッケージ（`python-pptx`, `playwright`）、サイドバー UI の排他・連動ロック仕様（pdf / pptx の分割）、および Report PPTX 特化エージェントの4層パイプライン動作詳細アルゴリズムを追記。
* **2026-07-04**
  * システム全体を完全に再構築可能なレベル（パッケージ構成、UIレイアウト、状態制御マトリクス、エージェントアルゴリズム、コンテキスト構築、ルーティング・高可用性仕様、セッション管理とクリーンアップ処理フロー）に仕様書の記述を大幅に拡充・詳細化。
* **2026-06-13**
  * 会話履歴読み込み時のセッションクリーンアップ処理（添付キュー・一時ウィジェットキーの削除、送信フラグの自動再構築）の仕様を追記。
* **2026-06-06**
  * システムプロンプト上書き確認ダイアログ (`st.dialog`)、プロンプト保存永続化先変更、マルチコードの常時有効化に伴う UI 変更（マルチコードトグルの廃止）の仕様を追記。
* **2026-05-23**
  * `gpt-5.3-codex` 直接接続（GCPバイパス）機能、Azure 使用時の GCP Cloud Logging 抑止、環境変数 `AZURE_OPENAI_CODEX_DEPLOYMENT` に関する仕様を追記。

