"""
Auto fix overlap — xếp toa tàu các audio bị chồng đè.

Logic:
- Sub đầu chain giữ nguyên
- Các sub sau dán sát (gap = 0)
- Nếu chain đẩy sub kế ngoài chain mà khoảng cách < threshold_anchor → cascade
- Cascade dừng khi gặp khe ≥ threshold_anchor

Tham số:
- overlap_threshold: chồng dưới ngưỡng coi như không đè (default 0.5s)
- threshold_anchor: khe ≥ ngưỡng là an toàn, dừng cascade (default 4s)
"""
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass


@dataclass
class SubInfo:
    id: int
    index: int
    start_time: float
    end_time: float
    audio_offset: float
    wav_duration: Optional[float]
    has_audio: bool

    @property
    def actual_start(self) -> float:
        return self.start_time + self.audio_offset

    @property
    def actual_end(self) -> float:
        dur = self.wav_duration if self.wav_duration else (self.end_time - self.start_time)
        return self.actual_start + dur

    @property
    def duration(self) -> float:
        return self.wav_duration if self.wav_duration else (self.end_time - self.start_time)


@dataclass
class FixChange:
    sub_id: int
    sub_index: int
    old_offset: float
    new_offset: float
    shift: float  # = new - old


def detect_chains(subs: List[SubInfo], overlap_threshold: float) -> List[List[int]]:
    """
    Phát hiện các chain audio đè nhau (chỉ tính sub đã có audio).
    Trả về danh sách các chain — mỗi chain là list index trong `subs`.
    """
    audio_subs_idx = [i for i, s in enumerate(subs) if s.has_audio]
    if len(audio_subs_idx) < 2:
        return []

    # Sort theo actual_start
    audio_subs_idx.sort(key=lambda i: subs[i].actual_start)

    chains: List[List[int]] = []
    current: List[int] = []
    chain_max_end = 0.0

    for idx in audio_subs_idx:
        s = subs[idx]
        if not current:
            current = [idx]
            chain_max_end = s.actual_end
            continue

        # Check overlap với chain hiện tại
        overlap = chain_max_end - s.actual_start
        if overlap > overlap_threshold:
            current.append(idx)
            if s.actual_end > chain_max_end:
                chain_max_end = s.actual_end
        else:
            if len(current) >= 2:
                chains.append(current)
            current = [idx]
            chain_max_end = s.actual_end

    if len(current) >= 2:
        chains.append(current)

    return chains


