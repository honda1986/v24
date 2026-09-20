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

## 1. PC の準備

### 入れるもの

- **Python 3.11**（Actions と同じ版）
- **Git for Windows**
- 仮想環境 `C:\boat\venv`

```
py -3.11 -m venv C:\boat\venv
C:\boat\venv\Scripts\python -m pip install numpy lightgbm requests beautifulsoup4
```

★**lightgbm はモデルを学習したときの版に合わせること。** 違う版だと予測値が
わずかにずれます。Actions の実行ログの `Successfully installed lightgbm-x.y.z`
を見て、`lightgbm==x.y.z` のように版を指定して入れてください。

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

---

## 2. タスクを登録する

PowerShell を**管理者として実行**して:

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
**レースと組の集合**が一致するか。ずれたら、まず lightgbm の版と
文字コード（`PYTHONUTF8`）を疑ってください。

---

## 7. 自動投票を同じ PC で動かすなら

`auto_bet/config.json` の `history_url` を**ローカルのファイル**にできます。

```json
"history_url": "C:\\boat\\v24\\history.json"
```

raw.githubusercontent の5分キャッシュも、push 待ちも無くなります。
yosou が書いている最中は読めないことがありますが、その周は何もせず次へ回ります。

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
