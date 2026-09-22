# 定期実行を PC で回す

GitHub Actions がやっていた `motor` / `prefetch` / `yosou` を、Windows の
タスクスケジューラで回します。GitHub には `daily`（夜の集計）と
`watchdog`（PC が止まっていないかの見張り）だけを残します。

```
Windows PC（C:\boat）                         GitHub（honda1986/v24）
  06:00         motor                          Pages（予想サイト）… そのまま
  07/10/13:00   prefetch        push →         daily.yml    23:50  … そのまま
  07:57〜23:57  yosou（3分おき）                watchdog.yml 毎時   … 新設
  runner.py が取り込み→実行→保存→push          yosou/motor/prefetch … 手動だけ残す
```

---

## 0. かんたん手順（ふつうはこれだけ）

### ① 一度だけ、コマンドプロンプトに貼る

```
git config --global core.autocrlf false && git clone https://github.com/honda1986/v24.git C:\boat\v24
```

### ② `C:\boat\v24\pc\setup.bat` をダブルクリック

venv・ライブラリ・v22・ログ置き場・通知の宛先を用意し、テストと試し運転まで
やります。**通知もしないし push もしません。** 何度やり直しても壊れません。

### ③ `C:\boat\v24\pc\tasks.bat` を右クリック →「管理者として実行」

毎日の予定を登録して、1回動かしてログを見せます。ここまでで終わりです。

うまくいかなかったら、画面に出た字をそのまま貼って相談してください。
下の §1 以降は、中で何をしているかの説明です。

---

## 1. PC の準備（setup.bat が中でやっていること）

### 入れるもの

- **Python 3.11**（Actions と同じ版）
- **Git for Windows**
- 仮想環境 `C:\boat\venv`

```
py -3.11 -m venv C:\boat\venv
C:\boat\venv\Scripts\python -m pip install numpy lightgbm requests beautifulsoup4
```

lightgbm は **4系**なら何でもよい。`model/lgb_mf.txt` は文字で書かれた
モデル（`version=v4`）で、木の形がそのまま入っているので、4系のどれで読んでも
同じ値が出ます。3系では読めません。

`setup.bat` は入れたあとに**実際にモデルを読んでみて**、木の数を表示します。
そこが通れば版の心配はいりません。

### フォルダ

```
C:\boat\
  venv\     Python
  v24\      このリポジトリ（作業フォルダ）
  v22\      Kファイルと確定オッズ（読むだけ）
  logs\     runner のログ
```

```
git config --global core.autocrlf false      ← ★clone する前に
git clone https://github.com/honda1986/v24.git C:\boat\v24

git clone --filter=blob:none --sparse https://github.com/honda1986/v22.git C:\boat\v22
cd C:\boat\v22
git sparse-checkout set kfile raw
```

`core.autocrlf` を false にしないと、改行が CRLF に変わって
history.json が毎回「全行変更」になり、統合が壊れます。

### 文字コード

`PYTHONUTF8=1` を必ず設定します（`pc\task.bat` が設定しています）。
Windows の Python は既定で cp932 で読み書きするので、日本語の JSON が化けます。

### 通知先

`NTFY_TOPIC` をユーザー環境変数に入れます（GitHub Secrets と同じ値）。

```
setx NTFY_TOPIC "あなたのトピック名"
```

### 電源と時計

- スリープ **なし**、ノートは「カバーを閉じたとき **何もしない**」
- Windows Update の**アクティブ時間を 6:00〜24:00** に（勝手な再起動が最大の停止原因）
- タイムゾーン **(UTC+09:00) 大阪、札幌、東京**、「時刻を自動的に設定する」オン

### GitHub への push

fine-grained PAT（対象 `v24` だけ、Contents の Read and write、期限1年）を作り、
最初の push で聞かれたら入力します。Git Credential Manager が覚えます。
**トークンをファイルや環境変数に書かないこと。**

★**必ず画面のある窓で1回済ませること。** `setup.bat` の「GitHub に書き込めるか」が
その段です。タスクスケジューラには画面が無いので、そこで初めて認証を求められると
**窓を出せずに固まります**（2026-09-20 に実機で起きました。ログが push の手前で
止まり、次の周からはずっと「まだ動いています」で飛ばされました）。

runner.py 側でも `GIT_TERMINAL_PROMPT=0` などを渡して、git に人を待たせないように
してあります。認証が無ければ黙って「push できず(次周に持ち越し)」になります。

