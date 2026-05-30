"""
ASS Subtitle generator — gen file .ass từ subs + style + clips (mapping output time).

ASS format chuẩn FFmpeg dùng được trực tiếp với filter `subtitles=file.ass`.
Reference: http://www.tcax.org/docs/ass-specs.htm
"""
from typing import List, Tuple, Optional
from .config_types import SubtitleStyle, VideoClip, PaddingConfig


def hex_to_ass_color(hex_color: str, alpha: float = 1.0) -> str:
    """
    Convert hex CSS color (#RRGGBB) → ASS BGR with alpha.
    Format: &H<AA><BB><GG><RR> (alpha 0=opaque, 0xFF=transparent)
    """
    h = hex_color.lstrip('#')
    if len(h) == 3:
        h = ''.join(c*2 for c in h)
    try:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
    except (ValueError, IndexError):
        r, g, b = 255, 255, 255
    a = int((1.0 - max(0.0, min(1.0, alpha))) * 255)
    return f"&H{a:02X}{b:02X}{g:02X}{r:02X}"


def fmt_ass_time(seconds: float) -> str:
    """Format time as H:MM:SS.CS (centiseconds)."""
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    cs = int((s - int(s)) * 100)
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


def map_source_to_output_time(
    source_time: float,
    clips: List[VideoClip],
) -> Optional[float]:
    """
    Map source time → output time.
    Returns None nếu source time không nằm trong clip nào.
    Nếu clips rỗng, source = output.
    """
    if not clips:
        return source_time
    sorted_clips = sorted(clips, key=lambda c: c.source_start)
    acc = 0.0
    for c in sorted_clips:
        if c.source_start <= source_time <= c.source_end:
            return acc + (source_time - c.source_start)
        acc += max(0.0, c.source_end - c.source_start)
    return None


def build_subtitle_ass(
    subs: List[dict],            # [{id, start_time, end_time, text}]
    style: SubtitleStyle,
    clips: List[VideoClip],
    padding: PaddingConfig,
    output_width: int,
    output_height: int,
) -> str:
    """
    Build ASS file content.

    Args:
      subs: list dicts {id, start_time, end_time, text} - thời gian source
      style: SubtitleStyle
      clips: list VideoClip để map source → output time
      padding: dùng để tính MarginV (sub không bị padding đè)
      output_width, output_height: kích thước final output (px)
    """
    # ─── Compute style values ────────────────────────────────────────────────
    primary = hex_to_ass_color(style.color, 1.0)
    outline = hex_to_ass_color(style.outline_color, 1.0) if style.outline_enabled else '&H00000000'
    back    = (hex_to_ass_color(style.background_color, style.background_opacity)
               if style.background_enabled else '&H00000000')

    # Border style: 1 = outline + shadow, 3 = opaque box background
    border_style = 3 if style.background_enabled else 1
    outline_w = style.outline_width if style.outline_enabled else 0
    shadow = style.shadow_blur if style.shadow_enabled else 0

    # Alignment ASS (numpad): 1-3 bottom, 4-6 middle, 7-9 top. Center: 2/5/8.
    alignment_map = {'top': 8, 'middle': 5, 'bottom': 2}
    alignment = alignment_map[style.position]

    bold = '-1' if style.bold else '0'
    italic = '-1' if style.italic else '0'

    # Font name: ASS không hỗ trợ Be Vietnam Pro với dấu — đảm bảo có sẵn ở server
    # Fallback nếu font không tìm thấy
    font_name = style.font_family
    font_size = style.font_size

    # ─── REFERENCE RESOLUTION TRICK ──────────────────────────────────────────
    # ASS có PlayResX/PlayResY là "virtual resolution". libass scale font/margin
    # theo TỈ LỆ output_height/PlayResY thật khi render.
    #
    # Để font_size user nhập = px ở reference "chiều ngắn 1080" (khớp Preview FE):
    #   - Tính PlayRes sao cho min(PlayResX, PlayResY) = 1080
    #   - Giữ tỉ lệ aspect đúng với output thật
    if output_width >= output_height:
        # Ngang: chiều ngắn = height
        play_res_y = 1080
        play_res_x = int(round(output_width * 1080 / max(1, output_height)))
    else:
        # Dọc: chiều ngắn = width
        play_res_x = 1080
        play_res_y = int(round(output_height * 1080 / max(1, output_width)))

    # ─── MarginV (sau khi biết PlayResY) ─────────────────────────────────────
    # User nhập padding.height_px và style.y_offset theo reference 1080.
    # MarginV trong ASS dùng cùng đơn vị với PlayResY. Khi PlayResY != 1080
    # (vd output dọc → PlayResY = 1920), phải scale lên.
    # Padding overlay drawbox cũng scale theo out_h/1080 — phải khớp.
    margin_scale = play_res_y / 1080.0

    if style.position == 'bottom':
        # Sub mặc định sát padding bottom (MarginV = padBotH khi y_offset=0)
        # y_offset > 0 → đẩy XUỐNG (giảm MarginV)
        # y_offset < 0 → đẩy LÊN (tăng MarginV)
        pad_bot = padding.bottom.height_px if padding.bottom.enabled else 0
        margin_v_raw = pad_bot - style.y_offset
        margin_v = int(round(margin_v_raw * margin_scale))
    elif style.position == 'top':
        pad_top = padding.top.height_px if padding.top.enabled else 0
        margin_v_raw = pad_top + style.y_offset
        margin_v = int(round(margin_v_raw * margin_scale))
    else:
        # middle: dùng y_offset trực tiếp (ASS center sub không có khái niệm MarginV chính xác)
        margin_v = 0

    # ─── ASS header ──────────────────────────────────────────────────────────
    header = f"""[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: {play_res_x}
PlayResY: {play_res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary},&H000000FF,{outline},{back},{bold},{italic},0,0,100,100,0,0,{border_style},{outline_w},{shadow},{alignment},20,20,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # ─── Build events ────────────────────────────────────────────────────────
    events: List[str] = []
    for sub in subs:
        text = (sub.get('text') or '').strip()
        if not text:
            continue
        # Skip nếu text là placeholder
        if text.startswith('[CHƯA') or text.startswith('[UNTRANSLATED'):
            continue

        src_start = float(sub.get('start_time') or 0)
        src_end   = float(sub.get('end_time') or src_start)

        # Map source → output time
        out_start = map_source_to_output_time(src_start, clips)
        out_end   = map_source_to_output_time(src_end, clips)

        # Nếu start hoặc end không nằm trong clip nào → skip
        if out_start is None or out_end is None:
            continue
        if out_end <= out_start:
            continue

        # Escape text: thay \n bằng \N (ASS line break), escape các ký tự đặc biệt
        # ASS không support nhiều markup, chỉ \N
        safe_text = (text
                     .replace('\\', '\\\\')
                     .replace('\n', '\\N')
                     .replace('{', '\\{')
                     .replace('}', '\\}'))

        events.append(
            f"Dialogue: 0,{fmt_ass_time(out_start)},{fmt_ass_time(out_end)},Default,,0,0,0,,{safe_text}"
        )

    return header + '\n'.join(events) + '\n'
