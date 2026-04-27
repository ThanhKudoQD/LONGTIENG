#!/bin/bash
# ═══════════════════════════════════════════════════════
#  train_nhan_vat.sh
#  Dùng:
#    bash train_nhan_vat.sh <actor_id> <ten> "<win_path>" [num_iters] [save_interval] [warmup_steps]
#  Ví dụ — dùng tham số mặc định từ check_dataset:
#    bash train_nhan_vat.sh 1a2b3c4d luc_minh "T:\DIEN_VIEN\export_luc minh_20260420"
#  Ví dụ — truyền tham số tùy chỉnh:
#    bash train_nhan_vat.sh 1a2b3c4d luc_minh "T:\DIEN_VIEN\export_luc minh_20260420" 82 20 8
# ═══════════════════════════════════════════════════════
set -e

# ── Tham số ──
ACTOR_ID="$1"
NAME="$2"
WIN_PATH="$3"
CUSTOM_ITERS="$4"
CUSTOM_SAVE="$5"
CUSTOM_WARMUP="$6"

if [ -z "$ACTOR_ID" ] || [ -z "$NAME" ] || [ -z "$WIN_PATH" ]; then
  echo "Dung: bash train_nhan_vat.sh <actor_id> <ten> \"<win_path>\" [num_iters] [save_interval] [warmup_steps]"
  exit 1
fi

# ── Convert đường dẫn Windows → WSL ──
WSL_PATH=$(echo "$WIN_PATH" | sed 's|\\|/|g' | sed 's|^\([A-Za-z]\):|/mnt/\L\1|')

NANO_DIR="$HOME/nano"
DATASET_DIR="$NANO_DIR/dataset/$NAME"
CONFIG_DIR="$NANO_DIR/configs"
CKPT_DIR="$NANO_DIR/checkpoints/$NAME"
LORA_DIR="$NANO_DIR/loras/$ACTOR_ID"
LOG_DIR="$NANO_DIR/logs/$NAME"
CONFIG_FILE="$CONFIG_DIR/$NAME.yaml"
TEMPLATE="$CONFIG_DIR/_template.yaml"
TRAIN_JSONL="$DATASET_DIR/train.jsonl"

echo ""
echo "======================================================"
echo "  TRAIN LoRA — $NAME  |  ID: $ACTOR_ID"
echo "======================================================"

# ── Kiểm tra ──
[ -d "$NANO_DIR/voxcpm_env" ] || { echo "[X] Khong tim thay voxcpm_env"; exit 1; }
[ -d "$NANO_DIR/VoxCPM2" ]    || { echo "[X] Khong tim thay VoxCPM2";    exit 1; }
[ -f "$TEMPLATE" ]             || { echo "[X] Khong tim thay template: $TEMPLATE"; exit 1; }
[ -d "$WSL_PATH" ]             || { echo "[X] Khong tim thay dataset: $WSL_PATH"; exit 1; }
[ -f "$WSL_PATH/metadata.json" ] || { echo "[X] Khong tim thay metadata.json"; exit 1; }

source "$NANO_DIR/voxcpm_env/bin/activate"

# ── Bước 1: Check dataset + lấy tham số gợi ý ──
echo ""
echo "[1/5] Kiem tra dataset..."
CHECK=$(python "$NANO_DIR/check_dataset.py" "$WIN_PATH" 2>&1)
echo "$CHECK"

# Parse tham số từ output check_dataset
REC_LINE=$(echo "$CHECK" | grep "num_iters=")
REC_ITERS=$(echo "$REC_LINE"  | grep -oP 'num_iters=\K[0-9]+')
REC_SAVE=$(echo "$REC_LINE"   | grep -oP 'save_interval=\K[0-9]+')
REC_WARMUP=$(echo "$REC_LINE" | grep -oP 'warmup_steps=\K[0-9]+')
REC_R=$(echo "$CHECK"         | grep -oP 'LoRA r=\K[0-9]+')

