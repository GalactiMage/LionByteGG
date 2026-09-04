"""
Generate a beautiful schedule announcement image for Discord.
Uses Pillow to create a week-grid layout with shift details.
"""
import io
import os
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, "..", "LionShiftGGLogo.png")

# Colors (RGB tuples)
BG_DARK = (15, 17, 26)
BG_CARD = (25, 28, 42)
BG_COL_ALT = (21, 23, 34)
AMBER = (245, 158, 11)
ORANGE = (234, 88, 12)
WHITE = (255, 255, 255)
TEXT_PRIMARY = (242, 243, 245)
TEXT_SECONDARY = (180, 183, 191)
TEXT_MUTED = (130, 134, 145)
OPENER_COLOR = (34, 197, 94)
MID_COLOR = (59, 130, 246)
CLOSER_COLOR = (168, 85, 247)
BORDER = (50, 54, 72)
DIVIDER = (40, 43, 58)

TYPE_COLORS = {"opener": OPENER_COLOR, "mid": MID_COLOR, "closer": CLOSER_COLOR}
TYPE_LABELS = {"opener": "OPENER", "mid": "MID", "closer": "CLOSER"}


def _get_font(size, bold=False):
    """Get a font, falling back to default if needed."""
    names = (
        ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"]
        if bold
        else ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"]
    )
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except (OSError, IOError):
            pass
    try:
        path = "C:/Windows/Fonts/" + ("segoeuib.ttf" if bold else "segoeui.ttf")
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _rrect(draw, xy, r, fill=None, outline=None, width=1):
    """Draw a rounded rectangle."""
    draw.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=width)


def _fmt_time(t):
    """'09:00' -> '9:00 AM'"""
    if not t:
        return "?"
    try:
        h, m = map(int, t.split(":"))
        suffix = "AM" if h < 12 else "PM"
        return f"{h % 12 or 12}:{m:02d} {suffix}"
    except Exception:
        return t


def _parse_shift(text):
    """Parse 'Opener: 09:00-13:00 (Worker Name) | Room Name' into (type, start, end, worker, room)."""
    shift_type = "mid"
    time_start = ""
    time_end = ""
    worker = "Unassigned"
    room = ""
    try:
        # Room is appended after a pipe: '... (Worker) | Room Name'
        if "|" in text:
            text, room = text.rsplit("|", 1)
            room = room.strip()
            text = text.strip()
        colon_idx = text.index(":")
        shift_type = text[:colon_idx].strip().lower()
        rest = text[colon_idx + 1:].strip()
        # Extract worker from parentheses
        if "(" in rest and ")" in rest:
            paren_start = rest.index("(")
            paren_end = rest.index(")")
            worker = rest[paren_start + 1:paren_end].strip() or "Unassigned"
            rest = rest[:paren_start].strip()
        # Extract times
        if "-" in rest:
            parts = rest.split("-")
            time_start = parts[0].strip()
            time_end = parts[1].strip()
    except Exception:
        pass
    return shift_type, time_start, time_end, worker, room


