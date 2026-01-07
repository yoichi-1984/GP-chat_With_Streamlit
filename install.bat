@echo off

:: 1. Python仮想環境を有効にする
echo Activating virtual environment...
call ".\env\Scripts\activate.bat"
if not exist ".\env\Scripts\activate.bat" (
    echo Error: Virtual environment not found.
    pause
    exit
)

:: 2. pip と setuptools をアップグレードする
echo.
echo Upgrading pip and setuptools...
python -m pip install --upgrade pip setuptools

:: 3. カレントディレクトリにある全ての.whlファイルをインストールする
echo.
echo Installing .whl files...
FOR %%f IN (*.whl) DO (
    echo  - Installing %%f
    python -m pip install "%%f"
)

echo.
echo =================================
echo  Setup complete.
echo  The virtual environment is active.
echo =================================
echo.

:: 4. コマンドプロンプトを開いたままにする
cmd /k