@echo off
setlocal EnableDelayedExpansion

echo ======================================================
echo  GP-Chat Certificate and Security Update Tool
echo ======================================================
echo.

REM --- 1. Activate Python virtual environment ---
echo [1/3] Activating virtual environment...
if exist ".\env\Scripts\activate.bat" (
    call ".\env\Scripts\activate.bat"
) else (
    echo [ERROR] Virtual environment not found at .\env\Scripts\activate.bat
    echo Please make sure the 'env' virtual environment is set up.
    pause
    exit /b 1
)

REM --- 2. Upgrade target security packages ---
echo.
echo [2/3] Upgrading security packages and certificates...
echo Upgrading: streamlit, pillow, urllib3, GitPython, requests, certifi, grpcio, brotli
python -m pip install --upgrade "streamlit>=1.54.0" "pillow>=13.0.0" "urllib3>=2.8.0" "GitPython>=3.1.51" "requests>=2.33.0" "certifi>=2026.10.19" "grpcio>=1.83.0" "brotli>=1.2.1"
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to upgrade packages.
    echo Please check your internet connection or proxy settings.
    pause
    exit /b 1
)

REM --- 3. Verify installed versions ---
echo.
echo [3/3] Verifying installed security versions...
python -c "import streamlit, PIL, urllib3, git, requests, certifi, grpc, brotli; print('  [OK] streamlit : ' + str(streamlit.__version__)); print('  [OK] pillow    : ' + str(PIL.__version__)); print('  [OK] urllib3   : ' + str(urllib3.__version__)); print('  [OK] GitPython : ' + str(git.__version__)); print('  [OK] requests  : ' + str(requests.__version__)); print('  [OK] certifi   : ' + str(certifi.__version__)); print('  [OK] grpcio    : ' + str(grpc.__version__)); print('  [OK] brotli    : ' + str(brotli.__version__))"

echo.
echo ======================================================
echo  Update completed successfully!
echo  Your certificates and security libraries are up to date.
echo ======================================================
echo.
pause