def generate_schedule_image(schedule):
    """
    Generate a week-grid schedule announcement image.
    Returns io.BytesIO containing a PNG.
    """
    name = schedule.get("name", "Untitled Schedule")
    start_date = schedule.get("start_date", "?")
    end_date = schedule.get("end_date", "?")
    shift_count = schedule.get("shift_count", 0)
    shift_summary = schedule.get("shift_summary", {})
    allow_offers = schedule.get("allow_offers", True)
    created_by = schedule.get("created_by", "Dashboard Admin")

    # Fonts
    f_title = _get_font(28, True)
    f_sub = _get_font(14)
    f_badge = _get_font(11, True)
    f_stat_num = _get_font(22, True)
    f_stat_lbl = _get_font(10)
    f_col_hdr = _get_font(13, True)
    f_col_day = _get_font(10)
    f_shift_type = _get_font(10, True)
    f_shift_time = _get_font(11)
    f_shift_worker = _get_font(10)
    f_footer = _get_font(11)

    sorted_days = sorted(shift_summary.keys())[:7]
    num_cols = max(len(sorted_days), 1)

    # Layout constants
    WIDTH = 800
    PAD = 28
    GRID_LEFT = PAD
    GRID_RIGHT = WIDTH - PAD
    GRID_W = GRID_RIGHT - GRID_LEFT
    COL_W = GRID_W / num_cols
    HEADER_H = 110
    STATS_H = 64
    COL_HDR_H = 44
    SHIFT_BLOCK_H = 62
    SHIFT_GAP = 6

    # Find max shifts in any day column
    max_shifts = 0
    for day in sorted_days:
        max_shifts = max(max_shifts, len(shift_summary[day][:6]))
    if max_shifts == 0:
        max_shifts = 1

    GRID_BODY_H = max_shifts * (SHIFT_BLOCK_H + SHIFT_GAP) + 12

    # Total height
    HEIGHT = HEADER_H + 10 + STATS_H + 16 + COL_HDR_H + GRID_BODY_H + 20 + 36 + 20
    HEIGHT = max(380, HEIGHT)

    img = Image.new("RGB", (WIDTH, HEIGHT), BG_DARK)
    draw = ImageDraw.Draw(img)

    # ── GRADIENT TOP BAR ──
    for yy in range(4):
        ratio = yy / 4
        r = int(AMBER[0] * (1 - ratio) + ORANGE[0] * ratio)
        g = int(AMBER[1] * (1 - ratio) + ORANGE[1] * ratio)
        b = int(AMBER[2] * (1 - ratio) + ORANGE[2] * ratio)
        draw.line([(0, yy), (WIDTH, yy)], fill=(r, g, b))

    # ── HEADER ──
    _rrect(draw, (PAD - 4, 16, WIDTH - PAD + 4, HEADER_H), r=14, fill=BG_CARD)

    logo_x = PAD + 8
    try:
        if os.path.exists(LOGO_PATH):
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo = logo.resize((40, 40), Image.LANCZOS)
            img.paste(logo, (logo_x, 30), logo)
            logo_x += 50
    except Exception:
        pass

    draw.text((logo_x, 28), "New Schedule Posted!", font=f_title, fill=WHITE)

    # Date subtitle
    date_str = f"{start_date} to {end_date}"
    try:
        if start_date != "?" and end_date != "?":
            sd = datetime.strptime(start_date, "%Y-%m-%d")
            ed = datetime.strptime(end_date, "%Y-%m-%d")
            date_str = f"{sd.strftime('%b %d')} \u2013 {ed.strftime('%b %d, %Y')}"
    except Exception:
        pass
    draw.text((logo_x, 62), date_str, font=f_sub, fill=TEXT_SECONDARY)

    # Name badge (top-right)
    if name:
        nw = draw.textlength(name, font=f_badge) + 16
        bx = WIDTH - PAD - int(nw) - 2
        _rrect(draw, (bx, 34, bx + int(nw), 54), r=8, fill=(40, 35, 20), outline=AMBER)
        draw.text((bx + 8, 37), name, font=f_badge, fill=AMBER)

    y = HEADER_H + 10

    # ── STATS ROW ──
    stats = [
        (str(shift_count), "Total Shifts", MID_COLOR),
        (str(len(sorted_days)), "Days", AMBER),
        ("Yes" if allow_offers else "No", "Trading", OPENER_COLOR if allow_offers else (239, 68, 68)),
    ]
    sw = (GRID_W - 12) // 3
    for i, (val, lbl, clr) in enumerate(stats):
        sx = PAD + i * (sw + 6)
        _rrect(draw, (sx, y, sx + sw, y + STATS_H), r=10, fill=BG_CARD, outline=BORDER)
        # Accent line
        draw.rectangle((sx + 2, y + 2, sx + sw - 2, y + 4), fill=clr)
        # Value centered
        vw = draw.textlength(val, font=f_stat_num)
        draw.text((sx + (sw - vw) // 2, y + 10), val, font=f_stat_num, fill=clr)
        # Label centered
        lw = draw.textlength(lbl, font=f_stat_lbl)
        draw.text((sx + (sw - lw) // 2, y + 40), lbl, font=f_stat_lbl, fill=TEXT_MUTED)

    y += STATS_H + 16

    # ── GRID: COLUMN HEADERS ──
    grid_top = y
    _rrect(draw, (PAD - 2, grid_top, WIDTH - PAD + 2, grid_top + COL_HDR_H + GRID_BODY_H), r=12, fill=BG_CARD, outline=BORDER)

    for i, day in enumerate(sorted_days):
        cx = GRID_LEFT + i * COL_W
        # Alternating column background
        if i % 2 == 1:
            draw.rectangle((int(cx) + 1, grid_top + 1, int(cx + COL_W) - 1, grid_top + COL_HDR_H + GRID_BODY_H - 1), fill=BG_COL_ALT)

        try:
            d = datetime.strptime(day, "%Y-%m-%d")
            weekday = d.strftime("%a").upper()
            month_day = d.strftime("%b %d")
        except Exception:
            weekday = "?"
            month_day = day

        # Column header: weekday + date
        tw = draw.textlength(weekday, font=f_col_hdr)
        draw.text((int(cx + (COL_W - tw) / 2), grid_top + 8), weekday, font=f_col_hdr, fill=WHITE)
        dw = draw.textlength(month_day, font=f_col_day)
        draw.text((int(cx + (COL_W - dw) / 2), grid_top + 25), month_day, font=f_col_day, fill=TEXT_MUTED)

    # Header divider line
    draw.line([(PAD, grid_top + COL_HDR_H), (WIDTH - PAD, grid_top + COL_HDR_H)], fill=DIVIDER, width=1)

    # Column divider lines
    for i in range(1, num_cols):
        lx = int(GRID_LEFT + i * COL_W)
        draw.line([(lx, grid_top), (lx, grid_top + COL_HDR_H + GRID_BODY_H)], fill=DIVIDER, width=1)

    # ── GRID: SHIFT BLOCKS ──
    body_top = grid_top + COL_HDR_H + 8

    for i, day in enumerate(sorted_days):
        cx = GRID_LEFT + i * COL_W
        shifts = shift_summary[day][:6]
        block_x = int(cx) + 6
        block_w = int(COL_W) - 12
        sy = body_top

        for shift_text in shifts:
            stype, t_start, t_end, worker, room = _parse_shift(shift_text)
            clr = TYPE_COLORS.get(stype, MID_COLOR)

            # Shift block background
            _rrect(draw, (block_x, sy, block_x + block_w, sy + SHIFT_BLOCK_H), r=8, fill=BG_DARK, outline=BORDER)
            # Color left accent
            draw.rectangle((block_x + 1, sy + 6, block_x + 4, sy + SHIFT_BLOCK_H - 6), fill=clr)

            # Type label
            type_label = TYPE_LABELS.get(stype, stype.upper())
            draw.text((block_x + 10, sy + 6), type_label, font=f_shift_type, fill=clr)

            # Room label (right-aligned on the type row)
            if room:
                rlabel = room if len(room) <= 16 else room[:14] + ".."
                rw = draw.textlength(rlabel, font=f_shift_type)
                draw.text((block_x + block_w - 8 - rw, sy + 6), rlabel, font=f_shift_type, fill=TEXT_SECONDARY)

            # Time
            time_str = f"{_fmt_time(t_start)} \u2013 {_fmt_time(t_end)}"
            draw.text((block_x + 10, sy + 22), time_str, font=f_shift_time, fill=TEXT_PRIMARY)

            # Worker
            w_display = worker if len(worker) <= 14 else worker[:12] + ".."
            draw.text((block_x + 10, sy + 40), w_display, font=f_shift_worker, fill=TEXT_MUTED)

            sy += SHIFT_BLOCK_H + SHIFT_GAP

    y = grid_top + COL_HDR_H + GRID_BODY_H + 16

    # ── FOOTER ──
    draw.line([(PAD, y), (WIDTH - PAD, y)], fill=DIVIDER, width=1)
    y += 10
    footer = f"LionShiftGG  \u2022  Posted by {created_by}  \u2022  {datetime.now().strftime('%b %d, %Y at %I:%M %p')}"
    draw.text((PAD, y), footer, font=f_footer, fill=TEXT_MUTED)

    # Crop
    final_h = y + 28
    if final_h < HEIGHT:
        img = img.crop((0, 0, WIDTH, final_h))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
