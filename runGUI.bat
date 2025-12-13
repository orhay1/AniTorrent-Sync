@echo off
set SCRIPT_DIR=%~dp0
set PYTHON_EXE=%SCRIPT_DIR%venv\Scripts\pythonw.exe

if not exist "%PYTHON_EXE%" (
    echo [ERROR] pythonw.exe not found in venv.
    exit /b 1
)

start "" "%PYTHON_EXE%" "%SCRIPT_DIR%gui.py"
exit
