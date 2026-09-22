# register_tasks.ps1 -- タスクスケジューラに3つ登録する
#
#   PowerShell を「管理者として実行」して:
#     cd C:\boat\v24\pc
#     powershell -ExecutionPolicy Bypass -File .\register_tasks.ps1
#
# 仕様書 §4-2 の設定をそのまま入れてあります。
# 消すとき: Unregister-ScheduledTask -TaskName boat_yosou -Confirm:$false

param([string]$Boat = "C:\boat")

$bat = Join-Path $Boat "v24\pc\task.bat"
if (-not (Test-Path $bat)) { throw "$bat がありません" }

function New-BoatTask {
    param($Name, $Arg, $Triggers, [int]$LimitMinutes, [int]$RestartCount = 0)

    $action = New-ScheduledTaskAction -Execute $bat -Argument $Arg `
                                      -WorkingDirectory (Join-Path $Boat "v24")
    $settings = New-ScheduledTaskSettingsSet `
        -WakeToRun `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes $LimitMinutes) `
        -StartWhenAvailable
    if ($RestartCount -gt 0) {
        # ★RestartInterval は「PT15M」の形（ISO 8601）で入れること。
        #   New-TimeSpan を後から代入すると XML に "00:15:00" と書かれ、
        #   Register-ScheduledTask が
        #     「タスク XML に、書式設定が正しくない値または範囲外の値が
        #       含まれています。(43,28):Interval:00:15:00」
        #   で落ちる。-ExecutionTimeLimit のようにコマンドレットの引数で
        #   渡すぶんには変換されるが、後からの代入は変換されない。
        #
        #   ★これを踏んだせいで boat_motor だけ登録されていなかった
        #     （2026-09-20〜09-22）。RestartCount を使うのは motor だけなので、
        #     prefetch と yosou は成功し、motor だけが黙って飛ばされていた。
        #     Register-ScheduledTask のエラーは終了させない種類なので、
        #     スクリプトはそのまま残り2つを登録して最後まで走ってしまう。
        $settings.RestartCount = $RestartCount
        $settings.RestartInterval = "PT15M"
    }
    # ユーザーがログオンしていなくても動かす
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
                 -LogonType S4U -RunLevel Limited

    # ★-ErrorAction Stop を付けること。既定では登録に失敗しても赤い字が
    #   出るだけでスクリプトは続き、「登録しました」も出ないまま次へ行く。
    #   最後の確認コマンドを打たないと、1つ足りないことに気づけない。
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $Triggers `
        -Settings $settings -Principal $principal -Force -ErrorAction Stop | Out-Null
    Write-Host "登録しました: $Name"
}

# 06:00 モーター純度と前日の取り込み（失敗したら15分後に3回まで）
New-BoatTask -Name "boat_motor" -Arg "motor" -LimitMinutes 60 -RestartCount 3 `
    -Triggers (New-ScheduledTaskTrigger -Daily -At 6:00am)

# 07:00 / 10:00 / 13:00 出走表の先取り
New-BoatTask -Name "boat_prefetch" -Arg "prefetch" -LimitMinutes 30 -Triggers @(
    (New-ScheduledTaskTrigger -Daily -At 7:00am),
    (New-ScheduledTaskTrigger -Daily -At 10:00am),
    (New-ScheduledTaskTrigger -Daily -At 1:00pm)
)

# 07:57 から3分おきに16時間（23:57 まで）
$yosou = New-ScheduledTaskTrigger -Daily -At 7:57am
$yosou.Repetition = (New-ScheduledTaskTrigger -Once -At 7:57am `
    -RepetitionInterval (New-TimeSpan -Minutes 3) `
    -RepetitionDuration (New-TimeSpan -Hours 16)).Repetition
New-BoatTask -Name "boat_yosou" -Arg "yosou" -LimitMinutes 10 -Triggers $yosou

# ★登録し終わったら、自分で数えて確かめる。
#   人間が確認コマンドを打つのを当てにしない（打たなかったので2日気づけなかった）
Write-Host ""
$want = @("boat_motor", "boat_prefetch", "boat_yosou")
$have = @(Get-ScheduledTask -TaskName $want -ErrorAction SilentlyContinue |
          Select-Object -ExpandProperty TaskName)
$miss = @($want | Where-Object { $_ -notin $have })
if ($miss.Count -gt 0) {
    Write-Host "★登録できていないタスクがあります: $($miss -join ', ')" -ForegroundColor Red
    throw "タスクが $($miss.Count) 個足りません"
}
Write-Host "3つとも登録できています: $($have -join ', ')" -ForegroundColor Green

Write-Host ""
Write-Host "確認:  Get-ScheduledTask boat_* | Format-Table TaskName, State"
Write-Host "試す:  Start-ScheduledTask -TaskName boat_yosou"
Write-Host "       そのあと C:\boat\logs\yosou_<日付>.log を見る"
