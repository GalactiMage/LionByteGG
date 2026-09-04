#!/usr/bin/env python3
"""LionByteGG — cinematic Matrix startup intro."""
import sys, time, random, os

# ── Windows: ANSI + UTF-8 ────────────────────────────────────────────────────
os.system('')
if sys.platform == 'win32':
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ── ANSI ─────────────────────────────────────────────────────────────────────
RST = "\033[0m"
W   = "\033[97m"       # bright white
G0  = "\033[32;2m"     # dim green  (far tail)
G1  = "\033[32m"       # green      (mid tail)
G2  = "\033[92m"       # bright green (near tail)
GH  = "\033[97;1m"     # white      (drop head)
GO  = "\033[93;1m"     # bold gold  (logo)
GY  = "\033[90m"       # dark grey
HID = "\033[?25l"
SHW = "\033[?25h"
CLS = "\033[2J\033[H"
EL  = "\033[2K"
UP  = lambda n: f"\033[{n}A"

GLYPHS = list(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    "0123456789@#$%&*|/\\<>[]{}!?+=-_~^"
)

# ── Block font: 8 wide × 6 tall using █ ──────────────────────────────────────
FONT = {
    'L': ["█       ", "█       ", "█       ", "█       ", "█       ", "████████"],
    'i': [" ██████ ", "   ██   ", "   ██   ", "   ██   ", "   ██   ", " ██████ "],
    'o': [" ██████ ", "██    ██", "██    ██", "██    ██", "██    ██", " ██████ "],
    'n': ["██    ██", "███   ██", "████  ██", "██ ██ ██", "██  ████", "██   ███"],
    'B': ["██████  ", "██    ██", "██    ██", "██████  ", "██    ██", "██████  "],
    'y': ["██    ██", "██    ██", " ██  ██ ", "  ████  ", "   ██   ", "  ██    "],
    't': ["████████", "  ██    ", "  ██    ", "  ██    ", "  ██    ", "  █████ "],
    'e': [" ██████ ", "██    ██", "████████", "██      ", "██    ██", " ██████ "],
    'G': [" ██████ ", "██      ", "██      ", "██  ████", "██    ██", " ██████ "],
}

AH   = 6    # art height (rows per letter)
LGAP = 2    # gap chars between letters
WORD = "LionByteGG"

def build_art():
    rows = [""] * AH
    for idx, ch in enumerate(WORD):
        ltr = FONT.get(ch, [" " * 8] * AH)
        for r in range(AH):
            rows[r] += ltr[r]
            if idx < len(WORD) - 1:
                rows[r] += " " * LGAP
    w = max(len(r) for r in rows)
    return [r.ljust(w) for r in rows], w

ART, ART_W = build_art()

TERM_W   = 110
PAD      = (TERM_W - ART_W) // 2   # left padding to centre logo (≈6)
ART_L    = PAD                       # terminal col where logo starts
ART_R    = PAD + ART_W               # terminal col where logo ends

RAIN_H   = 34
LOGO_ROW = RAIN_H - AH              # row where the art begins inside rain canvas
SNAKE    = 22                        # drop tail length

# ── Drop state: [float_pos, speed, char_list] per terminal column ─────────────
_rng = random.Random()

def _make_drop(stagger=True):
    pos   = _rng.uniform(-SNAKE, RAIN_H if not stagger else 0)
    spd   = _rng.uniform(0.30, 0.80)
    chars = [_rng.choice(GLYPHS) for _ in range(RAIN_H + SNAKE + 8)]
    return [pos, spd, chars]

drops = [_make_drop() for _ in range(TERM_W)]

