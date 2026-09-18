@echo off
rem v24 自動投票。ダブルクリックで起動する用。
rem 既定は check（見るだけ）。dry / live にするときは下の MODE を書き換える。
rem   login … 手でログインする（最初の1回と、セッションが切れたとき）
rem   check … ブラウザを開かず、いま買うべきレースを並べるだけ
rem   dry   … ブラウザを開き、確認画面まで進んで押さない
rem   live  … 実際に投票する（config.json の i_have_read_the_terms が true のときだけ）
set MODE=check

chcp 65001 > nul
cd /d "%~dp0"
python auto_bet.py --mode %MODE%
echo.
if errorlevel 4 (
  echo ★投票を押した後で分からなくなったので止まりました。
  echo    テレボートの投票履歴を見て、通っているか確認してください。
) else if errorlevel 3 (
  echo ★bet_done.json が壊れています。直すまで動かさないでください。
) else if errorlevel 2 (
  echo ★設定か準備が足りません。上のメッセージを見てください。
) else (
  echo 終了しました。
)
pause
