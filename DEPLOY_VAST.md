# Deploy Nano lên Vast.ai

Mục tiêu: chạy được server (dịch + TTS VoxCPM2 + export) trên GPU thuê. Chạy code gốc, không obfuscate.

## Tóm tắt 5 bước

1. **Local (WSL):** đóng gói code sạch → `nano_deploy.tar.gz`
2. **Vast:** thuê instance đúng tiêu chí
3. **Vast:** upload code + LoRA giọng
4. **Vast:** chạy `setup_vast.sh` (dựng môi trường + tải model)
5. **Vast:** mở cổng, vào UI

---

## Bước 1 — Đóng gói ở máy local (WSL)

Copy 4 file này vào `~/nano`: `requirements.txt`, `requirements-optional.txt`, `setup_vast.sh`, `pack_for_vast.sh`. Rồi:

```bash
cd ~/nano
bash pack_for_vast.sh
```

Script tự loại `private_key.pem`, thư mục `VoxCPM2` (5GB), `.git`, các file `.bak`, đồ train. Cuối cùng nó tự kiểm tra chắc chắn **không có private key** trong gói. Kết quả: `~/nano/nano_deploy.tar.gz`.

> LoRA giọng bạn tự train (`loras/`, `configs/*.yaml`, `voices.json`) **được giữ trong gói** vì đó là tài sản của bạn và cần để chạy giọng tùy chỉnh. Base model VoxCPM2 thì tải lại trên Vast.

## Bước 2 — Thuê instance Vast đúng tiêu chí

Khi lọc máy trên vast.ai, chọn:

- **GPU:** RTX 4090 24GB (ngọt nhất) hoặc RTX 3090 24GB. Tối thiểu 12GB.
- **CUDA Version ≥ 12.4** (bắt buộc — torch của bạn build cu124, cần driver ≥ 550).
- **Disk ≥ 30GB** (model 5GB + môi trường ~8GB + chỗ làm việc).
- **Image:** một image Ubuntu có CUDA, ví dụ `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04` hoặc template PyTorch bất kỳ. Script sẽ tự dựng env Python 3.10 riêng nên image gốc dùng Python nào cũng được.
- **Open Ports:** thêm `8809` vào ô port khi tạo instance (nếu không sẽ không vào được UI từ ngoài).

Chọn host có nhiều review tốt, datacenter-tier (vì code chạy trên máy người lạ).

## Bước 3 — Upload code lên Vast

Lấy lệnh SSH/scp ở trang instance (Vast cho port SSH riêng, thường không phải 22):

```bash
# Từ máy local:
scp -P <SSH_PORT> nano_deploy.tar.gz root@<VAST_IP>:/root/

# SSH vào Vast:
ssh -p <SSH_PORT> root@<VAST_IP>

# Trên Vast: giải nén vào ~/nano
mkdir -p ~/nano && tar -xzf /root/nano_deploy.tar.gz -C ~/nano
```

## Bước 4 — Dựng môi trường + tải model

```bash
cd ~/nano
bash setup_vast.sh
```

Script làm tuần tự: cài `ffmpeg` → tạo conda env Python 3.10 → torch 2.5.1 cu124 → **flash-attn wheel build sẵn** (không build từ source, nhanh) → `nano-vllm-voxcpm` → requirements → tải `openbmb/VoxCPM2` (~5GB) từ HuggingFace. Cuối cùng nó hỏi có chạy server luôn không.

Lần đầu mất ~5–10 phút (chủ yếu là tải model + cài torch).

## Bước 5 — Chạy & truy cập

Nếu chưa chạy tự động:

```bash
conda activate nano
cd ~/nano
python app.py --model-id ./VoxCPM2 --host 0.0.0.0 --port 8809 --gpu-mem 0.85
```

- **UI:** `http://<VAST_IP>:8809/app`
- **API docs:** `http://<VAST_IP>:8809/docs`

(`<VAST_IP>` và cổng public lấy ở trang instance, mục "Open Ports" — Vast có thể map 8809 ra một cổng ngoài khác.)

---

## Tính năng tùy chọn (cài thêm khi cần)

- **Tách nhạc nền (Demucs):** `pip install -r requirements-optional.txt`. Không có nó server vẫn chạy, chỉ nút tách stem báo unavailable.
- **Auto-assign speaker (diarization):** bỏ comment `pyannote.audio` trong `requirements-optional.txt`. Nặng, và cần HF token + accept điều khoản 2 model `pyannote/...` trên HuggingFace.

## Lưu ý quan trọng

- **`private_key.pem` không bao giờ lên Vast.** Server chỉ cần `public_key.pem` để verify license. (Script pack đã tự loại.)
- **Dữ liệu là tạm thời.** Khi bạn tắt/hủy instance Vast, mọi thứ trên đĩa mất. Nếu muốn giữ DB/audio đã tạo, dùng "Stop" thay vì "Destroy", hoặc tải file kết quả về.
- **Bảo mật:** đổi biến môi trường `JWT_SECRET` (mặc định trong code là `voicecast_secret_change_me`):
  ```bash
  export JWT_SECRET="chuoi-bi-mat-cua-ban"
  python app.py ...
  ```
- **Xóa sạch sau khi test:** vì máy của người lạ, làm xong nên Destroy instance để không còn code/LoRA của bạn nằm lại.

## Khi gặp lỗi

- `flash_attn` cài lỗi → kiểm tra `python --version` phải là **3.10** (env conda `nano` đã active chưa?). Wheel là cp310.
- `torch.cuda.is_available()` = False → host driver quá cũ; chọn lại máy có CUDA ≥ 12.4.
- Server bật rồi nhưng không vào được UI → chưa mở cổng 8809 ở instance, hoặc đang gõ nhầm cổng public Vast map ra.
- TTS lỗi OOM → giảm `--gpu-mem` (vd 0.70) hoặc chọn GPU VRAM lớn hơn.
