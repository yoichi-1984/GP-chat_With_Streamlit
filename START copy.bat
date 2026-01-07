@echo off
REM --- Python仮想環境を有効化 ---
echo Activating virtual environment...
call ".\env\Scripts\activate.bat"

REM --- アプリケーションを起動 ---
streamlit run src/gp_chat/main_runner.py