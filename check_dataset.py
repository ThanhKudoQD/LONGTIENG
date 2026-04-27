"""
check_dataset.py — Kiểm tra dataset và gợi ý tham số train
Dùng: python check_dataset.py "T:\DIEN_VIEN\export_luc minh_20260420"
"""
import json, sys, wave
from pathlib import Path

def get_duration(path):
    try:
        with wave.open(str(path), 'r') as f:
            return f.getnframes() / f.getframerate()
    except:
        return -1

def fmt(sec):
    m, s = divmod(int(sec), 60)
    return f"{m}m{s:02d}s"

def to_wsl(win_path):
    p = win_path.replace('\\', '/')
    if len(p) >= 2 and p[1] == ':':
        drive = p[0].lower()
        p = f"/mnt/{drive}{p[2:]}"
    return p

if len(sys.argv) < 2:
    print('Dùng: python check_dataset.py "T:\\DIEN_VIEN\\export_luc minh_20260420"')
    sys.exit(1)

base_dir  = Path(to_wsl(sys.argv[1]))
if not base_dir.exists():
    print(f"❌ Không tìm thấy: {base_dir}"); sys.exit(1)

meta_file = base_dir / "metadata.json"
if not meta_file.exists():
    print(f"❌ Không tìm thấy metadata.json trong: {base_dir}"); sys.exit(1)

data = json.loads(meta_file.read_text(encoding="utf-8"))

durations, missing, too_short, too_long, ok_clips = [], [], [], [], []

for item in data:
    fpath = base_dir / item["file_name"]
    dur   = item.get("duration_sec") or get_duration(fpath)
    if not fpath.exists() or dur < 0:
        missing.append(item["file_name"]); continue
    durations.append(dur)
    if dur < 3.0:    too_short.append((item["file_name"], dur))
    elif dur > 30.0: too_long.append((item["file_name"], dur))
    else:            ok_clips.append(dur)

total     = len(durations)
n         = len(ok_clips)
avg_dur   = sum(durations) / total if total else 0
total_dur = sum(durations)

print()
print("=" * 50)
print(f"  DATASET: {base_dir.name}")
print("=" * 50)
print(f"  Tong clip        : {total}")
print(f"  Tong thoi luong  : {fmt(total_dur)} ({total_dur/60:.1f} phut)")
print(f"  Thoi luong TB    : {avg_dur:.2f}s")
print(f"  Clip dat chuan   : {n} clip (3-30s)")
if missing:   print(f"  [!] File thieu   : {len(missing)} clip")
if too_short: print(f"  [!] Qua ngan <3s : {len(too_short)} clip")
if too_long:  print(f"  [!] Qua dai >30s : {len(too_long)} clip")

if n < 5:
    print("\n[X] Qua it clip de train (can it nhat 5 clip dat chuan)!")
    sys.exit(1)
elif n <= 20:  epochs, r = 3, 32
elif n <= 50:  epochs, r = 2, 32
elif n <= 150: epochs, r = 1, 32
else:          epochs, r = 1, 64

steps_per_epoch = max(1, n // 4)
num_iters       = steps_per_epoch * epochs
save_interval   = max(20, num_iters // 4)
warmup_steps    = max(10, num_iters // 10)

print()
print("-" * 50)
print(f"  GOI Y THAM SO TRAIN ({epochs} epoch, {n} clip)")
print("-" * 50)
print(f"  num_iters={num_iters} save_interval={save_interval} warmup_steps={warmup_steps}")
print()
print(f"  LoRA r={r}  |  ~{steps_per_epoch} steps/epoch")
print("=" * 50)
print()