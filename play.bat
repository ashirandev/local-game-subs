@echo off
REM Double-click to start translating. Run setup.bat once first.
REM Uses the private Python in .venv, so nothing outside this folder is involved.
cd /d "%~dp0"
set PYTHONPATH=%~dp0src;%PYTHONPATH%
set PYTHONIOENCODING=utf-8
set VENVPY=%~dp0.venv\Scripts\python.exe

if not exist "%VENVPY%" (
  echo Run setup.bat first -- there is no .venv folder here yet.
  echo.
  pause
  exit /b 1
)

"%VENVPY%" -u -X utf8 -m gamesubs play %*
echo.
pause
