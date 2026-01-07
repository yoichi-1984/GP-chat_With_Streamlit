@echo off
REM --- Python仮想環境を有効化 ---
echo Activating virtual environment...
call ".\env\Scripts\activate.bat"

REM --- アプリケーションを起動 ---
echo Starting codex-chat-gcp...
gp-chat