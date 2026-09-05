# AGENTS.md

## 1. プロジェクト概要 & 技術スタック
- Framework: (例: Next.js / FastAPI / React / etc.)
- Language: (例: TypeScript strict / Python 3.12 / etc.)
- Package Manager: (例: pnpm / npm / poetry / etc.)

## 2. 検証コマンド (Verification Ground Truth)
エージェントはコード修正後、以下のコマンドを実行して正常終了（Exit Code 0）を確認すること。
- 型チェック / Lint: `npm run lint` （または `mypy .` 等）
- 単体テスト: `npm test` （または `pytest` 等）
- ビルド確認: `npm run build`

## 3. 参照ディレクトリ
- 仕様書正本: `for_agent/` 配下のすべての .md ファイル
- 進捗管理: `Plan.md`
- 変更ログ: `AICHANGELOG.md`