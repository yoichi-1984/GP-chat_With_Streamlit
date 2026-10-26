@echo off
setlocal EnableDelayedExpansion

echo ======================================================
echo  GP-Chat Installer and Environment Setup
echo ======================================================
echo.

REM --- 1. Activate Python virtual environment ---
echo [1/4] Activating virtual environment...
if exist ".\env\Scripts\activate.bat" (
    call ".\env\Scripts\activate.bat"
) else (
    echo [ERROR] Virtual environment not found at .\env\Scripts\activate.bat
    pause
    exit /b 1
)

REM --- 2. Upgrade pip, setuptools and packaging ---
echo.
echo [2/4] Upgrading pip, setuptools and packaging...
python -m pip install --upgrade pip setuptools packaging

REM --- 3. Install/Upgrade application and dependencies ---
echo.
echo [3/4] Installing application and dependencies...

REM (A) Install from requirements.txt if present
if exist "requirements.txt" (
    echo  - Installing from requirements.txt...
    python -m pip install --upgrade -r requirements.txt
)

REM (B) Find and install latest .whl file if present
(
echo import glob, os
echo from packaging.version import parse
echo whls = glob.glob("*.whl"^) + glob.glob("dist/*.whl"^)
echo groups = {}
echo for w in whls:
echo     base = os.path.basename(w^)
echo     parts = base.split("-"^)
echo     if len(parts^) ^< 2: continue
echo     name = parts[0]
echo     if name not in groups: groups[name] = []
echo     groups[name].append(w^)
echo for name, files in groups.items(^):
echo     latest = sorted(files, key=lambda x: parse(os.path.basename(x^).split("-"^)[1]^)^)[-1]
echo     print(latest^)
) > _filter_whl.py

if exist _filter_whl.py (
    FOR /F "usebackq tokens=*" %%f IN (`python _filter_whl.py`) DO (
        echo  - Installing latest wheel: %%f
        python -m pip install --upgrade "%%f"
    )
    del _filter_whl.py
)

REM (C) Ensure critical security packages are definitely up to date
echo  - Ensuring critical security packages are up to date...
python -m pip install --upgrade "streamlit>=1.54.0" "pillow>=13.0.0" "urllib3>=2.8.0" "GitPython>=3.1.51" "requests>=2.33.0" "certifi>=2026.10.19" "grpcio>=1.83.0" "brotli>=1.2.1"

REM --- 4. Verify installed security versions ---
echo.
echo [4/4] Verifying installed security versions...
python -c "import streamlit, PIL, urllib3, git, requests, certifi, grpc, brotli; print('  [OK] streamlit : ' + str(streamlit.__version__)); print('  [OK] pillow    : ' + str(PIL.__version__)); print('  [OK] urllib3   : ' + str(urllib3.__version__)); print('  [OK] GitPython : ' + str(git.__version__)); print('  [OK] requests  : ' + str(requests.__version__)); print('  [OK] certifi   : ' + str(certifi.__version__)); print('  [OK] grpcio    : ' + str(grpc.__version__)); print('  [OK] brotli    : ' + str(brotli.__version__))"

echo.
echo ======================================================
echo  Setup complete.
echo  The virtual environment is active and up to date.
echo ======================================================
echo.

REM --- 5. Keep command prompt open ---
cmd /k