---

## 2. タスクを登録する

`pc\tasks.bat` を**右クリック →「管理者として実行」**。中でこれを叩いています:

```
cd C:\boat\v24\pc
powershell -ExecutionPolicy Bypass -File .\register_tasks.ps1
```

| タスク | 起動 | 打ち切り |
|---|---|---|
| `boat_motor` | 毎日 6:00（失敗したら15分後に3回まで） | 60分 |
| `boat_prefetch` | 毎日 7:00 / 10:00 / 13:00 | 30分 |
| `boat_yosou` | 毎日 7:57 から**3分おきに16時間**（23:57まで） | 10分 |

共通の設定（`register_tasks.ps1` が入れています）:
ログオンしていなくても実行 / スリープを解除して実行 / バッテリーでも実行 /
**既に実行中なら新しく始めない**。

手で登録する場合は、**開始（作業フォルダ）を `C:\boat\v24`** にしてください。
既定の `C:\Windows\System32` のままだとファイルが見つかりません。

### ★登録したら、3つ揃っているか必ず数えること

```
powershell -c "Get-ScheduledTask boat_* | Format-Table TaskName, State"
```

`boat_motor` / `boat_prefetch` / `boat_yosou` の**3つ**が `Ready` で出ること。

2026-09-20〜09-22 に、**`boat_motor` だけが登録されていなかった**ことがあります。
`register_tasks.ps1` の `RestartInterval` の書式が正しくなく
（`00:15:00` ではなく `PT15M` でなければならない）、`RestartCount` を使うのは
motor だけなので、**motor だけが赤いエラーで飛ばされ、残り2つは登録されて
スクリプトは最後まで走っていました**。

そのあいだ yosou は動いていたので通知は普通に来ていて、
**結果（的中・払戻）とモーター純度だけが2日ぶん止まっている**ことに
誰も気づけませんでした。いまは
- `register_tasks.ps1` が最後に3つ揃ったかを数えて、足りなければ止まる
- `daily.py`（GitHub 側・23:50）が「結果が2日以上入っていない」「モーター純度が古い」で鳴る

の2段で拾えるようにしてあります。

### なぜ yosou を「3分おきに1回ずつ」にするか

GitHub では「3時間走り続けるジョブの中でループ」でした（起動が当てにならないため）。
PC では起動が当てになるので、**1回ごとに終わる**ほうが強い作りです。途中で落ちても
失うのは3分ぶんだけで、次の周が勝手に拾います。

---

## 3. runner.py が1回にやること

```
python runner.py yosou      （task.bat が呼びます）
```

1. **二重起動の防止**（`logs\yosou.lock`。古いロックは無視）
2. **リモートの取り込み** — 予備運転で GitHub 側が進んでいたら拾う
3. **本体を動かす** — `yosou.py --budget 150` など。引数は `.github/workflows/*.yml` と同じ
4. **commit して push** — 失敗しても何も消さない。次の周がまた push する
5. **ログ** — `C:\boat\logs\<タスク>_<日付>.log`

### 取り込みの決まり（ここが肝）

- `history.json` … **`merge_history.py` で意味を見て統合**（git には混ぜさせない）
- `state/notified_*.json` … **和集合**。どちらかで通知済みなら通知済み
- `cache/` `motor/` `state/` のそれ以外 … ローカル優先

`git rebase` / `merge -X theirs` / `push --force` は使いません。
history.json は1行の JSON なので、git に混ぜさせると settle が入れた
的中・払戻が黙って消えます（メモ §26）。

**`notified` を和集合にしているのは GitHub の `save()` より良くしてある点です。**
PC と GitHub の両方が動いた日に、片方の通知済みが消えて二重通知になるのを防ぎます。

### 手で動かすとき

```
cd C:\boat\v24
C:\boat\venv\Scripts\python runner.py yosou --dry          通知しない
C:\boat\venv\Scripts\python runner.py yosou --no-push      push しない
```

| 終了コード | 意味 |
|---|---|
| 0 | 正常 |
| 1 | 本体が失敗（途中までを commit して終わる） |
| 2 | もう動いていたので何もしなかった |
| 3 | フォルダの指定が違う |

---

## 4. GitHub 側

### watchdog（新設・追加済み）

毎時 JST 9:00〜23:00 に `history.json` を読み、

- 今日の日付が無い → 「今日は一度も動いていません」
- `last_run` が30分以上前 → 「◯分止まっています」

