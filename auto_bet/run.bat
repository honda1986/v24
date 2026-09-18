@echo off
rem --------------------------------------------------------------------
rem  v24 auto_bet launcher
rem  ASCII only. cmd.exe cannot read UTF-8 Japanese in .bat files.
rem
rem  MODE:
rem    login ... open Chrome and wait for manual login
rem    check ... list races to bet. no browser, no betting
rem    dry   ... open Chrome, stop at the confirm screen, press nothing
rem    live  ... place real bets (needs i_have_read_the_terms = true)
rem --------------------------------------------------------------------
set MODE=check

chcp 65001 > nul
set PYTHONUTF8=1
cd /d "%~dp0"

python auto_bet.py --mode %MODE%
set CODE=%ERRORLEVEL%
echo.

if "%CODE%"=="4" (
  echo [!] Stopped: a bet was pressed but the result is unknown.
  echo     Check your TELEBOAT bet history before running again.
) else if "%CODE%"=="3" (
  echo [!] bet_done.json is broken. Fix it before running again.
) else if "%CODE%"=="2" (
  echo [!] Setup is incomplete. See the message above.
) else if "%CODE%"=="9009" (
  echo [!] Python not found. Install it from python.org
  echo     and tick "Add python.exe to PATH".
) else (
  echo Finished. (exit code %CODE%)
)
pause
