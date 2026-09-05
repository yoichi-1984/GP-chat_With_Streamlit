# AGENTS.md

## 1. プロジェクト概要 & 技術スタック
- Framework: Streamlit
- Language: Python (venv: env)
- Package Manager: pip

## 2. 検証コマンド (Verification Ground Truth)
エージェントはコード修正後、以下のコマンドを実行して正常終了（Exit Code 0）を確認すること。
- 依存整合性: `.\env\Scripts\python.exe -m pip check`
- 構文チェック: `.\env\Scripts\python.exe -m py_compile <ファイル名>.py`
- 単体テスト: `pytest` （※テストコードが存在する場合のみ pytest を実行）
- 静的コード解析: `.\env\Scripts\python.exe -m pylint <対象ファイル>` (スコア良好・構文エラーなし)

## 3. 参照ディレクトリ
- 仕様書正本: `for_agent/` 配下のすべての .md ファイル
- 進捗管理: `Plan.md`
- 変更ログ: `AICHANGELOG.md`