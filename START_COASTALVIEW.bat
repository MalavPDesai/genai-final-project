@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title CoastalView GenAI Launcher

echo.
echo ============================================================
echo   CoastalView CRM + GenAI Demo
echo   One-click Windows launcher
echo ============================================================
echo.

REM ------------------------------------------------------------
REM 1. Find Python. If it is missing, try to install Python 3.12
REM    through Windows Package Manager (winget).
REM ------------------------------------------------------------
set "PYTHON_EXE="

where python >nul 2>&1
if not errorlevel 1 (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python"
)

if not defined PYTHON_EXE (
    where py >nul 2>&1
    if not errorlevel 1 (
        py --version >nul 2>&1
        if not errorlevel 1 set "PYTHON_EXE=py"
    )
)

if not defined PYTHON_EXE (
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    )
)

if not defined PYTHON_EXE (
    echo [1/5] Python was not found.
    echo       I will try to install Python 3.12 automatically with winget.
    echo.
    where winget >nul 2>&1
    if errorlevel 1 goto :NO_WINGET

    winget install --exact --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    if errorlevel 1 goto :PYTHON_INSTALL_FAILED

    REM The current Command Prompt may not receive the updated PATH immediately,
    REM so locate the newly installed interpreter directly.
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    )

    if not defined PYTHON_EXE (
        for /f "delims=" %%P in ('where /r "%LOCALAPPDATA%\Programs\Python" python.exe 2^>nul') do (
            if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
        )
    )
)

if not defined PYTHON_EXE goto :PYTHON_INSTALL_FAILED

echo [1/5] Python ready.
"%PYTHON_EXE%" --version
echo.

REM ------------------------------------------------------------
REM 2. Create a local virtual environment.
REM    We call its python.exe directly, so no PowerShell execution
REM    policy changes and no manual activation are required.
REM ------------------------------------------------------------
set "VENV_PY=%CD%\.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [2/5] Creating the CoastalView Python environment...
    "%PYTHON_EXE%" -m venv ".venv"
    if errorlevel 1 goto :VENV_FAILED
) else (
    echo [2/5] Existing Python environment found.
)
echo.

REM ------------------------------------------------------------
REM 3. Install dependencies only when the environment is missing
REM    one of the packages CoastalView needs.
REM ------------------------------------------------------------
"%VENV_PY%" -c "import fastapi, uvicorn, openai, dotenv, numpy, pydantic, pytest, httpx" >nul 2>&1
if errorlevel 1 (
    echo [3/5] Installing CoastalView dependencies.
    echo       First launch can take a minute or two...
    "%VENV_PY%" -m pip install --upgrade pip
    if errorlevel 1 goto :DEPENDENCY_FAILED
    "%VENV_PY%" -m pip install -r "requirements.txt"
    if errorlevel 1 goto :DEPENDENCY_FAILED
) else (
    echo [3/5] Dependencies are already installed.
)
echo.

REM ------------------------------------------------------------
REM 4. Ensure .env exists. If the OpenAI key is blank, open the
REM    file in Notepad so the user only has to paste it once.
REM ------------------------------------------------------------
if not exist ".env" (
    copy /y ".env.example" ".env" >nul
)

:CHECK_API_KEY
set "OPENAI_KEY="
for /f "tokens=1,* delims==" %%A in ('findstr /b /c:"OPENAI_API_KEY=" ".env" 2^>nul') do (
    set "OPENAI_KEY=%%B"
)

if not defined OPENAI_KEY (
    echo [4/5] Your OpenAI API key has not been added yet.
    echo.
    echo       Notepad will open your private .env file.
    echo       Paste your key after:
    echo.
    echo       OPENAI_API_KEY=
    echo.
    echo       Example:
    echo       OPENAI_API_KEY=sk-your-key-here
    echo.
    echo       Save the file and close Notepad to continue.
    echo       Do not put the key in frontend files.
    echo.
    start /wait "" notepad.exe ".env"

    set "OPENAI_KEY="
    for /f "tokens=1,* delims==" %%A in ('findstr /b /c:"OPENAI_API_KEY=" ".env" 2^>nul') do (
        set "OPENAI_KEY=%%B"
    )

    if not defined OPENAI_KEY (
        echo.
        echo The API key is still blank.
        choice /C RO /N /M "Press R to reopen .env, or O to run the offline demo: "
        if errorlevel 2 goto :START_APP
        goto :CHECK_API_KEY
    )
)

echo [4/5] Configuration ready. OpenAI live mode will be requested.
echo.

REM ------------------------------------------------------------
REM 5. Start a delayed browser opener, then run Uvicorn in this
REM    same window. Closing this window or pressing Ctrl+C stops it.
REM ------------------------------------------------------------
:START_APP
echo [5/5] Starting CoastalView...
echo.
echo       The website will open automatically at:
echo       http://127.0.0.1:8000
echo.
echo       Keep this window open while using CoastalView.
echo       Press Ctrl+C here when you are finished.
echo.
echo ============================================================
echo.

start "" /b "%VENV_PY%" -c "import time, webbrowser; time.sleep(2.5); webbrowser.open('http://127.0.0.1:8000')"

"%VENV_PY%" -m uvicorn main:app --host 127.0.0.1 --port 8000

echo.
echo CoastalView has stopped.
pause
exit /b 0

:NO_WINGET
echo.
echo ERROR: Python is not installed and Windows Package Manager (winget)
echo could not be found.
echo.
echo Install Python 3.12 from:
echo https://www.python.org/downloads/windows/
echo.
echo During installation, select "Add python.exe to PATH".
echo Then double-click START_COASTALVIEW.bat again.
echo.
pause
exit /b 1

:PYTHON_INSTALL_FAILED
echo.
echo ERROR: Python could not be installed automatically.
echo.
echo Install Python 3.12 from:
echo https://www.python.org/downloads/windows/
echo.
echo Then double-click START_COASTALVIEW.bat again.
echo.
pause
exit /b 1

:VENV_FAILED
echo.
echo ERROR: The local Python environment could not be created.
echo Please copy the error shown above and ask for help.
echo.
pause
exit /b 1

:DEPENDENCY_FAILED
echo.
echo ERROR: One or more Python packages could not be installed.
echo Check your internet connection, then double-click this launcher again.
echo.
pause
exit /b 1