def compute_fix(
    subs: List[SubInfo],
    overlap_threshold: float = 0.5,
    threshold_anchor: float = 4.0,
) -> Tuple[List[FixChange], List[Dict]]:
    """
    Tính các thay đổi audio_offset cần apply.

    Returns:
      changes: list các thay đổi sẽ apply
      skipped: list chain bị skip kèm lý do (hiện tại không có skip với logic mới)
    """
    if not subs:
        return [], []

    # Sort subs theo actual_start để xử lý từ trái sang phải
    sorted_idx = sorted(range(len(subs)), key=lambda i: subs[i].actual_start if subs[i].has_audio else subs[i].start_time)

    chains = detect_chains(subs, overlap_threshold)
    if not chains:
        return [], []

    # Map từ sub_id -> new_offset (chỉ những sub bị thay đổi)
    new_offsets: Dict[int, float] = {}

    def get_offset(sub_idx: int) -> float:
        """Trả về offset hiện tại (đã update nếu có)"""
        sid = subs[sub_idx].id
        return new_offsets.get(sid, subs[sub_idx].audio_offset)

    def get_actual_start(sub_idx: int) -> float:
        return subs[sub_idx].start_time + get_offset(sub_idx)

    def get_actual_end(sub_idx: int) -> float:
        return get_actual_start(sub_idx) + subs[sub_idx].duration

    skipped = []

    # Xử lý từng chain
    for chain_idx, chain in enumerate(chains):
        # Sub đầu chain GIỮ NGUYÊN — đặt anchor
        anchor = chain[0]
        prev_end = get_actual_end(anchor)

        # Xếp toa các sub còn lại trong chain (dán sát)
        for i in range(1, len(chain)):
            sub_i = chain[i]
            s = subs[sub_i]
            cur_start = get_actual_start(sub_i)
            # Nếu cur_start < prev_end → cần dịch
            if cur_start < prev_end - 0.001:  # epsilon
                shift = prev_end - cur_start
                new_offset = get_offset(sub_i) + shift
                new_offsets[s.id] = new_offset
            prev_end = get_actual_end(sub_i)

        # Cascade: tìm sub kế tiếp ngoài chain
        last_in_chain = chain[-1]
        cur_pos = sorted_idx.index(last_in_chain) if last_in_chain in sorted_idx else -1

        # Tìm next sub theo thứ tự sorted (sau sub cuối chain)
        # Lưu ý: chain có thể có sub không liên tiếp nếu dữ liệu lạ — dùng sorted_idx
        last_chain_indices = set(chain)

        # Tìm sub kế tiếp NGOÀI chain (sau last_in_chain theo time)
        next_sub_idx = None
        last_end_now = get_actual_end(last_in_chain)
        for s_idx in sorted_idx:
            if s_idx in last_chain_indices:
                continue
            if not subs[s_idx].has_audio:
                continue
            if get_actual_start(s_idx) >= subs[last_in_chain].actual_start:
                # Là sub đứng sau anchor, nhưng có thể đã thuộc chain khác xử lý sau
                next_sub_idx = s_idx
                break

        # Cascade — đẩy sub kế tiếp nếu khe < threshold_anchor
        cur_idx = next_sub_idx
        while cur_idx is not None:
            cur_start = get_actual_start(cur_idx)
            gap = cur_start - prev_end
            if gap >= threshold_anchor:
                break  # Đủ xa, dừng cascade
            # Cần đẩy sub này dán sát prev_end
            if cur_start < prev_end - 0.001:
                shift = prev_end - cur_start
                new_offset = get_offset(cur_idx) + shift
                new_offsets[subs[cur_idx].id] = new_offset
            prev_end = get_actual_end(cur_idx)

            # Tìm sub kế tiếp sau cur_idx
            cur_pos_in_sorted = sorted_idx.index(cur_idx)
            next_idx = None
            for j in range(cur_pos_in_sorted + 1, len(sorted_idx)):
                cand = sorted_idx[j]
                if subs[cand].has_audio:
                    next_idx = cand
                    break
            cur_idx = next_idx

    # Build danh sách changes
    changes: List[FixChange] = []
    for s in subs:
        if s.id in new_offsets:
            new_off = new_offsets[s.id]
            if abs(new_off - s.audio_offset) > 0.001:  # chỉ tính thay đổi đáng kể
                changes.append(FixChange(
                    sub_id=s.id,
                    sub_index=s.index,
                    old_offset=s.audio_offset,
                    new_offset=round(new_off, 3),
                    shift=round(new_off - s.audio_offset, 3),
                ))

    return changes, skipped


def summarize(changes: List[FixChange], chains: List[List[int]], total_audio: int) -> Dict:
    """Tóm tắt cho preview."""
    if not changes:
        return {
            "total_chains": len(chains),
            "total_audio_in_chains": sum(len(c) for c in chains),
            "subs_affected": 0,
            "max_shift": 0.0,
            "avg_shift": 0.0,
        }
    shifts = [abs(c.shift) for c in changes]
    max_change = max(changes, key=lambda c: abs(c.shift))
    return {
        "total_chains": len(chains),
        "total_audio_in_chains": sum(len(c) for c in chains),
        "subs_affected": len(changes),
        "max_shift": round(max(shifts), 3),
        "avg_shift": round(sum(shifts) / len(shifts), 3),
        "max_shift_sub": {"index": max_change.sub_index, "shift": max_change.shift},
    }
