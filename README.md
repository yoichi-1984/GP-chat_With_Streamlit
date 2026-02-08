GP-Chat_With_Streamlit: Gemini対応AI汎用チャットアプリ  
  
## Table of Contents  
  
- [概要](#概要)  
- [リポジトリ構成](#リポジトリ構成)  
- [インストール](#インストール例)  
- [環境設定](#環境設定)  
- [使い方](#使い方)  
- [主な機能](#主な機能)  
- [CHANGELOG](#changelog)  
- [ライセンス](#ライセンス)  
- [Author](#Author)  
  
---  
## 概要  
  
`GP-Chat_With_Streamlit` は、  
GeminiAPIに対応した汎用のチャットアプリケーションです。  
本アプリケーションは、従来のチャット形式の対話に加え、PDF・画像・WORDファイルの添付機能と、  
複数のコードブロック（Canvas）をコンテキストとしてAIに提供できる「マルチコード」機能を  
搭載しています。  
  
CLIラッパー (`main_runner.py`) は `streamlit run main.py` を自動で呼び出します。  
  
---  
## リポジトリ構成  
.  
 ├── env/  
 │ └── *.env # モデル設定ファイル (選択可能)  
 ├── src/  
 │ 　└── codex_chat_gcp/  
 │ 　　├── __init__.py  
 │ 　　├── main.py # Streamlit アプリケーション本体  
 │ 　　├── main_runner.py # CLI からの起動用ラッパー  
 │ 　　├── utils.py # ヘルパー関数群  
 │ 　　├── config.py # 定数・テキスト定義  
 │ 　　├── config.yaml # テキスト情報  
 │ 　　├── sidebar.py # サイドバー機能管理  
 │ 　　├── data_manager.py # ファイル管理  
 │ 　　├── execution_engine.py # 内部コード実行用  
 │ 　　└── prompts.yaml # プロンプト定義  
 ├── .gitignore  
 ├── LICENSE  
 ├── README.md  
 ├── pyproject.toml  
 ├── sample_of.env  
 ├── requirements.txt  
 ├── install.bat  
 ├── START.bat  
 └── CHANGELOG.md  
  
---  
## 環境設定  
  
google cloudにアクセスし、画面左上部からプロジェクト選択ボタン押し、  
該当のプロジェクトID（最右列）をメモ(後述のGCP_PROJECT_ID)。  
Google Cloud コンソールのメニューから「API とサービス」>「ライブラリ」を選択。  
検索バーから"vertex ai api"を検索し、開き、有効にする。  
コンソールのナビゲーションメニューから「IAM と管理」>「サービス アカウント」に移動し、  
上部の「＋サービス アカウントを作成」をクリックし、  
サービスアカウント名（例: gemini-3-pro-runner）を入力し、「作成して続行」をクリックする。  
「このサービス アカウントにプロジェクトへのアクセス権を付与する」セクションで、  
ロールから、「Vertex AI ユーザー」を選択。  
最後のステップは省略可能なので、そのまま「完了」。  
作成したサービスアカウントのメールアドレスをクリックして詳細画面を開き、  
「キー」タブを選択し、「鍵を追加」>「新しい鍵を作成」の順にクリック。  
キーのタイプとして「JSON」を選択し、「作成」をクリックしてダウンロードし、  
ローカルの所定の場所に保管。  
  
プロジェクトルートに env/ ディレクトリを作成し、.env ファイルを配置。  
"GOOGLE_APPLICATION_CREDENTIALS"には、前述したjsonファイルのアドレスを記述。  

GCP_PROJECT_ID="gen-lang-client-xxxxx"  
GCP_LOCATION="global"  
GEMINI_MODEL_ID="gemini-3-pro-preview"  
GOOGLE_APPLICATION_CREDENTIALS="C:/xxxxx/gen-lang-client-xxxx-xxxx.json"  
  
---  
## 事前準備    
  
以下に記載の方法でPython仮想環境を構築  
https://note.com/yoichi_1984xx/n/n3c95602b011c  
  
pyproject.tomlに従ってインストール。  
pip install -e .  
その後は  
仮想環境で「gp-chat」と打ち込めば、内部的にstreamlit run で main_runner.py が実行される。  
  
他には  
python -m src.gp_chat.main_runner  
や  
streamlit run src/gp_chat/main.py  
でも起動できます。  
  
---  
## 主な機能  
### AIモデルの選択:  
 サイドバー上部にAIモデルの選択リストがあります。使いたいモデルを選択してください。  
### AIの役割設定:  
 最初のチャット画面で、AIの役割を定義するシステムプロンプトを入力し、「この役割でチャットを開始する」ボタンをクリックします。  
### マルチ Canvas コードエディタ（最大 20）:  
 Canvasを用いてコードをAIに効率よく読ませることができます。マルチコード機能を有効にすることで、最大20個までCanvasを拡張することも可能です。  
### 会話履歴の JSON ダウンロード／アップロード:  
 AIの役割、チャット履歴、Canvasの内容すべてをJSON形式でダウンロードし、途中再開が可能です。  
 チャット再開時には、AIモデルの選択情報、Canvasに記述したコード、チャット内容すべて再開できます。  
### 応答ストリーミング＆停止ボタン:  
 APIからの応答をリアルタイム表示し、途中停止が可能。  
### トークン使用量の表示・累計:  
 AIモデルの最大トークンに考慮した形でチャットができるように、最新の使用トークンを表示します。  
  
---  
## CHANGELOG  
すべてのリリース履歴は CHANGELOG.md に記載しています。  
  
---  
## ライセンス  
 本ソフトウェアは「Apache License 2.0」に準拠しています。  
  
---  
## Author  
 -Yoichi-1984 (<yoichi.1984.engineer@gmail.com>)  
