@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"

:MENU
cls
echo.
echo    v24 自動投票
echo    ------------------------------------------------------
echo     1) check   いま買うべきレースを見るだけ（ブラウザ無し）
echo     2) dry     ブラウザを開き、確認画面まで進んで押さない
echo     3) live    実際に投票する
echo.
echo     8) ログの最後の30行を見る
echo     9) テスト（サイトを触らずに確かめる）
echo     0) 終わる
echo    ------------------------------------------------------
echo.
set N=
set /p N="番号を入れて Enter: "

if "%N%"=="1" goto CHECK
if "%N%"=="2" goto DRY
if "%N%"=="3" goto LIVE
if "%N%"=="8" goto LOG
if "%N%"=="9" goto TEST
if "%N%"=="0" goto END
goto MENU

:CHECK
call :RUN check
goto MENU

:DRY
call :RUN dry
goto MENU

:LIVE
echo.
echo    ★ live は実際にお金を使って投票します。
set YES=
set /p YES="よろしければ y を入れて Enter（やめるなら何も入れずに Enter）: "
if /i not "%YES%"=="y" goto MENU
call :RUN live
goto MENU

:LOG
echo.
if exist "logs\auto_bet.log" (
  powershell -NoProfile -Command "Get-Content -Tail 30 -Encoding UTF8 'logs\auto_bet.log'"
) else (
  echo    まだログがありません。
)
echo.
pause
goto MENU

:TEST
echo.
python run_tests.py
echo.
pause
goto MENU

:RUN
echo.
echo    %1 で動かします。止めるときは Ctrl+C。
echo.
python auto_bet.py --mode %1
set CODE=%ERRORLEVEL%
echo.
if "%CODE%"=="4" (
  echo    ★投票を押した後で分からなくなったため止まりました。
  echo      テレボートの投票履歴を見て、通っているか確認してください。
) else if "%CODE%"=="3" (
  echo    ★bet_done.json が壊れています。直すまで動かさないでください。
) else if "%CODE%"=="2" (
  echo    ★設定か準備が足りません。上のメッセージを見てください。
) else if "%CODE%"=="9009" (
  echo    ★Python が見つかりません。python.org から入れて、
  echo      インストーラ最初の画面の「Add python.exe to PATH」にチェックを。
) else (
  echo    終了しました。
)
echo.
pause
exit /b

:END
