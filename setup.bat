@echo off
REM Double-click this once. It installs the Python packages, downloads llama.cpp and the model,
REM then proves the whole thing works. Safe to run again -- every step skips or resumes.
cd /d "%~dp0"
set PYTHONPATH=%~dp0src;%PYTHONPATH%
set PYTHONIOENCODING=utf-8

python --version >nul 2>&1
if errorlevel 1 (
  echo Python is not installed, or it was installed without "Add Python to PATH".
  echo Get it from https://www.python.org/downloads/ and tick that box during setup.
  echo.
  pause
  exit /b 1
)

echo Installing the three Python packages this needs...
python -m pip install --quiet --disable-pip-version-check mss numpy Pillow
if errorlevel 1 (
  echo pip failed. Try running this window as Administrator, or:
  echo   python -m pip install --user mss numpy Pillow
  echo.
  pause
  exit /b 1
)
echo.

python -u -X utf8 -m gamesubs setup %*
if errorlevel 1 goto done

echo.
echo Now checking that your machine can actually run it...
echo.
python -u -X utf8 -m gamesubs check

:done
echo.
echo When that says PASS, start a game and double-click play.bat
echo.
pause
