@echo off
rem v24 の定期実行を1回まわす。タスクスケジューラから呼ばれる。
rem   使い方: task.bat yosou   /   task.bat prefetch   /   task.bat motor
rem   後ろに足せる: task.bat yosou --dry   （通知しない。並走で試すとき）
rem
rem ★PYTHONUTF8=1 は必須。Windows の Python は既定で cp932 で読み書きするので、
rem   日本語の JSON がどこかで化ける。
setlocal
set PYTHONUTF8=1
set BOAT=C:\boat
cd /d "%BOAT%\v24"
"%BOAT%\venv\Scripts\python.exe" runner.py %* --v22 "%BOAT%\v22" --log-dir "%BOAT%\logs"
exit /b %ERRORLEVEL%
