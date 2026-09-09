@echo off
REM Double-click this. On the very first run it offers to fetch what it needs; after that it
REM just starts. Everything it installs stays inside THIS folder, so uninstalling is deleting it.
cd /d "%~dp0"
set PYTHONPATH=%~dp0src;%PYTHONPATH%
set PYTHONIOENCODING=utf-8
set VENVPY=%~dp0.venv\Scripts\python.exe

if exist "%VENVPY%" goto play

REM ---------------------------------------------------------------- first run
REM It used to say "run setup.bat first" and stop. That is a second file to find, in a folder of
REM thirty, for somebody who has just downloaded a zip and pressed the obvious button. But a
REM double-click must never quietly pull six gigabytes either, so it says what it is about to do
REM and waits to be told.
echo.
echo   This is the first run, so there are two things to fetch before anything can start:
echo.
echo     llama.cpp   the program that runs the model      about 34 MB
echo     the model   what reads your screen and translates  about 5.9 GB
echo.
echo   Both go into THIS folder and nowhere else. Nothing is written to your registry, your
echo   home folder, or your system Python. Uninstalling is deleting this folder.
echo.
echo   It resumes if you stop it, so a lost connection is not a lost download.
echo.
set /p GO=  Press ENTER to fetch them now, or type N and press ENTER to cancel:
if /i "%GO%"=="N" (
  echo.
  echo   Nothing was downloaded. Run this again whenever you want to.
  echo.
  pause
  exit /b 0
)

echo.
call "%~dp0setup.bat" --no-check
if not exist "%VENVPY%" (
  echo.
  echo   Setup did not finish, so there is nothing to start yet. The message above says why.
  echo.
  pause
  exit /b 1
)

echo.
echo   Ready. Starting...
echo.

:play
"%VENVPY%" -u -X utf8 -m gamesubs play %*
echo.
pause
