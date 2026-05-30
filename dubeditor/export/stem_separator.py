"""
Stem Separator — tách audio từ video gốc thành 3 stem (bass, drums, vocals).
Sử dụng Demucs với model mdx_extra_q (quantized, fast, GPU support).

Workflow:
  1. ffmpeg trích audio từ video → .wav 44.1kHz stereo
  2. demucs apply_model → 4 stem (bass, drums, other, vocals)
  3. Lưu bass.wav, drums.wav, vocals.wav (bỏ other.wav)
  4. Trả về 3 path cho FE upload vào BGM list

API: separate_video_stems(video_path, output_dir, project_id, progress_callback)
"""
import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional, Callable, Dict

logger = logging.getLogger(__name__)

# Lazy import demucs (chỉ load khi cần — model nặng)
_demucs_model = None
_demucs_lock = threading.Lock()

# Output stems để giữ (bỏ 'other')
KEEP_STEMS = ['bass', 'drums', 'vocals']

# Model: fastest GPU-supported
DEMUCS_MODEL_NAME = 'mdx_extra_q'


def _get_demucs_model():
    """Load demucs model 1 lần (cached). Auto-detect cuda → cpu."""
    global _demucs_model
    with _demucs_lock:
        if _demucs_model is not None:
            return _demucs_model
        try:
            import torch
            from demucs.pretrained import get_model
        except ImportError as e:
            raise RuntimeError(
                "Demucs chưa cài. Chạy: pip install demucs --break-system-packages"
            ) from e

        logger.info(f"[StemSep] Loading model: {DEMUCS_MODEL_NAME}")
        model = get_model(DEMUCS_MODEL_NAME)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(device)
        model.eval()
        _demucs_model = model
        logger.info(f"[StemSep] Model loaded on {device}. Sources: {model.sources}")
        return model


def check_demucs_available() -> Dict[str, any]:
    """Kiểm tra Demucs + GPU. Trả info cho FE để show trạng thái."""
    info = {
        'demucs_installed': False,
        'cuda_available': False,
        'device': 'cpu',
        'model': DEMUCS_MODEL_NAME,
        'error': None,
    }
    try:
        import demucs
        info['demucs_installed'] = True
    except ImportError:
        info['error'] = 'Demucs chưa cài (pip install demucs)'
        return info
    try:
        import torch
        info['cuda_available'] = torch.cuda.is_available()
        info['device'] = 'cuda' if info['cuda_available'] else 'cpu'
    except ImportError:
        info['error'] = 'PyTorch chưa cài'
    return info


def _extract_audio_from_video(video_path: str, out_wav: str) -> None:
    """ffmpeg trích audio từ video → wav 44.1kHz stereo."""
    cmd = [
        'ffmpeg', '-y', '-loglevel', 'error',
        '-i', video_path,
        '-vn', '-ac', '2', '-ar', '44100',
        '-c:a', 'pcm_s16le',
        out_wav,
    ]
    logger.info(f"[StemSep] Extract audio: {video_path} → {out_wav}")
    subprocess.run(cmd, check=True, capture_output=True)


def separate_video_stems(
    video_path: str,
    output_dir: str,
    project_id: int,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> Dict[str, str]:
    """
    Tách video → 3 stem (bass, drums, vocals).

    Args:
        video_path: path video gốc
        output_dir: folder lưu output stem
        project_id: dùng để đặt tên file
        progress_callback: fn(progress: 0-1, message: str)

    Returns:
        {'bass': path, 'drums': path, 'vocals': path}
    """
    def cb(p: float, m: str):
        if progress_callback:
            try:
                progress_callback(p, m)
            except Exception:
                pass
        logger.info(f"[StemSep] {p*100:.0f}% — {m}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Check cache
    cache_paths = {
        stem: output_dir / f"stem_{project_id}_{stem}.wav"
        for stem in KEEP_STEMS
    }
    if all(p.exists() and p.stat().st_size > 1000 for p in cache_paths.values()):
        cb(1.0, f"Đã có cache, dùng lại 3 stem")
        return {k: str(v) for k, v in cache_paths.items()}

    cb(0.05, "Trích audio từ video...")

    with tempfile.TemporaryDirectory(prefix='nano_stemsep_') as tmpdir:
        tmpdir = Path(tmpdir)
        audio_wav = tmpdir / "input.wav"
        try:
            _extract_audio_from_video(video_path, str(audio_wav))
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"ffmpeg extract audio failed: {e.stderr.decode()[-500:]}")

        if not audio_wav.exists() or audio_wav.stat().st_size < 1000:
            raise RuntimeError("Audio extract thất bại hoặc rỗng")

        cb(0.15, "Đang tải model Demucs...")

        # Import lazy
        import torch
        import torchaudio
        from demucs.apply import apply_model
        from demucs.audio import convert_audio

        model = _get_demucs_model()
        device = next(model.parameters()).device

        cb(0.25, f"Đang tách stem trên {device.type.upper()}...")

        # Load audio
        wav, sr = torchaudio.load(str(audio_wav))
        wav = convert_audio(wav, sr, model.samplerate, model.audio_channels)

        # Normalize like demucs CLI
        ref = wav.mean(0)
        ref_mean = ref.mean()
        ref_std = ref.std() + 1e-8
        wav_norm = (wav - ref_mean) / ref_std

        # Apply model. split=True để chia segment tránh OOM. progress=False (không in stdout).
        # shifts=0 → fastest. overlap=0.25 default.
        with torch.no_grad():
            sources = apply_model(
                model,
                wav_norm[None].to(device),
                shifts=0,
                split=True,
                overlap=0.25,
                progress=False,
                device=device,
            )[0]
        # Denormalize
        sources = sources * ref_std + ref_mean

        cb(0.85, "Đang lưu stem...")

        # model.sources = ['drums', 'bass', 'other', 'vocals'] thường
        # Lưu file theo KEEP_STEMS, bỏ 'other'
        result_paths = {}
        for i, name in enumerate(model.sources):
            if name not in KEEP_STEMS:
                continue
            stem_tensor = sources[i].cpu()
            out_path = cache_paths[name]
            torchaudio.save(
                str(out_path),
                stem_tensor,
                model.samplerate,
                encoding='PCM_S',
                bits_per_sample=16,
            )
            result_paths[name] = str(out_path)
            cb(0.85 + 0.05 * (len(result_paths) / 3),
               f"Đã lưu {name}.wav ({out_path.stat().st_size // 1024} KB)")

        cb(1.0, f"Hoàn tất — tách được {len(result_paths)} stem")
        return result_paths
