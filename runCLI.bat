@echo off
REM Get the directory of this script
set SCRIPT_DIR=%~dp0

REM Path to venv python
set PYTHON_EXE=%SCRIPT_DIR%venv\Scripts\python.exe

REM Check that venv exists
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Virtual environment not found.
    echo Expected: %PYTHON_EXE%
    echo.
    echo Create it with:
    echo   python -m venv venv
    exit /b 1
)

REM Run the app using venv python
"%PYTHON_EXE%" "%SCRIPT_DIR%main.py" --config "%SCRIPT_DIR%config.yaml"

pause