def _advance():
    for dp in drops:
        dp[0] += dp[1]
        if dp[0] > RAIN_H + SNAKE:
            dp[0] = _rng.uniform(-SNAKE, -1)
            dp[1] = _rng.uniform(0.30, 0.80)
            # Refresh a third of chars for the glitch effect
            idxs = _rng.sample(range(len(dp[2])), len(dp[2]) // 3)
            for i in idxs:
                dp[2][i] = _rng.choice(GLYPHS)

def _drop_color(dist):
    if dist == 0:      return GH
    if dist <= 2:      return G2
    if dist <= 7:      return G1
    if dist <= 14:     return G0
    return GY

def _render(locked_set):
    """locked_set: set of ART-relative column indices frozen into the logo."""
    out = []
    for r in range(RAIN_H):
        row = []
        for c in range(TERM_W):
            art_c = c - ART_L
            in_logo = (0 <= art_c < ART_W) and (r >= LOGO_ROW) and (art_c in locked_set)
            if in_logo:
                ch = ART[r - LOGO_ROW][art_c]
                row.append(GO + '█' + RST if ch == '█' else ' ')
            else:
                dp   = drops[c]
                dist = int(dp[0]) - r
                if 0 <= dist < SNAKE:
                    g = dp[2][(r + int(dp[0] * 7) + c * 3) % len(dp[2])]
                    row.append(_drop_color(dist) + g + RST)
                else:
                    row.append(' ')
        out.append(EL + "".join(row))
    sys.stdout.write(UP(RAIN_H) + "\n".join(out) + "\n")
    sys.stdout.flush()

def _typewrite(msg, color=W, delay=0.05):
    for ch in msg:
        sys.stdout.write(color + ch + RST)
        sys.stdout.flush()
        time.sleep(delay)
    print()

def _show_final():
    sys.stdout.write(CLS)
    sys.stdout.flush()
    IW       = TERM_W - 2                    # inner border width = 108
    art_pad  = " " * ((IW - ART_W) // 2)
    tag      = "[ P N W   E S P O R T S ]"
    tl       = (IW - len(tag)) // 2
    tr       = IW - len(tag) - tl
    ver      = "v2026   ·   PNW Esports"
    vl       = (IW - len(ver)) // 2
    vr       = IW - len(ver) - vl

    def border_line(inner=""):
        pad = " " * (IW - len(inner)) if inner else " " * IW
        return GO + "║" + RST + inner + pad + GO + "║" + RST

    print(GO + "╔" + "═" * IW + "╗" + RST)
    print(GO + "║" + " " * IW + "║" + RST)
    for art_line in ART:
        row_out = "".join((GO + ch + RST) if ch == '█' else ' ' for ch in art_line)
        print(GO + "║" + RST + art_pad + row_out + art_pad + GO + "║" + RST)
    print(GO + "║" + " " * IW + "║" + RST)
    print(GO + "║" + RST + " " * tl + GY + tag + RST + " " * tr + GO + "║" + RST)
    print(GO + "║" + RST + " " * vl + GY + ver + RST + " " * vr + GO + "║" + RST)
    print(GO + "║" + " " * IW + "║" + RST)
    print(GO + "╚" + "═" * IW + "╝" + RST)
    sys.stdout.flush()

# ── Sweep order: left-to-right with a little per-chunk jitter ────────────────
def _sweep_order():
    order = list(range(ART_W))
    for i in range(0, ART_W - 5, 5):
        chunk = order[i:i + 7]
        random.shuffle(chunk)
        order[i:i + 7] = chunk
    return order

try:
    sys.stdout.write(HID + CLS)
    sys.stdout.flush()

    # ── Phase 1: Typewriter ───────────────────────────────────────────────────
    print("\n" * (RAIN_H // 2 - 1), end="")
    _typewrite("         Starting LionServices...", W, 0.055)
    time.sleep(2.0)

    # ── Phase 2: Pure rain warmup ─────────────────────────────────────────────
    sys.stdout.write(CLS)
    sys.stdout.flush()
    for _ in range(RAIN_H):
        sys.stdout.write("\n")

    locked = set()
    for _ in range(35):
        _advance()
        _render(locked)
        time.sleep(0.042)

    # ── Phase 3: Sweep reveal (left → right) ─────────────────────────────────
    sweep = _sweep_order()
    cols_per_frame = max(1, ART_W // 38)
    idx = 0
    while idx < len(sweep):
        _advance()
        for _ in range(cols_per_frame):
            if idx < len(sweep):
                locked.add(sweep[idx])
                idx += 1
        _render(locked)
        time.sleep(0.038)

    # ── Phase 4: Hold with rain on sides ─────────────────────────────────────
    locked = set(range(ART_W))
    for _ in range(28):
        _advance()
        _render(locked)
        time.sleep(0.042)

    # ── Phase 5: Final framed display ────────────────────────────────────────
    _show_final()
    time.sleep(3.2)

    sys.stdout.write(CLS)
    sys.stdout.flush()

finally:
    sys.stdout.write(SHW)
    sys.stdout.flush()
