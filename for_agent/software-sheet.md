# GP-Chat システム仕様書 (software-sheet.md)

本ドキュメントは、GCP (Vertex AI) および Azure OpenAI などの大規模言語モデル（LLM）APIを活用した、Streamlitベースの多機能チャットアプリケーション「GP-Chat」の仕様書です。本ドキュメントのみを参照することで、システムの全体構造、UI動作、内部アルゴリズム、コンテキスト管理、例外処理方針を完全に理解し、本アプリケーションを再構築できる詳細な設計情報を記述しています。

---

## 1. システム概要
GP-Chatは、対話型AIチャットを基盤とし、マルチモーダルなドキュメント分析、ローカル実行エンジンによるデータ分析とグラフ自動描画、およびヘッドレスブラウザ連携によるHTML/PDFレポートスライド自動生成機能を備えた、高度なアシスタントアプリケーションです。
GCP Vertex AIのAPIを主系（標準ルートおよび高負荷対策用の優先ルート）としつつ、自動フォールバック先および特定コーディングモデル（`gpt-5.3-codex`）の直接接続先としてAzure OpenAIを統合し、柔軟かつ堅牢な稼働安定性を有しています。

---

## 2. システムアーキテクチャとファイル構成
本システムのプログラムは主に `src/gp_chat` ディレクトリ内に配置されています。各モジュールの役割は以下の通りです。

```
gp-chat/
├── pyproject.toml              # パッケージビルド定義、依存パッケージ定義
├── requirements.txt            # ローカル環境用依存定義
├── mail.txt                    # ユーザーメールアドレス一時保存用
├── Plan.md                     # タスク計画管理用
├── AICHANGELOG.md              # 変更履歴記録用
├── dev/
│   └── fault_injection.local.toml # 疑似エラー注入・シミュレーション用設定
├── env/
│   └── *.env                   # 環境変数定義ファイル群
├── prompts/
│   └── prompts.yaml            # UI編集・永続化用システムプロンプト設定（カレント優先）
├── slide_data/
│   └── <チャットタイトル>/      # 生成されたHTML/PDFスライドの格納ディレクトリ
├── chat_log/
│   └── *.json                  # 会話履歴の自動保存・分岐データ格納ディレクトリ
├── temp_workspace/
│   └── <Session-UUID>/         # セッション固有のデータファイル一時保存ディレクトリ
└── src/
    └── gp_chat/
        ├── __init__.py
        ├── main_runner.py      # アプリのエントリーポイント。main.py を呼び出す。
        ├── main.py             # メインロジック。画面制御、チャット描画、セッション連携、モデルに応じたGCPバイパス、Azure Fallback。
        ├── sidebar.py          # UIサイドバーの描画。モデル、Thinking Level、Canvas、ファイル添付、履歴の制御。
        ├── config.py           # デフォルトセッション情報、UIテキスト、選択可能なモデル、各種定数。
        ├── config.yaml         # Canvasへのファイルロード時に許可する拡張子リストなどの設定ファイル。
        ├── prompts.yaml        # デフォルトのプロンプト定義（初回起動時にカレントディレクトリへコピーされる）。
        ├── utils.py            # Word・Excel・PPT・PDF等のファイルパース処理、プロンプトのロード、Gemini用コンテキストの構築。
        ├── state_manager.py    # 会話履歴の自動保存、手動再開、中断リカバリー、セッションクリーンアップ、デバッグログの収集。
        ├── data_manager.py     # 一時ファイルやアップロードファイルをセッションIDごとに管理（ポインタ位置の保護機能付き）。
        ├── llm_router.py       # Vertex AI クライアントの初期化。標準/優先ルート制御、API 429等のエラー発生時の自動リトライ。
        ├── execution_engine.py # セッション内スコープにおけるPythonコードの実行、標準出力の回収、描画されたグラフのキャプチャ。
        ├── code_agent.py       # AIが生成したコードの実行を監視し、エラー時にAIへ自己修復を依頼するループ制御。
        ├── reasoning_agent.py  # 「アプローチ立案 → 自己批判(Critique) → 最終結論」を行う思考プロセス特化エージェント。
        ├── research_agent.py   # 情報過不足を評価しながらGoogle検索を自律反復する徹底調査（ReAct）エージェント。
        ├── report_agent.py     # 会話履歴からHTMLプレゼンを構築し、ヘッドレスブラウザでPDFに自動変換して保存するエージェント。
        ├── azure_runtime.py    # Azure OpenAI クライアントの初期化とランタイム管理（Codex専用デプロイメント等のロード）。
        ├── azure_context_builder.py # Azure APIに適した形式のコンテキストオブジェクトの構築（PDF非サポート、画像base64化）。
        ├── azure_supervisor_helpers.py # GCP側のエラー状態を検知し、Azure側への切り替え要否を判定するスーパーバイザヘルパー。
        ├── azure_fault_injection.py # Azure fallback挙動をテストするための疑似エラー注入用モジュール。
        ├── azure_common_types.py # Azure環境下で共通して利用されるデータクラスの定義。
        ├── azure_*_agent.py    # 主系に対応するAzure用の各種特化型エージェント（Code, Reasoning, Research, Report, Normal）。
        ├── pptx_agent.py       # PowerPointネイティブプレゼンテーション自動生成、Playwright幾何学バリデーション、自己修復ループ。
        ├── format.pptx         # PowerPointスライドレポート用のデザインテンプレート。
        └── cloud_logging_utils.py # GCP Cloud Logging へのログ送信ユーティリティ。
```

