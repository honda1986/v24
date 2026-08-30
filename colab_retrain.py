# ===== モデルを作り直す（消えたので）=====
# pure.npz が残っていれば学習だけ。無ければ Kファイルから作り直す（時間がかかる）。
# できたモデルは /content/model_out と /content/v24/model の両方に置く。

import os
import subprocess

os.chdir("/content")


def sh(*cmd):
    print("$ " + " ".join(cmd), flush=True)
    p = subprocess.Popen(list(cmd), stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in p.stdout:
        print(line, end="", flush=True)
    if p.wait():
        raise SystemExit("★ ここで止まりました。上のエラーを見てください")


for name in ("v22", "v24"):
    if not os.path.isdir(name):
        sh("git", "clone", "--depth", "1",
           f"https://github.com/honda1986/{name}.git")
for d in ("v22/kfile", "v22/raw", "v22/tokuten"):
    if not os.path.isdir(d):
        raise SystemExit(f"★ {d} がありません")
    print(f"  {d:<14} {len(os.listdir(d)):,}件")

if os.path.isfile("pure.npz"):
    print("\npure.npz はあるので作り直しません")
else:
    print("\nKファイルから特徴量を作ります（900日ぶん。時間がかかります）")
    sh("python", "v24/pure.py", "--kfile", "v22/kfile", "--out", "/content/pure.npz")

sh("python", "v24/train.py",
   "--raw", "v22/raw", "--tokuten", "v22/tokuten",
   "--pure", "/content/pure.npz", "--out", "/content/model_out",
   "--cut", "20250316")

# v24 側にも置く（push セルがここを見る）
os.makedirs("/content/v24/model", exist_ok=True)
import shutil
for f in ("lgb_mf.txt", "features.json"):
    src = f"/content/model_out/{f}"
    if os.path.isfile(src):
        shutil.copy2(src, f"/content/v24/model/{f}")
        print(f"  model/{f}  {os.path.getsize(src):,} バイト")

print("\n" + "=" * 60)
print("★『学習に使っていない期間』で 市場 → モデル が下がっているか確認すること。")
print("  下がっていればこのあと push。上がっていたら投入しない。")
print("=" * 60)
