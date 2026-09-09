@echo off
REM Double-click when lines are MISSED or read twice. It shows the two numbers that decide
REM when the model runs -- ink and chg -- and writes band.png, the exact crop being read.
REM No model is loaded, so it is instant and free to leave running while you play.
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

"%VENVPY%" -u -X utf8 -m gamesubs tune %*
echo.
pause