---

## 3. 動作前提条件とシステム要件

### ① 実行環境
* **Pythonバージョン**: `Python >= 3.11`
* **動作OS**: Windows / macOS / Linux (PowerPoint/PDFエクスポートの一部機能はWindows OSかつEdge/Chrome/PowerPointのインストールが必要)
* **パッケージング**: `pyproject.toml` に基づきwheel化してビルド可能。

### ② 主要な依存パッケージ
- `streamlit==1.52.2` (WebUIフレームワーク)
- `google-genai==2.4.0` (Vertex AI / Gemini API 連携)
- `google-auth==2.53.0`
- `google-cloud-logging==3.15.0` (GCP Cloud Logging 送信用)
- `openai==2.30.0` (Azure OpenAI 接続用)
- `streamlit-ace==0.1.1` (コードエディタウィジェット)
- `python-docx==1.2.0` (Word文書テキスト抽出)
- `pywin32==311` (PowerPointのCOM連携・PNGエクスポート)
- `pandas==2.3.3`, `openpyxl>=3.1.2`, `python-calamine>=0.2.0` (ExcelのMarkdown変換・データ分析)
- `matplotlib==3.10.8` (ローカルグラフ描画)
- `pylint==4.0.4` (Canvasコード検証)
- `python-pptx>=1.0.2` (PowerPoint物理スライド物理生成)
- `playwright>=1.49.0` (PowerPoint幾何学バリデーション用ブラウザ)

### ③ 環境変数設定
`./env/` 配下の `.env` ファイルに以下の環境変数が設定されていること。サイドバーから読み込む `.env` ファイルを切り替えることができる。
* `GCP_PROJECT_ID` (GCP プロジェクトID)
* `GCP_LOCATION` (Vertex AI リージョン。例: us-central1)
* `GEMINI_MODEL_ID` (デフォルトモデル。例: gemini-3.5-flash)
* `AZURE_OPENAI_API_KEY` (Azure 接続用キー)
* `AZURE_OPENAI_ENDPOINT` (Azure エンドポイントURL)
* `AZURE_OPENAI_GPT54_DEPLOYMENT` (標準Azure用デプロイメント名)
* `AZURE_OPENAI_CODEX_DEPLOYMENT` (Codex専用デプロイメント名。未指定時はGPT54用の設定を流用)

---

## 4. UIレイアウトと動作仕様

### ① 起動初期処理とメールアドレス設定
- アプリ起動時、カレントディレクトリに `mail.txt` が存在し、有効なメールアドレス（`user@domain` 形式）が記述されているかを判定する。
- 存在しない、または形式が不正な場合は、メイン画面にメールアドレス入力フォームを表示し、ユーザーに入力を強制する（入力して「保存して続行」を押すまでアプリの実行をブロックする）。入力されたアドレスは `mail.txt` に保存され、GCP Cloud Logging にログを送信する際の `user_email` として利用される。

