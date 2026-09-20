@echo off
rem v24 を PC で動かす準備。ダブルクリックするだけ。
rem   何度やり直しても壊れません。途中で転んだら直してもう一度どうぞ。
setlocal
set PYTHONUTF8=1
title v24 PC移行 セットアップ

set PY=
py -3.11 -c "import sys" >nul 2>&1 && set "PY=py -3.11"
if not defined PY (
  py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
  python -c "import sys" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo.
  echo   Python が見つかりません。
  echo   https://www.python.org/downloads/ から 3.11 を入れてください。
  echo   入れるときに「Add python.exe to PATH」に必ずチェックを。
  echo.
  pause
  exit /b 1
)

%PY% "%~dp0setup.py"
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
