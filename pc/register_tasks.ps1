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
        $settings.RestartCount = $RestartCount
        $settings.RestartInterval = (New-TimeSpan -Minutes 15)
    }
    # ユーザーがログオンしていなくても動かす
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
                 -LogonType S4U -RunLevel Limited

    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $Triggers `
        -Settings $settings -Principal $principal -Force | Out-Null
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

Write-Host ""
Write-Host "確認:  Get-ScheduledTask boat_* | Format-Table TaskName, State"
Write-Host "試す:  Start-ScheduledTask -TaskName boat_yosou"
Write-Host "       そのあと C:\boat\logs\yosou_<日付>.log を見る"
