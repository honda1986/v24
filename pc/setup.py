#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""setup.py -- PC で定期実行を始めるための下ごしらえを、まとめてやる

    pc\\setup.bat をダブルクリックすると、これが動く。

何度やり直しても壊れないように書いてある（もうあるものは作り直さない）。
途中で転んだら、直してからもう一度ダブルクリックすればよい。

★ここでやらないこと
  - タスクの登録（管理者権限が要るので pc\\tasks.bat に分けてある）
  - GitHub への push（試し運転は --no-push。人が確かめてから本番にする）
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)                 # C:\boat\v24
BOAT = os.path.dirname(REPO)                 # C:\boat
VENV = os.path.join(BOAT, "venv")
V22 = os.path.join(BOAT, "v22")
LOGS = os.path.join(BOAT, "logs")

WIN = os.name == "nt"
PY = (os.path.join(VENV, "Scripts", "python.exe") if WIN
      else os.path.join(VENV, "bin", "python"))

LIBS = ["numpy", "lightgbm>=4", "requests", "beautifulsoup4"]

problems = []       # 「あとで人が直すこと」を貯めておく


def say(*a):
    print(*a, flush=True)


def step(n, title):
    say("")
    say(f"--- {n} {title} " + "-" * max(0, 46 - len(title)))


def run(args, cwd=None, quiet=False):
    """外のコマンドを1回叩く。(うまくいったか, 出力) を返す"""
    env = dict(os.environ, PYTHONUTF8="1")
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env)
    except OSError as e:
        # コマンドそのものが無いとき。ここで落とすと画面が真っ赤になって
        # 何が悪いのか分からなくなるので、失敗として返すだけにする。
        return False, f"{args[0]} を動かせません: {e}"
    out = (p.stdout or "") + (p.stderr or "")
    if not quiet and out.strip():
        for line in out.strip().splitlines()[-12:]:
            say("   |", line)
    return p.returncode == 0, out


def run_live(args, cwd=None):
    """画面を取り上げずに動かす

    ★capture_output を使わないこと。GitHub のログインを聞かれたとき、
      その字が見えないまま固まる。実機でタスクが固まったのと同じ理屈。
    """
    try:
        return subprocess.run(args, cwd=cwd,
                              env=dict(os.environ, PYTHONUTF8="1")).returncode
    except OSError as e:
        say("   |", f"{args[0]} を動かせません: {e}")
        return 1


def ng(msg, how=""):
    say("  ×", msg)
    if how:
        for line in how.splitlines():
            say("    ", line)
    problems.append((msg, how))


def detail(out, keep=10):
    """外のコマンドが吐いた中身を、そのまま見せるために整える

    ★1行だけに削らないこと。Windows の DLL まわりの失敗は、
      最後の行だけ見ても何も分からない。
    """
    lines = [l.rstrip() for l in (out or "").strip().splitlines() if l.strip()]
    text = "\n".join(lines[-keep:])
    low = (out or "").lower()
    if "winerror 126" in low or "dll load failed" in low:
        text += ("\n★Visual C++ の部品が足りません。これを貼って入れてください:"
                 "\n    winget install --id Microsoft.VCRedist.2015+.x64 -e")
    return text or "（何も出ませんでした）"


# --------------------------------------------------------------------------
# Git を入れても PATH に入らないことがある（インストール時の選択による）。
# よくある置き場を自分で見に行く。
GIT_DIRS = [
    r"C:\Program Files\Git\cmd",
    r"C:\Program Files (x86)\Git\cmd",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Git\cmd"),
    os.path.join(os.environ.get("PROGRAMFILES", ""), r"Git\cmd"),
]


def find_git():
    """PATH に無ければ、よくある置き場から探して PATH に足す"""
    ok, out = run(["git", "--version"], quiet=True)
    if ok:
        return True, out.strip()
    for d in GIT_DIRS:
        if d and os.path.exists(os.path.join(d, "git.exe")):
            os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + d
            ok, out = run(["git", "--version"], quiet=True)
            if ok:
                return True, out.strip() + f"（{d} で見つけました）"
    return False, ""


def check_git():
    step(1, "Git があるか")
    ok, out = find_git()
    if not ok:
        ng("Git for Windows が入っていません",
           "コマンドプロンプトに貼って入れてください:\n"
           "    winget install --id Git.Git -e\n"
           "それができなければ https://git-scm.com/download/win から。\n"
           "入れたあと、この setup.bat をもう一度ダブルクリック。")
        return False
    say("  ○", out)
    return True


def update_self():
    """この setup.py 自身が古いことがある。まず新しくしてから進む

    直しを入れるたびに「git pull して」と頼むのは無理があるので、
    ここで勝手に追いつく。失敗しても止めない（ネットが無いだけかもしれない）。
    """
    step(3, "v24 を最新にする")
    ok, out = run(["git", "pull", "--ff-only", "--quiet"], cwd=REPO, quiet=True)
    if ok:
        say("  ○ 最新にしました")
        return True
    say("  ! 新しくできませんでした（このまま進みます）")
    for line in detail(out, 3).splitlines():
        say("   |", line)
    return True


