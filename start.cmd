@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 goto failed
set "DEMO_PYTHON=%~dp0.venv\Scripts\python.exe"
if exist "%DEMO_PYTHON%" goto run
set "DEMO_PYTHON=%~dp0..\.venv\Scripts\python.exe"
if exist "%DEMO_PYTHON%" goto run
echo Python environment was not found. See README.md.
goto failed
:run
"%DEMO_PYTHON%" "%~dp0app.py" %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo Demo could not start. See README.md.
pause
exit /b 1
