@echo off
setlocal EnableDelayedExpansion

:: 1. Python仮想環境を有効にする
echo Activating virtual environment...
if exist ".\env\Scripts\activate.bat" (
    call ".\env\Scripts\activate.bat"
) else (
    echo Error: Virtual environment not found at .\env\Scripts\activate.bat
    pause
    exit /b 1
)

:: 2. ツール類の更新 (packagingライブラリも追加で確保)
echo.
echo Upgrading pip, setuptools and packaging...
python -m pip install --upgrade pip setuptools packaging

:: 3. Pythonスクリプトを生成して、最新のwhlリストを作成する
echo.
echo Calculating latest versions...

(
echo import glob, os
echo from packaging.version import parse
echo whls = glob.glob("*.whl"^)
echo groups = {}
echo for w in whls:
echo     parts = w.split("-"^)
echo     if len(parts^) ^< 2: continue
echo     name = parts[0]
echo     if name not in groups: groups[name] = []
echo     groups[name].append(w^)
echo for name, files in groups.items(^):
echo     latest = sorted(files, key=lambda x: parse(x.split("-"^)[1]^)^)[-1]
echo     print(latest^)
) > _filter_whl.py

:: 4. 抽出された最新ファイルのみをインストール
echo.
echo Installing latest .whl files...
if exist _filter_whl.py (
    FOR /F "usebackq tokens=*" %%f IN (`python _filter_whl.py`) DO (
        echo  - Installing %%f
        python -m pip install "%%f"
    )
    del _filter_whl.py
)

echo.
echo =================================
echo  Setup complete.
echo  The virtual environment is active.
echo =================================
echo.

:: 5. コマンドプロンプトを開いたままにする
cmd /k