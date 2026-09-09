@echo off
REM Double-click this once. Everything it installs stays inside THIS folder:
REM
REM   .venv\          a private Python with the three packages this needs
REM   models\         the model and its vision projector
REM   llama.cpp\      the program that runs the model
REM
REM Nothing is written to your home folder, your registry, or your system Python. Uninstalling
REM is deleting this folder. Safe to run again -- every step skips or resumes.
cd /d "%~dp0"
set PYTHONPATH=%~dp0src;%PYTHONPATH%
set PYTHONIOENCODING=utf-8
set VENVPY=%~dp0.venv\Scripts\python.exe

python --version >nul 2>&1
if errorlevel 1 (
  echo Python is not installed, or it was installed without "Add Python to PATH".
  echo Get it from https://www.python.org/downloads/ and tick that box during setup.
  echo.
  pause
  exit /b 1
)

if exist "%VENVPY%" goto haveenv
echo Creating a private Python inside this folder ^(.venv^)...
python -m venv "%~dp0.venv"
if errorlevel 1 (
  echo Could not create the virtual environment.
  echo.
  pause
  exit /b 1
)
:haveenv

echo Installing the five packages this needs, into .venv only...
"%VENVPY%" -m pip install --quiet --disable-pip-version-check --upgrade pip
"%VENVPY%" -m pip install --quiet --disable-pip-version-check mss numpy Pillow uharfbuzz freetype-py
if errorlevel 1 (
  echo Installing the packages failed. Check your internet connection and run this again.
  echo.
  pause
  exit /b 1
)
echo.

REM play.bat calls this on a first run and then starts immediately, so there is nothing for
REM a check or a "now press play" message to be useful for. NOT passed through to the
REM python side, which has never heard of it -- and `shift` would not help, because it does
REM not change %*.
set SKIPCHECK=
if /i "%~1"=="--no-check" (
  set SKIPCHECK=1
  "%VENVPY%" -u -X utf8 -m gamesubs setup
) else (
  "%VENVPY%" -u -X utf8 -m gamesubs setup %*
)
if errorlevel 1 goto done
if defined SKIPCHECK goto quiet

echo.
echo Now checking that your machine can actually run it...
echo.
"%VENVPY%" -u -X utf8 -m gamesubs check

:done
if defined SKIPCHECK goto quiet
echo.
echo When that says PASS, start a game and double-click play.bat
echo.
pause

:quiet
