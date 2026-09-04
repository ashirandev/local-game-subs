@echo off
REM Double-click to start translating. Run setup.bat once first.
REM Works whether or not the package is pip-installed: src is put on the path either way.
cd /d "%~dp0"
set PYTHONPATH=%~dp0src;%PYTHONPATH%
set PYTHONIOENCODING=utf-8
python -u -X utf8 -m gamesubs play %*
echo.
pause
