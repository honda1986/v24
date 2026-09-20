@echo off
rem 毎日ひとりでに動くように、タスクスケジューラへ登録する。
rem   ★このファイルは「右クリック → 管理者として実行」で開くこと。
setlocal
set PYTHONUTF8=1
title v24 タスク登録

net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo   管理者として実行してください。
  echo   このファイルを右クリックして「管理者として実行」を選びます。
  echo.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0register_tasks.ps1"
if errorlevel 1 (
  echo.
  echo   登録に失敗しました。上の赤い字をそのまま貼って相談してください。
  echo.
  pause
  exit /b 1
)

echo.
echo   さっそく1回動かしてみます（1～2分かかります）...
schtasks /run /tn boat_yosou >nul 2>&1
timeout /t 100 /nobreak >nul

rem 日付の見た目は地域設定で変わるので、date /t は当てにしない
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%d
set LOG=C:\boat\logs\yosou_%TODAY%.log
echo.
if exist "%LOG%" (
  echo   --- %LOG% の終わりのほう ---
  powershell -NoProfile -Command "Get-Content -Tail 15 -Encoding UTF8 '%LOG%'"
) else (
  echo   ログがまだありません: %LOG%
  echo   もう少し待ってから、そのフォルダを見てください。
)

echo.
echo   ここまで来たら、あとは毎日ひとりでに動きます。
echo.
pause