### ② システムプロンプト設定（初回起動時）
- チャット開始前（`system_role_defined` が False の状態）に表示される。
- ルート直下の `prompts/prompts.yaml` からプロンプトのプリセット（デフォルトで「エンジニア向け」「翻訳アシスタント」など）をセレクトボックスに表示し、選択可能にする。
- プロンプト内容はテキストエリアで動的に編集可能であり、以下のボタンで開始・保存を実行する。
  - **「このまま実行(追加保存無し)」**: 赤背景白文字のボタン。プロンプト内容を YAML に保存せず、一時的にセッションに適用してチャット画面に移行する。
  - **「保存して実行」**: 白枠黒文字のボタン。「保存するプロンプト名」に入力された名前で `prompts/prompts.yaml` にプリセットを追加保存し、チャットに移行する。プロンプト名が空欄の場合は警告を表示する。既に同名のプロンプト名が存在する場合は、`st.dialog` を用いて上書き確認ダイアログを表示し、ユーザーの同意のもとで上書きを行う。

### ③ サイドバーの設定コントロールと連動ロック仕様
サイドバーの各種設定は、特定のモードが有効な場合に競合を防ぐため相互にロック（無効化・強制設定）される。

| UI要素名 | 役割・設定値 | 連動・ロック動作 |
| :--- | :--- | :--- |
| **Environment** | `.env` ファイルの切り替え | 生成中は無効化。 |
| **Target Model** | 選択可能なモデルの切り替え（`gpt-5.3-codex` を含む） | `gpt-5.3-codex` 選択時は最初から Azure OpenAI に直接接続（GCPバイパス）。 |
| **Thinking Level** | `high` / `low` / `deep` (推論レベル) | 「徹底調査」または「レポート機能(pdf)」「レポート機能(pptx)」のいずれかが ON の時は `high` に固定され、UIがロック（無効化）される。生成中は無効化。 |
| **Web検索** | Google Search GroundingのON/OFF | 「徹底調査」が ON の時は強制的に ON になり、UIがロック（無効化）される。生成中は無効化。 |
| **徹底調査** | `More Research` モードのON/OFF | 「Thinking Level: deep」または「レポート機能(pdf)」「レポート機能(pptx)」のいずれかが ON の時は、選択できず UI がロック（無効化）される。生成中は無効化。 |
| **レポート機能（pdf）** | `Report PDF` モードのON/OFF | 「徹底調査」、「Thinking Level: deep」、「レポート機能(pptx)」のいずれかが ON の時は、選択できず UI がロック（無効化）される。ONの時はThinking Levelが `high` に固定されロックされる。生成中は無効化。 |
| **レポート機能（pptx）** | `Report PPTX` モードのON/OFF | 「徹底調査」、「Thinking Level: deep」、「レポート機能(pdf)」のいずれかが ON の時は、選択できず UI がロック（無効化）される。ONの時はThinking Levelが `high` に固定されロックされる。生成中は無効化。 |
| **グラフ描画・データ分析** | `auto_plot_enabled` のON/OFF | ON の時のみ、チャット内の Python コードブロックを自動実行する。生成中は無効化。 |
| **履歴ファイルを選択** | 保存された履歴ファイルから会話を再開 | 生成中は無効化。読込ボタン押下で履歴データに基づきCanvasトグル等をクリーンアップ再構築する。 |

### ④ 会話履歴表示と分岐機能
- 各メッセージの下部に、モデル情報やトークン使用量詳細を表示する。
- 過去のアシスタントのメッセージの横に **「✂️ この会話から分岐」** ボタンを配置する（生成中は非表示）。
- ボタンが押されると、そのメッセージ時点までの履歴を切り取った上で、新しい履歴ファイル名（`yymmdd_元タイトル-02.json` など、末尾連番）を自動生成して保存し、セッションを切り替えてチャットを再開する。累積トークン数もその時点までの合計に再計算される。