を ntfy（優先度5）で知らせます。**読むだけで、commit も push もしません。**
`push` が失敗し続けているだけでも鳴ります（文面にそう書いてあります）。

止まっている間は毎時鳴ります。気づくまで鳴らすのが目的です。

### daily（そのまま）

23:50 の集計通知。「今日 yosou が1回も動いていない」を検知できるので、
**夜の最後の砦**です。

### yosou / motor / prefetch の schedule（2026-09-20 に消しました）

3つとも `on:` から `schedule:` を消し、`workflow_dispatch:` だけ残しました。
＝定期では動かず、スマホから手動で動かせる予備運転になります。

★**効くのは main に入ってからです。** GitHub の定期実行は
**既定のブランチ（main）の .yml だけ**を見ます。作業ブランチで消しても、
main に古い `schedule:` が残っている限り GitHub は動き続けます。
watchdog も同じで、main に入るまで鳴りません。

**つまり「main への取り込み」が切り替えの瞬間です。** PC のタスクを
登録して動くことを確かめてから取り込んでください。逆にすると、
どちらも動かない時間ができます。

戻したくなったら、各 `.yml` の `on:` に `schedule:` を書き戻して main に入れ、
**同時に PC のタスクを無効にします**（`Disable-ScheduledTask -TaskName boat_yosou` など）。
両方が定期で動く日を作らないこと。

---

## 5. PC が止まったとき（予備運転）

1. watchdog の警告が来る
2. すぐ直せないなら、スマホで GitHub → v24 → Actions → **yosou → Run workflow**
3. 3時間5分ぶん動きます

**PC を戻すときの順番**（間違えると二重通知・二重投票になります）:

1. GitHub 側の yosou が**終わっている**ことを確認（動いていれば Cancel）
2. それから PC のタスクを再開
3. runner の取り込みが、予備運転の記録と通知済みを PC に持ってきます

---

## 6. 移行の手順

| 段階 | やること | 合格 |
|---|---|---|
| 0 | 上の準備。`python selftest.py` と `python select_rule.py` | 両方「すべて通りました」 |
| 1 | 3日間の並走。GitHub はそのまま、PC は `--dry` で3分おき | 同じレースに同じ組が出る |
| 2 | PC タスクを有効にし、動いたのを見てから main に取り込む | その日のうちに通知とサイト更新 |
| 3 | 昼に yosou タスクを1時間止める | watchdog の警告が1〜2時間以内 |
| 4 | PC を止めてスマホから Run workflow → 戻す | 二重通知が出ない |
| 5 | 昼間に PC を再起動 | ログオンしなくてもタスクが再開する |

段階1の比べ方: GitHub 側の通知（または history.json の `picks` / `ana`）と、
PC の `--dry` のログに出る「★N点 …」「穴N点(試験) …」を突き合わせ、
**レースと組の集合**が一致するか。ずれたら、まず文字コード（`PYTHONUTF8`）と
モーター純度（`motor/latest.json` の日付）を疑ってください。

---

## 7. 自動投票を同じ PC で動かすなら

**何もしなくてもそうなります。** `auto_bet/` は v24 の中にあるので、
`history_path`（既定 `../history.json`）が同じ PC の history.json を指します。
raw.githubusercontent の5分キャッシュも push 待ちも無くなり、締切ぎりぎりの
レースにも間に合います。

手元のファイルを使うのは「今日のぶんがあって `last_run` が30分以内」のときだけ。
書き込み中だったり、別のフォルダに残った古い clone だったりすれば、黙って
`history_url`（GitHub）に切り替わります。買い目を取りこぼしません。

`auto_bet/config.json` は git で配っていません（`config.example.json` が見本で、
無ければ起動時に作られます）。配ってしまうと、runner の `reset --hard` で毎回
もとに戻されるか、「データ以外が変わっている」と見なされて取り込みが止まります。

自動投票のタスクは画面付きの Chrome を使うので、
**「ユーザーがログオンしているときのみ実行」**にしてください（他のタスクと違います）。

---

## 8. 確かめる

```
cd C:\boat\v24
C:\boat\venv\Scripts\python pc_selftest.py
```

runner の取り込み（通知済みの和集合・settle の結果が消えないこと）、ロック、
push 失敗、文字コード、改行、watchdog の判定を、GitHub にも競艇サイトにも
触らずに確かめます。