def check_python():
    step(4, "Python の版")
    v = sys.version_info
    say(f"  ○ Python {v.major}.{v.minor}.{v.micro}")
    if v < (3, 9):
        ng(f"Python が古すぎます（{v.major}.{v.minor}）",
           "python.org から 3.11 を入れてください。")
        return False
    if (v.major, v.minor) != (3, 11):
        say("  ※ GitHub 側は 3.11 で動いています。ふつうは動きますが、")
        say("     おかしくなったら 3.11 を疑ってください。")
    return True


def fix_eol():
    """改行が CRLF に化けていないか。化けていると history.json の統合が壊れる"""
    step(2, "改行の設定（ここが狂うと記録が壊れる）")
    run(["git", "config", "--global", "core.autocrlf", "false"], quiet=True)
    run(["git", "config", "core.autocrlf", "false"], cwd=REPO, quiet=True)
    say("  ○ core.autocrlf = false にしました")

    path = os.path.join(REPO, "history.json")
    if not os.path.exists(path):
        return True
    with open(path, "rb") as f:
        head = f.read(200000)
    if b"\r\n" not in head:
        say("  ○ history.json は LF のまま（正常）")
        return True

    say("  ! CRLF に化けていました。元に戻します")
    run(["git", "rm", "--cached", "-r", "-q", "."], cwd=REPO, quiet=True)
    ok, _ = run(["git", "reset", "--hard"], cwd=REPO, quiet=True)
    with open(path, "rb") as f:
        again = b"\r\n" in f.read(200000)
    if not ok or again:
        ng("改行を直せませんでした",
           f"{REPO} を消して、clone からやり直すのが確実です。")
        return False
    say("  ○ 直りました")
    return True


def fetch_v22():
    step(5, "v22（Kファイルと確定オッズ）")
    if os.path.isdir(os.path.join(V22, ".git")):
        say("  ○ もうあります:", V22)
        run(["git", "pull", "--quiet"], cwd=V22, quiet=True)
        return True
    say("  … 取ってきます（少し待ちます）")
    ok, _ = run(["git", "clone", "--filter=blob:none", "--sparse",
                 "https://github.com/honda1986/v22.git", V22])
    if not ok:
        ng("v22 を取れませんでした",
           "motor（毎朝6時）だけが動かなくなります。あとで直せます。")
        return False
    ok, _ = run(["git", "sparse-checkout", "set", "kfile", "raw"], cwd=V22)
    if not ok:
        ng("v22 の sparse-checkout に失敗しました")
        return False
    say("  ○ 用意できました:", V22)
    return True


def make_venv():
    step(6, "Python の入れ物（venv）")
    if os.path.exists(PY):
        say("  ○ もうあります:", VENV)
        return True
    say("  … 作ります")
    ok, _ = run([sys.executable, "-m", "venv", VENV])
    if not ok or not os.path.exists(PY):
        ng("venv を作れませんでした")
        return False
    say("  ○ 作りました:", VENV)
    return True