### ⑤ 入力中断リカバリーとドラフト復元
- ユーザーがメッセージを送信した後に生成が意図せず中断された（最後のメッセージがユーザーロールのまま生成フラグが降りている）状態を検知する。
- この場合、最後のユーザーメッセージを履歴から切り離し、「ドラフトテキスト」としてテキストエリアに復元表示し、ユーザーが「再送信」または「破棄」を選択できるようにする。

---

## 5. コンテキスト構築とマルチモーダルファイル添付
ユーザーが入力したテキスト、添付ファイル、Canvas（コードエディタ）の状態をマージして LLM API へ送信するコンテキストを構築する（`utils.build_materialized_chat_context` および `azure_context_builder.build_materialized_context`）。

### ① 添付ファイルのパース処理詳細
アップロード（およびクリップボード取得）されたファイルは、拡張子およびMIMEタイプに基づいて以下の処理を行う。

* **画像形式** (`.png`, `.jpg`, `.jpeg`, `.bmp`, `.gif`):
  - **GCP**: 画像バイナリを Part として直接 API 送信。
  - **Azure**: 画像バイナリを base64 エンコードし、`data:image/...;base64,...` 形式のデータURLに変換して送信。
* **PDF** (`.pdf`):
  - **GCP**: PDFバイナリを Part として直接 API 送信。
  - **Azure**: Azure Fallback 側ではPDFが未サポート（APIの制限）のため、コンテキスト構築時に `AzureContextBuildError` 例外をスローし、フォールバックを無効化する。
* **Word** (`.docx`):
  - `python-docx` を用いて、段落テキストをすべて抽出し、`[Attached Document: ファイル名]\n内容...` というテキストスニペットとして送信。
* **Excel** (`.xlsx`, `.xlsm`, `.xls`):
  - `pandas` の calamine エンジン（不在時は openpyxl）で全シートを読み込み、`### Sheet: シート名` の下に Markdown テーブル（`pandas.DataFrame.to_markdown`。`tabulate` 不在時は CSV 形式）に変換し、テキストスニペットとして送信。
* **PowerPoint** (`.ppt`, `.pptx`):
  - Windows環境かつ `pywin32` (COMオブジェクト) が動作可能な場合のみ対応。PowerPoint をバックグラウンドで起動し、各スライドを PNG 画像群としてテンポラリに保存する（値 `18` は `ppSaveAsPNG`）。
  - 各画像バイナリを画像データとして送信。処理高速化のため、ハッシュ値を用いた変換キャッシュ（`ppt_conversion_cache`）を保持する。
* **テキスト形式** (MIMEが `text/` または拡張子が `.py`, `.js`, `.md`, `.txt`, `.json`, `.csv`, `.yaml` 等):
  - UTF-8 でデコードを試みる。失敗した場合は CP932 (Windows Shift-JIS) で試み、さらに失敗した場合は errors="replace" で文字化けを許容してデコードし、``` 内に配置してテキスト送信。

### ② コードエディタ (Canvas) のインジェクション
- 起動時・履歴復元時を問わず、最大 40 個の独立した Canvas（`st_ace` 使用）が常に有効。
- 各 Canvas の「AIへ送信」が ON の場合、エディタ上のコードを `[Canvas-N]\n\`\`\`python\nコード...\n\`\`\`` という形式のテキストスニペットにして、チャット送信プロンプトの先頭に自動挿入する。
- 1番目の Canvas は何も入力されていない起動時は「AIへ送信」が OFF になるが、キー入力やファイルロードが行われると自動的に ON になる。
- 「全てを常にAIへ送る」トグルが ON の時は、送信後も「AIへ送信」トグルが自動的に OFF に戻らない。

---

## 6. 特化型エージェントのプログラムアルゴリズム

### ① Deep Reasoning（思考レベル: deep）
「アプローチ立案 → 自己批判 → 最終結論」のマルチターン・ワークフローを以下のフェーズに沿って実行する。
1. **Brainstorming フェーズ (アプローチ立案)**:
   - ユーザー要求を満たすための 3 つの異なるアプローチを AI に要求する。
   - `temperature=0.4` を設定し、`response_mime_type="application/json"` によってアプローチの名前と概要を JSON 構造 (`{"approaches": [{"name": "...", "description": "..."}]}`) で取得する。
