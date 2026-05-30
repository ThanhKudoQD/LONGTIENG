#!/usr/bin/env bash
# ============================================================================
#  pack_for_vast.sh  —  CHẠY Ở MÁY LOCAL (WSL), trong thư mục ~/nano
#  Tạo 1 tarball SẠCH để upload lên Vast.
#
#  Cố tình LOẠI BỎ:
#    - private_key.pem   (KHÓA KÝ LICENSE — TUYỆT ĐỐI KHÔNG ĐƯA LÊN VAST)
#    - VoxCPM2/          (5GB — sẽ tải lại từ HuggingFace trên Vast)
#    - .git, *.bak*, __pycache__, *.pyc
#    - checkpoints/ dataset/ logs/ release/  (đồ train, không cần để chạy)
#
#  Dùng:  bash pack_for_vast.sh
#  Kết quả: nano_deploy.tar.gz  (kéo lên Vast bằng scp)
# ============================================================================
set -euo pipefail

SRC="${1:-$HOME/nano}"
OUT="nano_deploy.tar.gz"

cd "$SRC"

# An toàn: cảnh báo nếu private key tồn tại (vẫn loại khỏi gói)
if [ -f private_key.pem ]; then
  echo "⚠️  Phát hiện private_key.pem — nó SẼ BỊ LOẠI khỏi gói (đúng như mong muốn)."
fi

tar -czf "/tmp/$OUT" \
  --exclude='private_key.pem' \
  --exclude='./VoxCPM2' \
  --exclude='./.git' \
  --exclude='*.bak' \
  --exclude='*.bak_*' \
  --exclude='*.bak[0-9]*' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='./release' \
  --exclude='./checkpoints' \
  --exclude='./dataset' \
  --exclude='./logs' \
  --exclude='./COPY_CODE' \
  --exclude='./node_modules' \
  --exclude='**/node_modules' \
  --exclude='pyarmor.bug.log' \
  --exclude='run.bat' \
  .

mv "/tmp/$OUT" "./$OUT"

echo ""
echo "✅ Tạo xong: $SRC/$OUT"
echo "   Dung lượng: $(du -h "$OUT" | cut -f1)"
echo ""
echo "Kiểm tra KHÔNG có private key trong gói:"
if tar -tzf "$OUT" | grep -q 'private_key.pem'; then
  echo "❌ NGUY HIỂM: private_key.pem VẪN còn trong gói — DỪNG LẠI!"
  exit 1
else
  echo "   ✓ Không có private_key.pem — an toàn."
fi
echo ""
echo "Tiếp theo, upload lên Vast (thay PORT/HOST theo instance của bạn):"
echo "   scp -P <SSH_PORT> $OUT root@<VAST_IP>:/root/"