# Dùng tham số truyền vào nếu có, không thì dùng gợi ý
NUM_ITERS=${CUSTOM_ITERS:-${REC_ITERS:-200}}
SAVE_INT=${CUSTOM_SAVE:-${REC_SAVE:-50}}
WARMUP=${CUSTOM_WARMUP:-${REC_WARMUP:-20}}
LORA_R=${REC_R:-32}

echo ""
echo "  => Se dung: num_iters=$NUM_ITERS save_interval=$SAVE_INT warmup_steps=$WARMUP lora_r=$LORA_R"

# ── Bước 2: Copy dataset ──
echo ""
echo "[2/5] Copy dataset tu Windows..."
mkdir -p "$DATASET_DIR"
cp -r "$WSL_PATH/." "$DATASET_DIR/"
echo "  => OK: $DATASET_DIR"

# ── Bước 3: Convert metadata.json → train.jsonl ──
echo ""
echo "[3/5] Convert metadata.json -> train.jsonl..."
python3 - << PYEOF
import json
from pathlib import Path

base   = Path("$DATASET_DIR")
data   = json.loads((base / "metadata.json").read_text(encoding="utf-8"))
out    = open("$TRAIN_JSONL", "w", encoding="utf-8")
count  = 0; skipped = 0

for item in data:
    p   = base / item["file_name"]
    dur = item.get("duration_sec", 99)
    if not p.exists() or dur < 1.0 or dur > 30.0:
        skipped += 1; continue
    out.write(json.dumps({"audio": str(p), "text": item["text"].strip()}, ensure_ascii=False) + "\n")
    count += 1

out.close()
print(f"  => {count} mau, bo qua {skipped} clip")
PYEOF

# ── Bước 4: Tạo yaml ──
echo ""
echo "[4/5] Tao config yaml..."
mkdir -p "$CONFIG_DIR" "$LOG_DIR" "$CKPT_DIR"
cp "$TEMPLATE" "$CONFIG_FILE"
sed -i "s|train_manifest:.*|train_manifest: $TRAIN_JSONL|" "$CONFIG_FILE"
sed -i "s|save_path:.*|save_path: $CKPT_DIR|"             "$CONFIG_FILE"
sed -i "s|tensorboard:.*|tensorboard: $LOG_DIR|"          "$CONFIG_FILE"
sed -i "s|num_iters:.*|num_iters: $NUM_ITERS|"            "$CONFIG_FILE"
sed -i "s|max_steps:.*|max_steps: $NUM_ITERS|"            "$CONFIG_FILE"
sed -i "s|save_interval:.*|save_interval: $SAVE_INT|"     "$CONFIG_FILE"
sed -i "s|warmup_steps:.*|warmup_steps: $WARMUP|"         "$CONFIG_FILE"
sed -i "/^lora:/,/^[^ ]/ s|^  r:.*|  r: $LORA_R|"        "$CONFIG_FILE"
sed -i "/^lora:/,/^[^ ]/ s|^  alpha:.*|  alpha: $LORA_R|" "$CONFIG_FILE"
echo "  => $CONFIG_FILE"

# ── Bước 5: Train ──
echo ""
echo "[5/5] Bat dau train..."
echo "  TensorBoard: tensorboard --logdir $LOG_DIR"
echo ""
cd "$NANO_DIR"
python scripts/train_voxcpm_finetune.py --config_path "$CONFIG_FILE"

# ── Copy LoRA ──
echo ""
echo "======================================================"
echo "  Copy LoRA -> loras/$ACTOR_ID ..."
if [ -d "$CKPT_DIR/latest" ]; then
  mkdir -p "$LORA_DIR"
  cp -r "$CKPT_DIR/latest/." "$LORA_DIR/"
  echo "  [OK] $LORA_DIR"
else
  echo "  [X] Khong tim thay checkpoint/latest!"
  exit 1
fi

echo ""
echo "  HOAN THANH! '$NAME' da co LoRA."
echo "  Actor ID : $ACTOR_ID"
echo "  LoRA     : $LORA_DIR"
echo "======================================================"