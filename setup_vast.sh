#!/usr/bin/env bash
# ============================================================================
#  setup_vast.sh  —  CHẠY TRÊN MÁY VAST (Ubuntu)
#  Dựng môi trường khớp đúng máy local của bạn rồi chạy server.
#
#  Yêu cầu instance Vast:
#    - GPU >= 12GB (khuyên RTX 4090 / 3090 24GB)
#    - CUDA driver >= 550 (để chạy torch cu124). Lọc "CUDA Version >= 12.4".
#    - Mở cổng 8809 (điền vào ô port khi tạo instance).
#
#  Dùng:
#    tar -xzf nano_deploy.tar.gz -C ~/nano   # đã giải nén code vào ~/nano
#    cd ~/nano && bash setup_vast.sh
# ============================================================================
set -euo pipefail

# ── CONFIG (sửa nếu cần) ──
ENV_NAME="nano"
PY_VER="3.10"                       # PHẢI là 3.10 — flash_attn wheel là cp310
APP_DIR="${APP_DIR:-$HOME/nano}"
MODEL_REPO="openbmb/VoxCPM2"
MODEL_DIR="$APP_DIR/VoxCPM2"
PORT="${PORT:-8809}"
GPU_MEM="${GPU_MEM:-0.85}"          # 24GB card để 0.85; 12GB để 0.75
FLASH_WHL="https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.4.post1/flash_attn-2.7.4.post1+cu12torch2.5cxx11abiFALSE-cp310-cp310-linux_x86_64.whl"

echo "==================================================================="
echo " Nano deploy on Vast  |  env=$ENV_NAME py=$PY_VER port=$PORT"
echo "==================================================================="

# ── 1. System deps ──
echo "[1/7] apt: ffmpeg, git, wget ..."
export DEBIAN_FRONTEND=noninteractive
( sudo apt-get update -y && sudo apt-get install -y ffmpeg git wget ) \
  || ( apt-get update -y && apt-get install -y ffmpeg git wget )

# ── 2. Conda (cài miniconda nếu chưa có) ──
if ! command -v conda >/dev/null 2>&1; then
  echo "[2/7] Cài Miniconda ..."
  wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/mc.sh
  bash /tmp/mc.sh -b -p "$HOME/miniconda3"
  export PATH="$HOME/miniconda3/bin:$PATH"
fi
source "$(conda info --base)/etc/profile.d/conda.sh"

# ── 3. Tạo env py3.10 ──
echo "[3/7] Tạo conda env $ENV_NAME (python $PY_VER) ..."
conda create -y -n "$ENV_NAME" python="$PY_VER" || true
conda activate "$ENV_NAME"
pip install -U pip

# ── 4. torch 2.5.1 + cu124 (index riêng của PyTorch) ──
echo "[4/7] torch 2.5.1 cu124 ..."
pip install torch==2.5.1 torchaudio==2.5.1 \
  --index-url https://download.pytorch.org/whl/cu124

# ── 5. flash-attn (WHEEL BUILD SẴN — không build từ source) + nano-vllm ──
echo "[5/7] flash-attn (prebuilt) + nano-vllm-voxcpm ..."
pip install "$FLASH_WHL"
pip install nano-vllm-voxcpm==2.0.0

# ── 6. Phần còn lại + (tùy chọn) demucs ──
echo "[6/7] requirements.txt ..."
cd "$APP_DIR"
pip install -r requirements.txt
# Bỏ comment dòng dưới nếu muốn tính năng tách nhạc nền (Demucs):
# pip install -r requirements-optional.txt

# Kiểm tra torch không bị nâng version ngoài ý muốn
python - <<'PY'
import torch, flash_attn
print("  torch:", torch.__version__, "| cuda ok:", torch.cuda.is_available())
print("  gpu  :", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "NONE")
print("  flash_attn:", flash_attn.__version__)
PY

# ── 7. Tải model VoxCPM2 từ HuggingFace (nếu chưa có) ──
if [ ! -f "$MODEL_DIR/model.safetensors" ]; then
  echo "[7/7] Tải model $MODEL_REPO -> $MODEL_DIR (~5GB) ..."
  pip install -U "huggingface_hub[cli]"
  huggingface-cli download "$MODEL_REPO" --local-dir "$MODEL_DIR"
else
  echo "[7/7] Model đã có sẵn ở $MODEL_DIR — bỏ qua tải."
fi

echo ""
echo "==================================================================="
echo " ✅ Cài xong. Khởi động server:"
echo "==================================================================="
echo "   conda activate $ENV_NAME"
echo "   cd $APP_DIR"
echo "   python app.py --model-id ./VoxCPM2 --host 0.0.0.0 --port $PORT --gpu-mem $GPU_MEM"
echo ""
echo " UI:  http://<VAST_IP>:$PORT/app     API docs: http://<VAST_IP>:$PORT/docs"
echo ""
read -r -p "Chạy server luôn bây giờ? [y/N] " ans
if [[ "${ans:-N}" =~ ^[Yy]$ ]]; then
  exec python app.py --model-id ./VoxCPM2 --host 0.0.0.0 --port "$PORT" --gpu-mem "$GPU_MEM"
fi
