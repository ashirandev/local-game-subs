@echo off
REM Downloads the model (about 5.7 GB, resumable) and then checks that it works.
cd /d "%~dp0"
set PYTHONPATH=%~dp0src;%PYTHONPATH%
set PYTHONIOENCODING=utf-8
python -u -X utf8 -m gamesubs setup %*
if errorlevel 1 goto done
echo.
python -u -X utf8 -m gamesubs check
:done
echo.
pause
