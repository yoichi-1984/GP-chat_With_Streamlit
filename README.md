# GP-Chat: 次世代マルチモーダル AI チャット & ドキュメント・スライド生成ワークステーション

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/framework-Streamlit%201.52.2-FF4B4B.svg)](https://streamlit.io/)
[![Google GenAI](https://img.shields.io/badge/LLM-Google%20GenAI%20SDK%202.22.0-4285F4.svg)](https://cloud.google.com/vertex-ai)
[![OpenAI SDK](https://img.shields.io/badge/LLM-OpenAI%203.8.0%20%2F%20httpx2-0078D4.svg)](https://azure.microsoft.com/products/ai-services/openai-service)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)

---

## 📖 はじめに (Introduction)

`GP-Chat` は、Google Cloud Platform (Vertex AI) の **Gemini モデル群 (最新フラッグシップ Gemini 3.8 Flash 含む)** および **Azure OpenAI サービス (GPT-5.6 / GPT-6 含む)** を高度に統合・最適化した、エンタープライズ対応の Streamlit ベース次世代 AI ワークステーションです。

本ドキュメントは、本アプリケーションの**システム仕様書兼開発・運用マニュアル**です。システムの全体アーキテクチャ、ファイル構造、UI/UX 挙動、特化型自律エージェントの内部アルゴリズム、二重化ルーティングと障害耐性、コンテキスト管理、および全セッション状態変数に至るまで、主要な設計情報を網羅しています。

---

## 📑 目次 (Table of Contents)

1. [システム概要 & コアコンセプト](#1-システム概要--コアコンセプト)
2. [システムアーキテクチャ & ファイル・モジュール責務一覧](#2-システムアーキテクチャ--ファイルモジュール責務一覧)
3. [動作環境 & 前提条件 & 依存ライブラリ](#3-動作環境--前提条件--依存ライブラリ)
4. [完全セットアップ & 環境変数リファレンス](#4-完全セットアップ--環境変数リファレンス)
5. [アプリケーションの起動と運用](#5-アプリケーションの起動と運用)
6. [UI / UX 機能仕様 & 画面詳細リファレンス](#6-ui--ux-機能仕様--画面詳細リファレンス)
7. [5大特化型エージェント詳細仕様 & アルゴリズム](#7-5大特化型エージェント詳細仕様--アルゴリズム)
8. [LLMルーティング・高可用性 & 障害耐性仕様](#8-llmルーティング高可用性--障害耐性仕様)
9. [マルチモーダル・ファイル解析 & コンテキスト構築仕様](#9-マルチモーダルファイル解析--コンテキスト構築仕様)
10. [Session State（セッション状態変数）完全リファレンス](#10-session-stateセッション状態変数完全リファレンス)
11. [開発・テスト・トラブルシューティングガイド](#11-開発テストトラブルシューティングガイド)
12. [ライセンス & 作者情報](#12-ライセンス--作者情報)

---

## 1. システム概要 & コアコンセプト

GP-Chat は、一般的な対話型チャットの枠を超え、データ分析、コード開発、Webリサーチ、および高品質なプレゼンテーション資料作成をひとつの環境で完結させる「AI駆動型統合ワークステーション」です。

### 🌟 コア機能ハイライト
- **ハイブリッド LLM 冗長化構成**:
  - 主系: **GCP Vertex AI (`gemini-3.8-flash` 等)** を Standard / Priority クライアントの二重化制御で利用。
  - 副系: API レートリミット（429）や障害検知時に **Azure OpenAI** へ自動フォールバック。
  - 特化モデル: `gpt-5.3-codex` / `gpt-5.6` / `gpt-6` 選択時は GCP をバイパスし Azure へ直接接続。
- **GPT-5.6 / GPT-6 専用 HTTPX2並行ハイブリッドオーケストレーター**:
  - 重推論（`high`/`deep`）実行時の APIM タイムアウト（504）を回避するため、タスク分解（Phase 1）→ HTTP/2 多重化並行実行（Phase 2）→ 思考ストリーミング統合推論（Phase 3）の自律パイプラインを搭載。
- **思考プロセスの折りたたみ永続化**:
  - 回答完了後の画面再描画後も、思考過程や並行タスク結果をメッセージ上部のアコーディオン（`st.expander`）からいつでも閲覧可能。
- **最大 40 スロットのマルチ Canvas コードエディタ**:
  - 独立した Python エディタ（Ace Editor）を統合。コード入力やファイル読込時に送信フラグを動的 ON 化。Pylint による構文自動検証付き。
- **5つの特化型自律エージェント**:
  1. **Deep Reasoning**: 3つのアプローチ立案 → 厳格な自己批判（Critique） → 最適解統合（マルチターン思考）。
  2. **More Research**: Google Search Grounding を自律反復する ReAct 型深掘り検索ループ（最大3サイクル）。
  3. **Auto-Plot**: ローカル環境での Python コード自動実行、OS別日本語フォント動的判別、最大2回の自己修復ループ。
  4. **Report PDF**: カードUIスタイルの HTML プレゼンを生成し、ローカルの Headless ブラウザ（Edge/Chrome）で PDF 化。
  5. **Report PPTX**: Marp設計思想に基づく PowerPoint ネイティブスライド生成、Playwright による幾何学溢れバリデーション & 文字数要約修復、AI画像自動生成/トリミングの 4層パイプライン。
- **完全なセッション & 履歴管理**:
  - 会話履歴の自動保存、JSON エクスポート / インポート。
  - 過去メッセージからの **「✂️ この会話から分岐」** によるツリー型対話。
  - 意図しない通信遮断・クラッシュ時の **未送信ドラフト自動復元**。

### 🏗️ 全体データフロー図

```mermaid
graph TD
    User([ユーザー入力 / 添付ファイル / Canvas]) --> Main[main.py: メインコントローラー]
    Main --> Builder[utils / azure_context_builder: コンテキスト構築]
    
    Builder --> Router{llm_router: モデル判定}
    Router -->|Gemini モデル| StandardClient[Vertex AI Standard Client]
    Router -->|gpt-5.3-codex / gpt-5.6 / gpt-6| AzureDirect[Azure OpenAI 直接接続]
    
    StandardClient -->|429 / 一時エラー| PriorityClient[Vertex AI Priority Client + Jitterリトライ]
    PriorityClient -->|全リトライ失敗| AzureFallback[Azure OpenAI 自動フォールバック]
    
    StandardClient -->|応答ストリーム| AgentRouter{特化モード判定}
    PriorityClient -->|応答ストリーム| AgentRouter
    AzureDirect -->|応答ストリーム| AgentRouter
    AzureFallback -->|応答ストリーム| AgentRouter
    
    AgentRouter -->|通常対話| StreamUI[UI ストリーミング出力]
    AgentRouter -->|Thinking: deep| DeepAgent[reasoning_agent: 立案・批判・統合]
    AgentRouter -->|More Research| ResearchAgent[research_agent: ReAct検索ループ]
    AgentRouter -->|Auto-Plot| PlotAgent[execution_engine: Python実行 & 自己修復]
    AgentRouter -->|Report PDF| PdfAgent[report_agent: HTML生成 & Headless PDF印刷]
    AgentRouter -->|Report PPTX| PptxAgent[pptx_agent: Playwright幾何学検証 & 物理PPTX生成]
    
    AgentRouter --> CloudLogging[GCP Cloud Logging 監査ログ送信 (Azure時はスキップ)]
    AgentRouter --> AutoSave[state_manager: chat_log/*.json 自動保存]
```

---

## 2. システムアーキテクチャ & ファイル・モジュール責務一覧

### 📁 ディレクトリ構造

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
├── dev/
│   └── fault_injection.local.toml # 疑似エラー注入・フォールバック検証用設定
├── env/
│   └── *.env                   # 環境変数定義ファイル群（UI上で動的切替可能）
├── prompts/
│   └── prompts.yaml            # UI編集・永続化用システムプロンプト設定（カレント優先）
├── slide_data/
│   └── <チャットタイトル>/      # 生成されたHTML/PDFスライドの格納ディレクトリ
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

### 🧩 各モジュールの詳細責務一覧

| モジュール名 | 主要クラス / 関数 | 主な責務・内部動作 |
| :--- | :--- | :--- |
| `main_runner.py` | `run()` | CLIコマンド `gp-chat` のエントリポイント。`sys.argv` を構築して `streamlit.web.cli.main()` を呼出。 |
| `main.py` | `main()` | UI全体の描画制御、セッション初期化、チャット入力受付、ストリーミング出力、思考ログ永続化、モデル別バイパス・Azure Fallback制御。 |
| `sidebar.py` | `render_sidebar()` | サイドバー描画、`.env` 切替、モデル選択（9モデル）、Thinking Level、排他トグル制御、Canvas（st_ace）描画、履歴ロード/リセット。 |
| `config.py` | `UITexts`, `SESSION_STATE_DEFAULTS` | システム定数（最大Canvas数=40、タイムアウト=30秒、リトライ間隔）、UI文言、選択可能モデル一覧、初期状態定義。 |
| `utils.py` | `parse_file()`, `build_materialized_chat_context()` | Word/Excel/PPT/PDF/画像のマルチモーダルパース、MIME判定、プロンプト読込、Gemini用Partリスト構築。 |
| `state_manager.py` | `save_chat_history()`, `cleanup_session_on_load()` | 会話履歴のJSON保存/読込、会話分岐（`✂️`）、中断検知・ドラフト復元、不要な一時ウィジェットキー削除。 |
| `data_manager.py` | `save_uploaded_file()`, `cleanup_temp_workspace()` | セッションごとの一時作業領域（`temp_workspace/<UUID>`）の管理、ファイルポインタ保護。 |
| `llm_router.py` | `get_gemini_client()`, `generate_content_with_retry()` | Vertex AI クライアント初期化、Standard/Priority 切替、指数バックオフ＋Jitterリトライ制御。 |
| `execution_engine.py` | `execute_code()` | ローカル環境スコープでのPython実行、Aggバックエンドでのグラフ画像キャプチャ、標準出力・標準エラー回収。 |
| `code_agent.py` | `run_code_agent()` | 生成されたコードの実行結果を監視し、Traceback発生時にAIへ自己修復を依頼する最大2回の反復制御。 |
| `reasoning_agent.py` | `run_reasoning_agent()` | 「3アプローチ立案 (temp=0.4) → 自己批判 (temp=0.2) → 統合出力 (temp=0.3)」の3段階推論パイプライン。 |
| `research_agent.py` | `run_research_agent()` | 情報過不足をJSON評価しながらGoogle検索を自律反復する最大3サイクルのReAct型深掘り調査。 |
| `report_agent.py` | `run_report_agent()` | 会話履歴からA4横向きHTMLプレゼンを生成し、Headlessブラウザ（Edge/Chrome）でPDFへ自動エクスポート。 |
| `pptx_agent.py` | `run_pptx_agent()` | PowerPointネイティブ生成。JSON DSL生成、Playwright幾何学溢れバリデーション、画像生成/トリミング、物理PPTX生成の4層構造。 |
| `azure_runtime.py` | `load_azure_runtime_from_env()` | Azure OpenAI クライアント初期化、エンドポイント・APIキー・Codex/GPT-5.6/GPT-6専用デプロイメント名の検証と管理。 |
| `azure_responses_router.py` | `generate_response()`, `async_stream_response()` | OpenAI SDK v3.x による同期/非同期（httpx2 HTTP/2多重化）二重化クライアント・通信ルーター。 |
| `azure_deep_orchestrator.py` | `run_orchestrated_generation()` | GPT-5.6 / GPT-6 専用 HTTPX2並行ハイブリッドオーケストレーター（タスク分解・並行回収・思考ストリーミング）。 |
| `azure_normal_chat.py` | `run_normal_generation()` | Azure通常チャット。対象推論モデル・高推論時はオーケストレーターへ自動ディスパッチ。 |
| `azure_context_builder.py` | `build_materialized_context()` | Gemini用コンテキストをAzure OpenAI API形式（画像base64、PDF非対応例外ハンドリング）に変換。 |
| `azure_supervisor_helpers.py` | `should_fallback_to_azure()` | GCP側のエラー状態・デバッグログを検査し、Azure側への切り替え要否を判定。 |
| `cloud_logging_utils.py` | `send_cloud_log()` | GCP Cloud Logging への監査ログ送信。Azure直接接続・フォールバック時は自動スキップ。 |

---

## 3. 動作環境 & 前提条件 & 依存ライブラリ

### ① 実行環境要件
* **Python バージョン**: `Python >= 3.11` (Python 3.11, 3.12, 3.13 に対応)
* **動作対応 OS**:
  - **Windows 10 / 11** (全機能が完全動作する推奨環境)
  - **macOS** (PowerPoint添付時のCOM変換、一部ブラウザ印刷を除く全機能に対応)
  - **Linux (Ubuntu等)** (PowerPoint添付時のCOM変換を除く全機能に対応)

### ② 主要依存パッケージ完全マトリクス
システムの完全な再現性を担保するため、すべての依存パッケージが動作検証済みの実績バージョン（`==`）で固定されています。

```toml
# pyproject.toml より抜粋 (全22パッケージ固定)
dependencies = [
    "streamlit==1.52.2",              # WebUIフレームワーク
    "google-genai==2.22.0",            # Google GenAI 統一 SDK (Gemini 3.8 Flash 公式対応)
    "google-auth==2.57.1",             # GCP 認証ライブラリ
    "google-cloud-logging==3.15.0",    # GCP Cloud Logging 監査ログ送信用
    "python-dotenv==1.2.1",            # .env 環境変数ローダー
    "streamlit-ace==0.1.1",            # コードエディタ (Ace Editor) ウィジェット
    "pylint==4.0.4",                   # Canvas コード構文検証
    "PyYAML==6.0.3",                   # prompts.yaml / config.yaml 解析
    "python-docx==1.2.0",              # Word (.docx) テキスト抽出
    "pywin32==311; sys_platform == 'win32'", # Windows COM 連携 (PowerPointスライドPNG化)
    "pillow==11.1.0",                  # 画像処理 & バウンディングボックストリミング
    "pandas==2.3.3",                   # データ分析 & 表形式データ処理
    "matplotlib==3.10.8",              # ローカルグラフ自動描画
    "openai==3.8.0",                   # Azure OpenAI 接続用クライアント (v3.x)
    "httpx2==2.12.0",                  # HTTP/2 多重化非同期通信基盤
    "h2==4.4.1",                       # HTTP/2 プロトコル実装
    "openpyxl==3.1.5",                 # Excel (.xlsx) 読込
    "xlrd==2.0.2",                     # 旧形式 Excel (.xls) 読込
    "python-calamine==0.6.2",          # 高速 Excel 解析エンジン (Rust製)
    "tabulate==0.10.0",                # DataFrame の Markdown テーブル変換
    "python-pptx==1.0.2",              # PowerPoint (.pptx) 物理ファイル生成
    "playwright==1.61.0"               # PowerPoint 幾何学バリデーション用 Headless ブラウザ
]
```

---

## 4. 完全セットアップ & 環境変数リファレンス

### ステップ 1: リポジトリのクローン & 仮想環境の構築

```bash
# リポジトリをクローン
git clone <repository_url>
cd GP-chat_With_Streamlit

# Python 仮想環境の作成
python -m venv env

# 仮想環境の有効化
# 【PowerShell (Windows)】:
.\env\Scripts\Activate.ps1
# 【コマンドプロンプト (Windows)】:
.\env\Scripts\activate.bat
# 【macOS / Linux】:
source env/bin/activate
```

### ステップ 2: パッケージのインストール & Playwright セットアップ

```bash
# pip およびビルドツールの更新
python -m pip install --upgrade pip setuptools wheel

# editable モードでパッケージをインストール
pip install -e .

# Playwright 用 Chromium ブラウザのインストール (PowerPointバリデーションに必須)
playwright install chromium
```

> [!TIP]
> Windows 環境では、ルート直下の **`install.bat`** をダブルクリックするだけで仮想環境の有効化、ビルドツールの更新、および依存パッケージのインストールを全自動で実行できます。

### ステップ 3: 環境変数（`.env`）の設定

`env/` ディレクトリ配下に `.env` ファイルを作成します。複数環境（開発用・本番用など）を作成してサイドバーから動的に切り替えることができます。

```bash
# env ディレクトリを作成し、サンプルをコピー
mkdir env
cp sample_of.env env/default.env
```

#### 📋 環境変数完全リファレンス表

| 環境変数名 | 必須 / 任意 | デフォルト値 | 設定値の例 | 説明 |
| :--- | :---: | :--- | :--- | :--- |
| **`GCP_PROJECT_ID`** | **必須** | - | `your-gcp-project-id` | Google Cloud プロジェクト ID。 |
| **`GCP_LOCATION`** | **必須** | `global` | `global`, `us-central1`, `asia-northeast1` | Vertex AI の Gemini が稼働するリージョン。 |
| **`GOOGLE_APPLICATION_CREDENTIALS`** | **必須** (ローカル時) | - | `C:/keys/service-account.json` | GCP サービスアカウントキー (JSON) の絶対パス。 |
| **`GEMINI_MODEL_ID`** | 任意 | `gemini-3.8-flash` | `gemini-3.8-flash`, `gemini-3.7-flash` | UI 起動時のデフォルトモデル ID。 |
| **`MAX_TOKEN`** | 任意 | `65536` | `65536`, `8192` | LLM が生成する最大出力トークン数。 |
| **`AZURE_OPENAI_ENDPOINT`** | 任意 (Azure利用時) | - | `https://xxxx.openai.azure.com/` | Azure OpenAI サービスのエンドポイント URL。 |
| **`AZURE_OPENAI_API_KEY`** | 任意 (Azure利用時) | - | `32桁の16進数キー` | Azure OpenAI API キー。 |
| **`AZURE_OPENAI_GPT54_DEPLOYMENT`** | 任意 (Azure利用時) | - | `gpt-54-prod` | Azure 側の標準フォールバック用デプロイメント名。 |
| **`AZURE_OPENAI_CODEX_DEPLOYMENT`** | 任意 (Codex利用時) | `GPT54設定値を流用` | `gpt-5.3-codex-deployment` | `gpt-5.3-codex` 選択時に使用される専用デプロイメント名。 |
| **`AZURE_OPENAI_SOL_DEPLOYMENT`** | 任意 (推論モデル時) | `GPT54設定値を流用` | `gpt-5.6-sol` | `gpt-5.6` 選択時に使用される専用デプロイメント名。 |
| **`AZURE_OPENAI_GPT6_DEPLOYMENT`** | 任意 (GPT-6利用時) | `GPT54設定値を流用` | `gpt-6-astra` | `gpt-6` 選択時に使用される専用デプロイメント名。 |
| **`AZURE_DEEP_MAX_CONCURRENCY`** | 任意 | `3` | `3`, `5` | GPT-5.6 / GPT-6 並行サブタスクの最大同時実行数。 |
| **`AZURE_OPENAI_ENV_FILE`** | 任意 | - | `C:/path/to/azure.env` | Azure 設定を外部の別 `.env` から読込む場合のパス。 |
| **`GP_CHAT_CLOUD_LOGGING_ENABLED`**| 任意 | `true` | `true` / `false` | GCP Cloud Logging への監査ログ送信の有効化フラグ。 |
| **`GP_CHAT_LOG_SERVICE_NAME`** | 任意 | `gp-chat-app` | `gp-chat-production` | Cloud Logging に記録されるサービス識別名。 |

#### 🔑 Google Cloud IAM・サービスアカウントの作成手順
1. [Google Cloud Console](https://console.cloud.google.com/) にアクセスし、プロジェクトを選択。
2. 「API とサービス」>「ライブラリ」から **「Vertex AI API」** を検索して有効化。
3. 「IAM と管理」>「サービス アカウント」に移動し、**「＋サービス アカウントを作成」** をクリック。
4. ロール付与画面で以下のロールを付与：
   - **`Vertex AI ユーザー`** (`roles/aiplatform.user`) - 必須
   - **`ログ書き込み`** (`roles/logging.logWriter`) - Cloud Logging 有効時
5. 作成したサービスアカウントの「キー」タブから「新しい鍵を作成」>「JSON」を選択してダウンロード。
6. ダウンロードした JSON ファイルのパスを `.env` の `GOOGLE_APPLICATION_CREDENTIALS` に設定。

### ステップ 4: 初回起動時のメールアドレス設定 (`mail.txt`)
- アプリ起動時、ルート直下に `mail.txt` が存在するか、および `user@domain` 形式のメールアドレスが含まれているかを判定します。
- 未設定または不正な場合、画面に入力フォームが表示され、有効なアドレスを入力して「保存して続行」を押すまでアプリの操作がブロックされます。
- 入力されたアドレスは `mail.txt` に保存され、GCP Cloud Logging にログ送信する際の `user_email`（監査ログメタデータ）として使用されます。

---

## 5. アプリケーションの起動と運用

### 🚀 起動方法一覧

```bash
# 【方法 1: Windows ワンクリック起動 (推奨)】
# ルート直下の START.bat をダブルクリック (仮想環境有効化と起動を自動実行)

# 【方法 2: CLI コマンド起動】
gp-chat

# 【方法 3: Streamlit コマンド直接起動】
streamlit run src/gp_chat/main.py
```

起動後、デフォルトブラウザで `http://localhost:8501` が自動的に開きます。

### ⚙️ 運用・一時ファイル管理
- **`temp_workspace/<Session-UUID>/`**:
  - セッションごとに一意の UUID ディレクトリが生成され、アップロードファイルや生成途中のグラフ画像が隔離保存されます。
  - アプリ終了時やセッション破棄時に `data_manager.cleanup_temp_workspace()` によって安全に解放されます。
- **`chat_log/*.json`**:
  - 会話が 1 ターン完了するごとに、自動的にタイムスタンプ付きのファイル名（`yymmdd_タイトル.json`）で保存されます。
- **`slide_data/<タイトル>/`**:
  - レポート機能で生成された HTML スライド、PDF ファイル、および PowerPoint ファイルが永続保存されます。

---

## 6. UI / UX 機能仕様 & 画面詳細リファレンス

### ① 初回起動画面: システムプロンプト設定
チャットが開始される前（`system_role_defined=False` の初期状態）に表示されます。

```text
┌─────────────────────────────────────────────────────────────┐
│ ⚙️ AIの役割設定 (System Role)                                │
├─────────────────────────────────────────────────────────────┤
│ プリセット選択: [ エンジニア向けアシスタント ▼ ]            │
│                                                             │
│ システムプロンプト (編集可能):                              │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ You are Gemini, a helpful and versatile AI assistant... │ │
│ │ ...                                                     │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ 保存するプロンプト名: [ my-custom-prompt ]                  │
│                                                             │
│ [ 🚀 このまま実行 (追加保存無し) ]    [ 💾 保存して実行 ]   │
└─────────────────────────────────────────────────────────────┘
```

- **「このまま実行(追加保存無し)」**: プロンプトをセッションに一時適用し、即座にチャット画面へ遷移します。
- **「保存して実行」**: 入力されたプロンプト名で `prompts/prompts.yaml` にプリセットを追加保存して開始します。同名のプロンプト名が既に存在する場合は、`st.dialog` による上書き確認ダイアログが表示され、ユーザーの明示的な同意を得てから上書きします。

### ② サイドバー設定 & 連動・排他ロックマトリクス
サイドバーの設定コントロールは、機能間の競合や不正な組み合わせを防止するため、以下の**厳格な連動ロック仕様**に基づいて動的に無効化・強制設定されます。

| 設定項目 | 選択値 / 機能概要 | 連動・ロック仕様マトリクス |
| :--- | :--- | :--- |
| **Environment** | `.env` ファイルの動的切替 | 生成中 (`is_generating=True`) は無効化。 |
| **Target Model** | モデル選択（`gemini-3.8-flash`, `gpt-6` 等9モデル） | `gpt-5.3-codex` / `gpt-5.6` / `gpt-6` 選択時は最初から Azure OpenAI に直接接続（GCPバイパス）。 |
| **Thinking Level** | `high` / `medium` / `low` / `deep` (推論レベル) | 「徹底調査」または「レポート機能 (pdf/pptx)」が ON の時は **強制的に `high` に固定され UI がロック**。生成中は無効化。 |
| **Web検索** | Google Search Grounding の ON/OFF | 「徹底調査」が ON の時は **強制的に ON に固定され UI がロック**。生成中は無効化。 |
| **徹底調査** | `More Research` 自律反復検索 | 「Thinking Level: deep」または「レポート機能 (pdf/pptx)」が ON の時は **選択不可（UI ロック）**。生成中は無効化。 |
| **レポート機能（pdf）** | HTML/PDFスライド自動生成 | 「徹底調査」「Thinking Level: deep」「レポート機能(pptx)」のいずれかが ON の時は **選択不可（UI ロック）**。ON 時は Thinking Level が `high` に固定。 |
| **レポート機能（pptx）** | PowerPointネイティブ自動生成 | 「徹底調査」「Thinking Level: deep」「レポート機能(pdf)」のいずれかが ON の時は **選択不可（UI ロック）**。ON 時は Thinking Level が `high` に固定。 |
| **グラフ描画・データ分析** | Pythonコード自動実行 (`auto_plot`) | ON の時のみ、応答内の Python コードブロックをローカル実行してグラフを表示。生成中は無効化。 |
| **履歴ファイルを選択** | 保存された JSON から会話を再開 | 読込実行時に添付キューや一時ウィジェットキーを自動クリーンアップして再構築。生成中は無効化。 |

- **思考プロセスの折りたたみ表示 (`st.expander`)**:
  - 生成中の一時表示に加え、回答完了後もメッセージ上部に `🧠 思考プロセス (Thinking Process)` の折りたたみアコーディオンを常時表示。クリックで展開してタスク分割や並行収集材料、推論ログを振り返ることが可能です。

### ③ マルチスロット Canvas コードエディタ
- 最大 **40 スロット** の独立した Ace Editor（Python構文ハイライト、Monokaiテーマ）が常時利用可能。
- **動的 ON 化**: 1番目の Canvas は初期状態で送信 OFF ですが、キー入力やファイル読込を検知すると自動的に「AIへ送信」が ON に切り替わります。
- **「全てを常にAIへ送る」トグル**: ON の場合、メッセージ送信後も各 Canvas の送信トグルが OFF に戻らず維持されます。
- **インジェクション仕様**: チャット送信時、有効な Canvas のコードは `[Canvas-N]\n```python\nコード...\n``` という形式でプロンプトの先頭に自動挿入されます。
- **ツールボタン**:
  - **「検証」**: Pylint をバックグラウンドで実行し、構文エラー（SyntaxError）を即座に検出・警告表示。
  - **「レビュー」**: Canvas のコードをレビューするための定型プロンプトをチャット入力欄に自動セット。
  - **「クリア」**: 当該 Canvas の内容を初期状態（`# コードはここに \n`）にリセット。

### ④ 会話履歴管理・分岐・中断リカバリー
- **会話の分岐（✂️ この会話から分岐）**:
  - 過去のアシスタントメッセージ横に配置されたハサミボタンを押すと、その発言時点までの履歴を切り出した上で、新しいファイル名（`yymmdd_元タイトル-02.json` など、末尾連番）を自動採番して保存し、セッションを切り替えてチャットを再開します。累積トークン数もその時点までの合計値に再計算されます。
- **入力中断リカバリーとドラフト復元**:
  - ユーザーがメッセージを送信した後に生成が意図せず中断された（最後のメッセージがユーザーロールのまま生成フラグが降りている）状態を自動検知します。
  - 最後の未処理ユーザー入力を履歴から切り離し、チャット入力欄に「ドラフト」として復元表示。ユーザーは「再送信」または「破棄」を即座に選択できます。

### ⑤ セッション状態（Session State）クリーンアップフロー
履歴ロード時（ローカル読込・アップロード）および「会話履歴をリセット」押下時は、旧セッションの残留による誤作動を防ぐため、以下の**6段階クリーンアップ**を厳密に実行します。
1. **添付ファイルキューの全削除**: `uploaded_file_queue` と `clipboard_queue` を空リスト `[]` に初期化。
2. **ファイルアップローダーUIのリセット**: `file_uploader_key` をインクリメントし、Streamlit 内部のアップロードキャッシュを強制フラッシュ。
3. **Canvas 送信フラグの再構築**:
   - `always_send_all_canvases` が ON の場合は全スロットを ON に設定。
   - OFF の場合は、履歴データを走査し、空またはデフォルトコード以外の**意味のあるコードが記述されている Canvas のみ**を ON、その他を OFF に自動設定。
4. **widget 一時ステートの消去**: session_state 内の `ace_`, `up_`, `cvs_tog_` で始まるすべてのキーを `del`。
5. **widget 巻き戻り防止フラグの適用**: `_canvas_reset_pending = True` をセットし、次フレームで Ace Editor の値が旧値に巻き戻ることを防止。
6. **レポートフォルダのクリア**: ロードされた履歴にレポートフォルダ情報がない場合は `current_report_folder` をクリア。

---

## 7. 5大特化型エージェント詳細仕様 & アルゴリズム

### ① Deep Reasoning（思考レベル: deep）
「多角的立案 → 厳格な自己批判 → 最終統合」のマルチターン思考パイプライン（`reasoning_agent.py`）。

```text
[ユーザー課題]
   │
   ▼ (Phase 1: Brainstorming)
┌─────────────────────────────────────────────────────────────┐
│ 異なるアプローチを3案立案 (temperature=0.4, JSON構造)       │
│ {"approaches": [{"name": "...", "description": "..."}]}     │
└─────────────────────────────────────────────────────────────┘
   │
   ▼ (Phase 2: Exploration & Critique)
┌─────────────────────────────────────────────────────────────┐
│ 3つのアプローチに対してあえて厳しく自己批判 (temperature=0.2) │
│ - 潜在的リスク、論理の飛躍、エッジケースでの破綻を徹底抽出  │
└─────────────────────────────────────────────────────────────┘
   │
   ▼ (Phase 3: Integration)
┌─────────────────────────────────────────────────────────────┐
│ 自己批判の内容を synthesis_instruction にマージ             │
│ 最も洗練された最適解をストリーミング生成 (temperature=0.3)   │
└─────────────────────────────────────────────────────────────┘
```

### ② More Research（徹底調査モード）
Google Search Grounding を自律的に反復する ReAct 型深掘り調査ループ（`research_agent.py`）。

```text
[調査テーマ]
   │
   ▼ (最大3サイクルの反復ループ)
┌─────────────────────────────────────────────────────────────┐
│ 【評価プロンプト】 (temperature=0.2, JSON形式)              │
│ {"status": "sufficient" or "needs_more_info",               │
│  "next_queries": ["クエリ1", "クエリ2"], "reasoning": "..."}│
└─────────────────────────────────────────────────────────────┘
   │
   ├─► [needs_more_info]: 指定クエリで Google 検索実行 ──┐
   │                      事実要約を蓄積してループ継続   │
   │                                                     │
   ▼ (ループ完了 または status="sufficient")             │
┌─────────────────────────────────────────────────────────────┘
│ 【Synthesis フェーズ】 (temperature=0.3)
│ 収集された全検索事実と「一次情報優先ルール」を統合し、
│ 包括的な調査レポートをストリーミング出力
└─────────────────────────────────────────────────────────────┐
```
- **堅牢化処理**: AIが出力した文字列から Markdown コードブロック（````json` 等）を除去し、正規表現で `{` と `}` の間を切り出してパース。パース失敗時は安全にループを終了して統合フェーズへ進みます。

### ③ Auto-Plot（データ分析・グラフ描画 & 自己修復）
Python コードのローカル安全実行と、エラー時の自己修復ループ（`execution_engine.py`, `code_agent.py`）。

1. **コードブロック検出 & 環境構築**:
   - 応答内の最新の ```python ... ``` ブロックを抽出。
   - OSを自動判別し、matplotlib の日本語フォントを設定：
     - Windows: `Meiryo`
     - macOS: `Hiragino Sans`
     - Linux: `Noto Sans CJK JP`
2. **実行 & グラフキャプチャ**:
   - `matplotlib.use('Agg')` で実行し、`pd`, `plt`, `np`, `io`, `files`, `canvas_1`... をスコープに注入した `exec()` を実行。
   - 実行後、`plt.get_fignums()` で生成されたすべての Figure を PNG 形式で回収し、Base64 エンコードしてチャットにインライン表示。
3. **自己修復ループ (Auto-Fix)**:
   - 実行出力に `Traceback (most recent call last):` が含まれる場合、エラーログをフィードバックプロンプトに埋め込んで AI に修正コードを要求。
   - **最大 2 回** までこの修復・再実行ループを自動反復。

### ④ Report PDF（HTML/PDF スライド自動生成）
会話履歴からプレゼンテーションスライドを HTML 化し、Headless ブラウザで PDF 出力（`report_agent.py`）。

1. **HTML プレゼンテーション構築**:
   - `prompts.yaml` の `report_pdf` テンプレートに基づき、A4横向き、カードUI、Font Awesome アイコン、改ページ制御（`break-after: page`）を含む HTML を生成。
   - `slide_data/<タイトル>/<連番>.html` に保存。
2. **Headless ブラウザによる PDF 印刷**:
   - 以下の優先順位でローカルのブラウザ実行ファイルを自動探索：
     1. `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`
     2. `C:\Program Files\Microsoft\Edge\Application\msedge.exe`
     3. `C:\Program Files\Google\Chrome\Application\chrome.exe`
     4. `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`
   - `subprocess.run` を用いて Headless 印刷を実行：
     ```bash
     msedge.exe --headless=new --disable-gpu --allow-file-access-from-files --run-all-compositor-stages-before-draw --virtual-time-budget=5000 --print-to-pdf=<PDF保存パス> <HTMLファイルURI>
     ```

### ⑤ Report PPTX（PowerPoint ネイティブ生成）
Marp の設計思想を取り入れた、PowerPoint ファイル（`.pptx`）の全自動物理生成パイプライン（`pptx_agent.py`）。

```text
┌─────────────────────────────────────────────────────────────┐
│ 【第1層: 構造化 JSON 生成】 (temperature=0.2)               │
│ - PresentationDSLSchema (タイトル, スライド構成, 配色テーマ)│
│ - format.pptx のレイアウト・プレースホルダー idx 動的注入   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 【第2層 & 第3層: 幾何学バリデーション & 要約自己修復】      │
│ - 各スライド座標から HTML モック生成                        │
│ - Playwright (Chromium) レンダリング                        │
│ - スクロール溢れ判定 (scrollHeight > clientHeight)          │
│ - 溢れ検出時: Gemini で文字数を 30~50% 削減要約 (最大3回)   │
│ - 上限到達時フォールバック: フォントサイズ -2pt 強制縮小    │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 【画像処理パイプライン】                                    │
│ - AI画像生成: gemini-3.1-flash-lite-image / imagen-3 (最大4枚)
│ - 添付画像トリミング: Gemini でバウンディングボックス検知   │
│   (CropAreaSchema) ──▶ Pillow で物理トリミング              │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 【第4層: 物理 PPTX 生成 & テンプレート後処理】              │
│ - python-pptx でプレースホルダー idx にコンテンツ描画      │
│ - 未使用プレースホルダー自動削除                            │
│ - 表紙タイトル書換、2枚目見本スライド削除、裏表紙の末尾移動 │
└─────────────────────────────────────────────────────────────┘
```

- **Marp設計思想の統合**:
  - **1スライド1アイデア原則**: 1枚のスライドに複数の主題を混在させない。
  - **リスト最大6行制限**: 箇条書きは最大6行とし、認知負荷を抑制。
  - **動的カラーテーマ制御**: `color_theme`（corporate, creative, warm, cool, light, dark）および `accent_color_hex`（重要KPI・矢印等の強調色）を動的に指示。
  - **フラットモダンデザイン**: 図形の枠線を極小化/廃止し、背景とコントラスト比の高い配色を採用。

---

## 8. LLMルーティング・高可用性 & 障害耐性仕様

### ① 二重化リクエスト制御 (Vertex AI)
一時的な負荷やレート制限に耐えるため、2つのクライアントを使い分けます（`llm_router.py`）。
- **Standard クライアント**: リトライ回数を1回に抑えた通常時クライアント。
- **Priority クライアント**: 以下の優先制御ヘッダーを注入した優先クライアント。
  - `X-Vertex-AI-LLM-Request-Type: shared`
  - `X-Vertex-AI-LLM-Shared-Request-Type: priority`
- **リトライポリシー**: 対象ステータスコード（`408`, `429`, `500`, `502`, `503`, `504`）を検知すると、Priority クライアントへ切り替え、指数バックオフ＋ランダム Jitter（待ち時間: 2.0s, 4.0s, 8.0s + 0~1秒）で最大 3 回リトライを実行します。

### ② Azure OpenAI 自動フォールバック
- GCP 側の全リトライが失敗した、または致命的な API エラーが発生した場合に作動。
- **作動条件**: まだチャット応答の文字出力が 1 文字も始まっていないこと (`visible_output_started=False`)、および Azure 接続設定が有効であること。
- **処理**: リトライ用にディープコピーしておいたコンテキストスナップショットを用いて Azure OpenAI API に切り替えてリクエストを再送し、ユーザーに応答をシームレスに継続します。

### ③ Azure 直接接続 (GCP バイパス)
- UI のモデル選択で `gpt-5.3-codex`、`gpt-5.6`、または `gpt-6` が選択された場合、Vertex AI へのリクエストを行わず、最初から Azure OpenAI へ直接接続して応答を生成します。

### ④ GCP Cloud Logging 最適化
- Azure 直接接続時および Azure フォールバックが機能した際は、GCP 側の権限エラー（403 Forbidden）による無駄なエラーログの発生を防ぐため、Cloud Logging 送信処理を自動的にスキップします。

### ⑤ 開発用疑似エラー注入 (Fault Injection)
- `dev/fault_injection.local.toml` を配置することで、GCP 呼び出し時に意図的に 429 エラーや 500 エラーを発生させ、Azure フォールバックやリトライの挙動を安全にシミュレーション・テストできます（`azure_fault_injection.py`）。

### ⑥ GPT-5.6 / GPT-6 専用 HTTPX2並行ハイブリッドオーケストレーター
- `gpt-5.6` または `gpt-6` を高推論モード（`high`/`deep`）で実行する際、中間プロキシの無通信タイムアウト（504）を回避するため、以下の自律3層処理を実行します。
  1. **Phase 1 (タスク分解)**: 軽量設定で課題を独立した並行サブタスクに分解（単一タスク時は Phase 3 へ Early Exit）。
  2. **Phase 2 (HTTP/2 並行回収)**: `httpx2` による HTTP/2 多重化接続上でサブタスクを並行実行し材料を高速回収。
  3. **Phase 3 (思考ストリーミング統合推論)**: 収集材料を統合し、思考ログをリアルタイム逐次描画しながら高推論を実行。

---

## 9. マルチモーダル・ファイル解析 & コンテキスト構築仕様

アップロードされたファイルは、`utils.parse_file()` および `utils.build_materialized_chat_context()` によって以下の形式に変換され、LLM API へ送信されます。

```text
添付ファイル
 │
 ├── 画像 (.png, .jpg, .jpeg, .gif, .bmp)
 │    ├─ GCP: 画像バイナリを Part として直接送信
 │    └─ Azure: Base64 エンコードし data:image/...;base64,... 形式で送信
 │
 ├── PDF (.pdf)
 │    ├─ GCP: PDF バイナリを Part として直接送信
 │    └─ Azure: 未サポートのため AzureContextBuildError をスローしフォールバック抑止
 │
 ├── Word (.docx)
 │    └─ python-docx で全段落テキスト抽出 ──▶ [Attached Document: ファイル名]\n内容...
 │
 ├── Excel (.xlsx, .xlsm, .xls)
 │    └─ Calamine/openpyxl で読込 ──▶ ### Sheet: シート名 の下に Markdown 表形式化
 │
 ├── PowerPoint (.ppt, .pptx)
 │    └─ Windows COM (pywin32) でバックグラウンド起動 ──▶ 各スライドを PNG 画像群として抽出
 │       (※ハッシュ値による ppt_conversion_cache キャッシュ機能付き)
 │
 └── ソースコード / テキスト (.py, .js, .md, .txt, .json, .csv, .yaml 等)
      └─ UTF-8 試行 ──▶ 失敗時 CP932 (Shift-JIS) 試行 ──▶ 失敗時 replace デコード
```

---

## 10. Session State（セッション状態変数）完全リファレンス

アプリケーションの全動作を司る `st.session_state` の完全リファレンスです。

| 変数名 | 型 | 初期値 | 役割・用途 |
| :--- | :---: | :--- | :--- |
| `messages` | `list[dict]` | `[]` | 会話履歴の辞書リスト（ロール、コンテンツ、Grounding情報、トークン情報、`thought_log` 永続化等）。 |
| `system_role_defined` | `bool` | `False` | システムプロンプトが確定してチャット画面に移行したかどうかのフラグ。 |
| `current_model_id` | `str` | `gemini-3.8-flash` | 現在選択されているターゲットモデル ID。 |
| `reasoning_effort` | `str` | `high` | 現在の Thinking Level (`high`, `medium`, `low`, `deep`)。 |
| `enable_google_search` | `bool` | `True` | Google Search Grounding の有効化フラグ。 |
| `enable_more_research` | `bool` | `False` | 徹底調査モード（More Research）の有効化フラグ。 |
| `report_mode_pdf` | `bool` | `False` | レポート機能（PDF）の有効化フラグ。 |
| `report_mode_pptx` | `bool` | `False` | レポート機能（PowerPoint）の有効化フラグ。 |
| `auto_plot_enabled` | `bool` | `False` | Pythonコード自動実行 & グラフ描画モードの有効化フラグ。 |
| `auto_save_enabled` | `bool` | `True` | 会話履歴の自動保存フラグ。 |
| `python_canvases` | `list[str]` | `["# コードはここに \n"]` | 各 Canvas に入力されている Python コード文字列のリスト。 |
| `canvas_enabled` | `list[bool]`| `[False]` | 各 Canvas の「AIへ送信」トグルの有効状態リスト。 |
| `always_send_all_canvases`| `bool` | `False` | 送信後も Canvas 送信トグルを OFF に戻さず維持するフラグ。 |
| `canvas_key_counter` | `int` | `0` | 全 Canvas の widget key 更新用カウンター（リセット時にインクリメント）。 |
| `toggle_keys` | `list[int]` | `[0]` | 各 Canvas トグルの widget key インクリメント用カウンターリスト。 |
| `uploaded_file_queue` | `list` | `[]` | 送信待ちの Streamlit アップロードファイルオブジェクトのリスト。 |
| `clipboard_queue` | `list` | `[]` | クリップボードから取得した一時画像オブジェクトのリスト。 |
| `current_chat_filename` | `str` | `None` | 現在開いているチャット履歴 JSON のローカルファイル名。 |
| `current_report_folder` | `str` | `None` | 現在のチャットに紐づくレポート保存フォルダ名。 |
| `total_usage` | `dict` | `{"input_tokens": 0...}`| セッション内の累計トークン使用量辞書。 |
| `last_usage_info` | `dict` | `None` | 直近の API 呼び出しにおけるトークン使用量詳細辞書。 |
| `is_generating` | `bool` | `False` | 現在 AI が応答を生成中かどうかのフラグ（UIロック制御用）。 |
| `stop_generation` | `bool` | `False` | ユーザーが「Stop」ボタンを押した際の中断要求フラグ。 |
| `debug_logs` | `list[dict]`| `[]` | 直近の API 通信デバッグログ（ステータスコード、ルーティング経路等）。 |
| `_canvas_reset_pending` | `bool` | `False` | 履歴ロード直後のレンダリングループで widget 巻き戻りを防止する内部フラグ。 |

---

## 11. 開発・テスト・トラブルシューティングガイド

### ① 開発用疑似エラー注入テストの手順
1. プロジェクトルートに `dev/fault_injection.local.toml` を作成。
2. 以下の設定を記述してアプリを起動：
   ```toml
   [gcp_fault]
   enabled = true
   status_code = 429
   error_message = "Resource has been exhausted (rate limit simulated)."
   ```
3. チャットでメッセージを送信し、ログおよび UI 上で Priority クライアントへのリトライ → Azure OpenAI への自動フォールバックが正常に行われるかを確認。

### ② よくあるエラーと対処法

| 現象 / エラーメッセージ | 主な原因 | 対処法 |
| :--- | :--- | :--- |
| **`Error: Environment variable 'GCP_PROJECT_ID' is not set.`** | `.env` ファイルが配置されていないか、読み込まれていない。 | `env/` ディレクトリ内に `.env` ファイルを配置し、サイドバーで正しく選択されているか確認。 |
| **`429 Resource Exhausted`** | Vertex AI の API レート制限超過。 | 自動リトライおよび Azure フォールバックが作動します。頻発する場合は GCP クォータの引き上げを申請。 |
| **`PowerPoint COM Error / pywintypes.com_error`** | PowerPoint がバックグラウンドでハングしているか、非Windows環境。 | タスクマネージャーで `POWERPNT.EXE` を強制終了。macOS/Linux では PPTX の直接添付は非対応（PDF等に変換して添付）。 |
| **`Playwright Browser Closed / Executable not found`** | Playwright の Chromium ブラウザが未インストール。 | 仮想環境内で `playwright install chromium` を実行。 |
| **`文字化け (グラフの日本語が豆腐 □ になる)`** | OS に対応する日本語フォントが見つからない。 | Windows では `Meiryo`、Linux では `fonts-noto-cjk` パッケージがインストールされているか確認。 |

---

## 12. ライセンス & 作者情報

### 📄 ライセンス
本ソフトウェアは **[Apache License 2.0](LICENSE)** に基づいて公開・提供されています。商用利用、改変、再配布が可能です。

### 👤 作者情報
- **開発者**: **Yoichi-1984**
- **連絡先**: [yoichi.1984.engineer@gmail.com](mailto:yoichi.1984.engineer@gmail.com)
- **GitHub**: [yoichi-1984](https://github.com/yoichi-1984)
- **技術解説記事**: [Note 記事一覧](https://note.com/yoichi_1984xx/n/n3c95602b011c)

