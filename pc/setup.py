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
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    out = (p.stdout or "") + (p.stderr or "")
    if not quiet and out.strip():
        for line in out.strip().splitlines()[-12:]:
            say("   |", line)
    return p.returncode == 0, out


def ng(msg, how=""):
    say("  ×", msg)
    if how:
        for line in how.splitlines():
            say("    ", line)
    problems.append(msg)


# --------------------------------------------------------------------------
def check_git():
    step(1, "Git があるか")
    ok, out = run(["git", "--version"], quiet=True)
    if not ok:
        ng("Git for Windows が入っていません",
           "https://git-scm.com/download/win から入れて、\n"
           "もう一度 setup.bat をダブルクリックしてください。")
        return False
    say("  ○", out.strip())
    return True


def check_python():
    step(2, "Python の版")
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
    step(3, "改行の設定（ここが狂うと記録が壊れる）")
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
    step(4, "v22（Kファイルと確定オッズ）")
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
    step(5, "Python の入れ物（venv）")
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
    step(6, "ライブラリ（numpy / lightgbm / requests / bs4）")
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
    """lightgbm の版ずれが怖いので、モデルが本当に読めるかここで確かめる"""
    step(7, "モデルが読めるか")
    code = (
        "import lightgbm as lgb, json;"
        "b = lgb.Booster(model_file=r'%s');"
        "print('lightgbm', lgb.__version__, '/ 木の数', b.num_trees())"
        % os.path.join(REPO, "model", "lgb_mf.txt")
    )
    ok, out = run([PY, "-c", code], cwd=REPO, quiet=True)
    if not ok:
        ng("モデルを読めませんでした",
           out.strip().splitlines()[-1] if out.strip() else "")
        return False
    say("  ○", out.strip())
    return True


def make_logs():
    step(8, "ログの置き場")
    os.makedirs(LOGS, exist_ok=True)
    say("  ○", LOGS)
    return True


def set_topic():
    """ntfy の宛先。GitHub Secrets の NTFY_TOPIC と同じ値"""
    step(9, "通知の宛先（ntfy）")
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
    step(10, "動くかどうかの確かめ")
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


def trial():
    """本番と同じ道すじを、通知もせず push もせずに1回だけ通してみる"""
    step(11, "試し運転（通知しない・push しない）")
    ok, out = run([PY, "runner.py", "yosou", "--dry", "--no-push",
                   "--v22", V22, "--log-dir", LOGS], cwd=REPO)
    if not ok:
        ng("試し運転に失敗しました",
           f"{LOGS} のログを見てください。")
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
    if not check_python():
        return finish()
    fix_eol()
    fetch_v22()
    if not make_venv():
        return finish()
    if not install_libs():
        return finish()
    check_model()
    make_logs()
    set_topic()
    if self_tests():
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
        for p in problems:
            say("   ・", p)
        say("")
        say("  直したら、この setup.bat をもう一度ダブルクリックしてください。")
    say("=" * 56)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