def install_libs():
    step(7, "ライブラリ（numpy / lightgbm / requests / bs4）")
    have = {}
    ok, out = run([PY, "-m", "pip", "list", "--format=freeze"], quiet=True)
    if ok:
        for line in out.splitlines():
            if "==" in line:
                name, _, ver = line.partition("==")
                have[name.strip().lower()] = ver.strip()
    need = [lib for lib in LIBS
            if re.split(r"[><=]", lib)[0].lower() not in have]
    if not need:
        for lib in LIBS:
            name = re.split(r"[><=]", lib)[0]
            say(f"  ○ {name} {have[name.lower()]}")
        return True
    say("  … 入れます（数分かかります）")
    ok, _ = run([PY, "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
                quiet=True)
    ok, _ = run([PY, "-m", "pip", "install", "--quiet", *LIBS])
    if not ok:
        ng("ライブラリを入れられませんでした",
           "ネットが繋がっているか見てください。")
        return False
    run([PY, "-m", "pip", "list", "--format=freeze"], quiet=True)
    say("  ○ 入りました")
    return True


def check_model():
    """モデルが本当に読めるかを、どこで転んだか分かる形で確かめる

    ★まとめて1回で試さないこと。前は「モデルを読めませんでした」としか
      出せず、ライブラリが悪いのかファイルが無いのか分からなかった。
    """
    step(8, "モデルが読めるか")

    for mod in ("numpy", "lightgbm"):
        ok, out = run([PY, "-c", f"import {mod};print({mod}.__version__)"],
                      cwd=REPO, quiet=True)
        if not ok:
            ng(f"{mod} を読み込めません", detail(out))
            return False
        say(f"  ○ {mod} {out.strip()}")

    path = os.path.join(REPO, "model", "lgb_mf.txt")
    if not os.path.exists(path):
        ng(f"モデルのファイルがありません: {path}",
           "clone が途中で切れたのかもしれません。\n"
           f"    cd {REPO}\n"
           "    git status\n"
           "を見せてください。")
        return False
    say(f"  ○ ファイルはあります（{os.path.getsize(path) // 1024} KB）")

    code = ("import lightgbm as lgb;"
            "b = lgb.Booster(model_file=r'%s');"
            "print('trees', b.num_trees())" % path)
    ok, out = run([PY, "-c", code], cwd=REPO, quiet=True)
    if not ok:
        ng("モデルを読み込めません", detail(out))
        return False
    say("  ○ 読めました:", out.strip())
    return True


def make_logs():
    step(9, "ログの置き場")
    os.makedirs(LOGS, exist_ok=True)
    say("  ○", LOGS)
    return True


def set_topic():
    """ntfy の宛先。GitHub Secrets の NTFY_TOPIC と同じ値"""
    step(10, "通知の宛先（ntfy）")
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if topic:
        say("  ○ もう入っています:", topic[:3] + "***")
        return True
    say("  スマホに通知を出すための合言葉（NTFY_TOPIC）を入れてください。")
    say("  GitHub の Settings → Secrets → NTFY_TOPIC と同じ値です。")
    say("  分からなければ、何も入れずに Enter（あとで入れられます）。")
    try:
        topic = input("  NTFY_TOPIC> ").strip()
    except EOFError:
        topic = ""
    if not topic:
        ng("NTFY_TOPIC を入れていません（通知が出ません）",
           'あとから: setx NTFY_TOPIC "合言葉"')
        return True
    run(["setx", "NTFY_TOPIC", topic] if WIN else ["true"], quiet=True)
    os.environ["NTFY_TOPIC"] = topic
    say("  ○ 入れました（次に開く窓から効きます）")
    return True


def self_tests():
    step(11, "動くかどうかの確かめ")
    for name, script in (("本体", "selftest.py"), ("PC移行ぶん", "pc_selftest.py")):
        say(f"  … {name}（{script}）")
        ok, out = run([PY, script], cwd=REPO, quiet=True)
        last = [l for l in out.strip().splitlines() if l.strip()][-3:]
        for line in last:
            say("   |", line)
        if not ok:
            ng(f"{script} が通りませんでした",
               "上の行が手がかりです。そのまま貼って相談してください。")
            return False
        say(f"  ○ {name} は通りました")
    return True


def check_push():
    """GitHub のログインを、画面のある今のうちに済ませる

    ★これを飛ばすと、毎日の自動実行が1回目の push で固まる。
      タスクスケジューラには画面が無いので、合言葉を聞く窓を出せない。
      （2026-09-20 に実機で起きた。ログが push の手前で止まり、
        次の周からはずっと「まだ動いています」で飛ばされた）
    """
    step(12, "GitHub に書き込めるか（ログイン）")
    say("  ログイン（ブラウザが開くか、合言葉の入力）を求められたら答えてください。")
    say("  一度答えれば Windows が覚えるので、次からは聞かれません。")
    say("")
    code = run_live(["git", "push", "--dry-run", "-q", "origin",
                     "HEAD:refs/heads/pc-setup-probe"], cwd=REPO)
    say("")
    if code != 0:
        ng("GitHub に書き込めません",
           "v24 に書き込める PAT が要ります。\n"
           "  GitHub → Settings → Developer settings →\n"
           "  Personal access tokens → Fine-grained tokens\n"
           "  対象は v24 だけ / Contents を Read and write / 期限1年\n"
           "★トークンはどのファイルにも書かないこと。Windows が覚えます。")
        return False
    say("  ○ 書き込めます（何も変えていません。ためしただけです）")
    return True


def trial():
    """本番とまったく同じ道すじを1回通す（通知だけしない）"""
    step(13, "試し運転（通知しないだけで、あとは本番と同じ）")
    code = run_live([PY, "runner.py", "yosou", "--dry",
                     "--v22", V22, "--log-dir", LOGS], cwd=REPO)
    if code == 2:
        say("  ! もう動いていたので、この回は何もしませんでした（異常ではありません）")
        return True
    if code != 0:
        ng("試し運転に失敗しました", f"{LOGS} のログを見てください。")
        return False
    say("  ○ 通りました")
    return True


def main():
    say("=" * 56)
    say("  v24 を PC で動かす準備をします")
    say("  場所:", BOAT)
    say("=" * 56)

    if not check_git():
        return finish()
    fix_eol()
    update_self()
    if not check_python():
        return finish()
    fetch_v22()
    if not make_venv():
        return finish()
    if not install_libs():
        return finish()
    check_model()
    make_logs()
    set_topic()
    if self_tests() and check_push():
        trial()
    return finish()


def finish():
    say("")
    say("=" * 56)
    if not problems:
        say("  ぜんぶ済みました。")
        say("")
        say("  次は pc\\tasks.bat を『右クリック → 管理者として実行』。")
        say("  それで毎日ひとりでに動くようになります。")
    else:
        say("  終わりましたが、直すところがあります:")
        # ★ここで中身まで出し直す。画面を遡らなくても、この囲みを貼れば
        #   何が起きたか分かるようにしておくこと。
        for msg, how in problems:
            say("")
            say("   ・", msg)
            for line in (how or "").splitlines():
                say("       ", line)
        say("")
        say("  直したら、この setup.bat をもう一度ダブルクリックしてください。")
    say("=" * 56)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