2. **Exploration & Critique フェーズ (自己批判)**:
   - 得られた 3 つのアプローチのそれぞれに対し、AIに「あえて厳しく自己批判（潜在的リスク、論理の飛躍、エッジケースでの破綻等）」を行わせる。
   - 評価の客観性を高めるため、`temperature=0.2` を適用する。
3. **Integration フェーズ (統合・最終結論)**:
   - 前フェーズで得られた自己批判の記録を `synthesis_instruction` としてシステム指示にマージする。
   - この指示のもとで、最も洗練された最終回答を `temperature=0.3` でストリーミング出力する。

### ② More Research（徹底調査モード）
Web検索結果を自律的に深掘りする ReAct 構造を有する。
1. **Dynamic Research ループ**:
   - 最大 3 サイクル実行される。
   - サイクル毎に、これまでに集まった情報をもとに情報が十分か判定する評価プロンプトを投げる。
   - 評価コンフィグは `temperature=0.2` で、JSON 形式（`{"status": "sufficient/needs_more_info", "next_queries": [...], "reasoning": "..."}`）で出力させる。
   - 堅牢化処理として、出力された文字列から Markdown コードブロック（````json` 等）を正規化除去し、文字列中の `{` と `}` の間を切り出してパースする。パース失敗時はフォールバックとしてループを終了する。
   - `needs_more_info` の場合、指定された検索クエリ（重複排除・最大3個）で Google 検索（Groundingツール）を実行し、その検索結果の要約事実を蓄積してループを継続する。
2. **Synthesis フェーズ**:
   - 収集されたすべての検索事実と「一次情報を優先する」「背景や前提条件を推測して論理的に比較する」といった推論ルールを `synthesis_instruction` に埋め込み、`temperature=0.3` で最終回答をストリーミング生成する。

### ③ Report PDF（レポート自動生成機能）
議論履歴からプレゼンテーション用の PDF スライドを書き出す。
1. **HTML 生成**:
   - `prompts.yaml` から `report_pdf` テンプレートを読み込み、会話履歴から美しい HTML/CSS（A4横向き、カードUI、Font Awesome アイコン、改ページ制御 `break-after: page` 等）を生成させる。
   - 生成結果から HTML コードを抽出し、`slide_data/<フォルダ名>/<連番>.html` に保存する。
2. **PDF エクスポート**:
   - Windows OSにインストールされているブラウザ（Edge または Chrome）の実行ファイルを以下の優先順位で自動スキャンする。
     1. `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`
     2. `C:\Program Files\Microsoft\Edge\Application\msedge.exe`
     3. `C:\Program Files\Google\Chrome\Application\chrome.exe`
     4. `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`
   - 見つかったブラウザを `subprocess.run` を用いて headless 起動し、HTML のローカルURIを読み込ませて PDF に印刷出力する。
     ```bash
     msedge.exe --headless=new --disable-gpu --allow-file-access-from-files --run-all-compositor-stages-before-draw --virtual-time-budget=5000 --print-to-pdf=<PDF出力パス> <HTMLファイルURI>
     ```
     ※ `virtual-time-budget=5000` は JavaScript 描画完了を待つための設定である。

### ④ Auto-Plot（データ分析・グラフ描画・自己修復）
1. **コード自動実行**:
   - チャット応答内に含まれる最新の ```python ... ``` ブロックを検出する。
   - 実行前に、OS判定（Windows -> "Meiryo", macOS -> "Hiragino Sans", Linux -> "Noto Sans CJK JP" 等）を行い、日本語が文字化けしないように matplotlib の font.family を動的に設定する。
   - 実行には Agg バックエンドを使用し、標準出力と標準エラー出力をキャプチャし、ローカル変数（`pd`, `plt`, `io`, `np`, `files`, `canvas_1`...）をインジェクションした `exec()` で実行する。
   - 実行完了後、`plt.get_fignums()` で生成された Figure を回収し、PNG形式で Base64 エンコードしてチャットにインライン表示する。
2. **自己修復ループ (Auto-Fix)**:
   - 実行出力に `Traceback (most recent call last):` が含まれる場合、エラー内容を AI にフィードバックして修正コードを要求する。
   - 最大 2 回までこの修復・再実行を自動ループする。

### ⑤ Report PPTX（PowerPointネイティブ生成機能）
議論履歴からプレゼンテーション用の PowerPoint スライド（.pptx）をネイティブ構築して書き出す。以下の4層構造パイプラインを有する。
1. **第1層：構造化 JSON 生成**:
   - 会話履歴から `PresentationDSLSchema`（プレゼンテーションタイトル、各スライドのタイトル、レイアウト名、プレースホルダーへの代入テキスト/画像/トリミング指示情報など）に準拠したJSON構成ストーリーを出力させる（`temperature=0.2`）。
   - テンプレート `format.pptx` が存在する場合、自動的にスライドレイアウト情報をスキャンし、利用可能なレイアウト名とプレースホルダー `idx` 情報をプロンプトに動的注入して、AIに正確にマッピングさせる。
2. **第2層＆第3層：物理マッピングと幾何学バリデーションループ**:
   - スライド毎の実座標に基づき、検証用の HTML モックを自動生成する。
   - Playwright (Chromium headless) を起動して HTML をレンダリングし、各テキストプレースホルダーで「スクロール溢れ（scrollHeight > clientHeight または scrollWidth > clientWidth）」が発生しているかを動的に検証する。
   - 溢れを検出した場合は、プレースホルダー ID や座標、スケール倍率（利用可能高さ/必要高さ）をエラー情報に含めて Gemini (gemini-3.5-flash) を呼び出し、文字数を約30%〜50%削減した要約にリライトさせる（最大3回の自己修復ループ）。
   - ループ上限に達しても解決しないスライドは、緊急用フォールバックとしてフォントサイズを `-2pt` 縮小して強制描画する。
3. **画像処理（生成＆トリミング）**:
   - プレースホルダーで AI 画像自動生成が指定されている場合、`gemini-3.1-flash-lite-image`（Nano Banana 2 Lite）または `imagen-3.0-generate-002` を呼び出して 16:9 画像をオンデマンド生成する。プレゼンテーション全体のビジュアル表現を豊かにするため、説明価値が高い場合は積極的に画像生成（全体で最大4枚程度まで）が実行される。
   - ユーザー添付画像を使用し、トリミング指示がある場合は、Gemini (gemini-3.5-flash) に画像と指示を渡し、対象物のバウンディングボックス相対座標（`CropAreaSchema`）を検出させ、Pillow で物理トリミングを適用する。
4. **第4層：物理 PowerPoint 生成とテンプレート後処理**:
   - `python-pptx` を使用してスライドを構築。テンプレート `format.pptx` が存在する場合、そのプレースホルダー `idx` にコンテンツ（テキスト、処理済み画像）を直接流し込んで描画する。描画後、AIが指定しなかった不要なプレースホルダーは自動削除する。
   - テンプレートの 1 枚目（表紙）はタイトル等を書き換えて利用し、2 枚目の「見本スライド」は自動削除し、3 枚目の「裏表紙スライド」は AI コンテンツスライドの後に移動させて最末尾に配置する後処理を実行して保存する。

---

## 7. LLMルーティング・高可用性仕様

### ① 二重化リクエスト制御
GCP Vertex AI の呼び出しにおいて、APIの429（Rate Limit）やタイムアウトなどの一時エラーに強固に対応するため、以下の2つのクライアントを使い分ける（`llm_router.py`）。
- **Standard クライアント**: リトライ回数を1回に制限。通常時はこちらを使用する。
- **Priority クライアント**: レート制限対策のヘッダー（`X-Vertex-AI-LLM-Request-Type: shared`, `X-Vertex-AI-LLM-Shared-Request-Type: priority`）を注入。
- **リトライポリシー**: Standard クライアントで 429 などのリトライ対象ステータスコードを検知すると、自動的に Priority クライアントにスイッチし、指数バックオフとランダム Jitter（待ち時間: 2.0s, 4.0s, 8.0s + 0~1秒のランダム値）を用いて最大 3 回までリトライを行う。

### ② Azure Fallback (自動フォールバック)
- GCP 側の API リクエストで最終的に例外エラーがスローされた、またはデバッグログから 429 等の致命的エラーが検出された場合に動作する。
- **作動条件**: まだチャット応答の文字出力が 1 文字も始まっていないこと (`visible_output_started=False`)、および Azure 接続設定が有効であること。
- **処理**: リトライ用にディープコピーしたコンテキストスナップショットを用いて Azure OpenAI API に切り替えてリクエストを再送し、シームレスに応答を継続する。

### ③ Azure 直接接続 (GCP バイパス)
- UIのモデル選択で `gpt-5.3-codex` が選択された場合、Vertex AI への接続をスキップし、最初から Azure OpenAI に直接接続して応答を生成する。この際、UIのローディング表示もAzure用に動的に変化する。

### ④ GCP Cloud Logging 送信スキップ
- Azure 直接接続時、または自動フォールバックが機能して Azure 側で応答を生成した時は、GCP Cloud Logging への送信処理を自動的にスキップする。これにより、GCPの権限不足（403 Forbidden）による無駄なエラーログの発生を防ぐ。

---

## 8. セッション状態 (Session State) 変数とクリーンアップ

### ① 主要な Session State 変数定義

| 変数名 | 型 | 役割・用途 |
| :--- | :--- | :--- |
| `messages` | `list` | チャット履歴の辞書リスト（ロール、コンテンツ、Grounding情報等）。 |
| `python_canvases` | `list` | Canvasに記述された Python コード文字列のリスト。 |
| `canvas_enabled` | `list` | 各 Canvas の「AIへ送信」トグル状態（boolean）のリスト。 |
| `toggle_keys` | `list` | トグルの widget key のインクリメント用カウンターリスト（巻き戻り防止）。 |
| `canvas_key_counter` | `int` | 全 Canvas の widget key 更新用カウンター（フルリセット・ロード時にインクリメント）。 |
| `always_send_all_canvases` | `bool` | 全ての Canvas を常に送信するトグルフラグ。 |
| `current_chat_filename` | `str` | 現在開いているチャット履歴 JSON のローカルファイル名。 |
| `current_report_folder` | `str` | 現在のチャットに紐づくレポート保存フォルダ名。 |
| `uploaded_file_queue` | `list` | 送信待ちの Streamlit アップロードファイルオブジェクトのリスト。 |
| `clipboard_queue` | `list` | クリップボードから取得した一時画像オブジェクト of VirtualUploadedFile のリスト。 |

### ② 履歴ロード・リセット時のクリーンアップ処理
前のセッション情報の残留による誤作動を排除するため、履歴ファイルのロード時（アップロードまたはローカル履歴読込時）および「会話履歴をリセット」押下時は、以下のクリーンアップを厳密に実行する。

1. **添付ファイルキューの全削除**: `uploaded_file_queue` と `clipboard_queue` を `[]` にクリア。
2. **ファイルアップローダーUIのリセット**: `file_uploader_key` をインクリメント（これにより `st.file_uploader` に残ったキャッシュが強制リセットされる）。
3. **Canvas 送信フラグの再構築**:
   - `always_send_all_canvases` が ON の場合は全 Canvas を ON とする。
   - OFF の場合は、前のセッションのトグル状態を引き継がず、履歴に含まれる各 Canvas の内容を走査し、空またはデフォルトコード（`# コードはここに \n`）以外の**意味のあるコードが記述されている Canvas のみ**を ON、その他を OFF で再構築する。
4. **widget 一時ステートの消去**: session_state 内の `ace_`, `up_`, `cvs_tog_` で始まる一時ウィジェットキーをすべて `del` する。
5. ** widget 巻き戻り防止フラグの適用**: `_canvas_reset_pending = True` を適用し、次のレンダリングループで st_ace などのコンポーネントが旧値に巻き戻ることを防止する。
6. **レポートフォルダのクリア**: ロードされた履歴に `current_report_folder` がない場合はクリアして残留を防ぐ。

---

## 改訂履歴
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
