"""
LionByte Master Terminal
========================
Real-time service monitoring dashboard.
"""

import os
import sys
import json
import threading
import time
import subprocess
from datetime import datetime

# ── Dependency bootstrap ────────────────────────────────────────────────────
def _ensure_deps():
    for pkg, imp in [("customtkinter", "customtkinter"), ("psutil", "psutil")]:
        try:
            __import__(imp)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

_ensure_deps()

import customtkinter as ctk
import psutil

# ── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ACTIVITY_LOG_PATH = os.path.join(DATA_DIR, "activity_log.json")
WORKSPACE_ROOT = os.path.dirname(BASE_DIR)

# ── Theme ───────────────────────────────────────────────────────────────────
BG          = "#0b0d11"
SURFACE     = "#12151c"
CARD        = "#181c26"
BORDER      = "#1f2433"
BORDER_LT   = "#2a2f40"
GREEN       = "#34d399"
RED         = "#f87171"
AMBER       = "#fbbf24"
BLUE        = "#60a5fa"
PURPLE      = "#a78bfa"
CYAN        = "#22d3ee"
WHITE       = "#e2e8f0"
DIM         = "#64748b"
MUTED       = "#3e4459"

SERVICE_COLORS = {
    "LionByteGG":    AMBER,
    "LionShiftGG":   PURPLE,
    "BoilerCraftGG": RED,
    "LionBeatsGG":   CYAN,
    "WebDashboard":  BLUE,
}

SERVICE_DEFS = {
    "LionByteGG":    {"script": "main.py",       "dir": BASE_DIR,                                           "runtime": "python"},
    "LionShiftGG":   {"script": "main.py",       "dir": os.path.join(WORKSPACE_ROOT, "LionShiftGG"),        "runtime": "python"},
    "BoilerCraftGG": {"script": "bot.py",         "dir": os.path.join(WORKSPACE_ROOT, "BoilerCraftGG"),      "runtime": "python"},
    "LionBeatsGG":   {"script": "src/index.js",   "dir": os.path.join(WORKSPACE_ROOT, "LionBeatsGG", "bot"), "runtime": "node"},
    "WebDashboard":  {"script": "run.py",          "dir": os.path.join(BASE_DIR, "web"),                      "runtime": "python"},
}


# ══════════════════════════════════════════════════════════════════════════════
class MasterTerminal(ctk.CTk):

    def __init__(self):
        super().__init__()

        self.title("LionByte  —  Master Terminal")
        self.geometry("960x680")
        self.minsize(820, 560)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        ico = os.path.join(DATA_DIR, "lion_icon.ico")
        if os.path.exists(ico):
            self.iconbitmap(ico)

        self.running = True
        self.start_time = datetime.now()
        self.cached_bots = {}
        self._last_net = psutil.net_io_counters()
        self._last_net_time = time.time()
        psutil.cpu_percent(interval=None)

        self._build_ui()
        threading.Thread(target=self._bg_loop, daemon=True).start()
        self._tick()

    # ── Build ────────────────────────────────────────────────────────────
    def _build_ui(self):

        # ═══ Header bar ═══
        header = ctk.CTkFrame(self, fg_color=SURFACE, height=52, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text="LIONBYTE",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=WHITE
        ).pack(side="left", padx=(24, 6))

        ctk.CTkLabel(
            header, text="MASTER TERMINAL",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=MUTED
        ).pack(side="left", padx=(0, 20))

        # Right side of header
        self.clock_lbl = ctk.CTkLabel(
            header, text="", font=ctk.CTkFont(size=11), text_color=DIM)
        self.clock_lbl.pack(side="right", padx=(0, 24))

        self.uptime_lbl = ctk.CTkLabel(
            header, text="", font=ctk.CTkFont(size=11), text_color=DIM)
        self.uptime_lbl.pack(side="right", padx=(0, 16))

        # ═══ Status banner ═══
        self.banner = ctk.CTkFrame(self, height=40, corner_radius=0, fg_color=SURFACE)
        self.banner.pack(fill="x")
        self.banner.pack_propagate(False)

        self.status_lbl = ctk.CTkLabel(
            self.banner, text="CHECKING SERVICES ...",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=DIM)
        self.status_lbl.pack(expand=True)

        # thin separator
        ctk.CTkFrame(self, fg_color=BORDER, height=1, corner_radius=0).pack(fill="x")

        # ═══ Main body ═══
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=16)

        # ── Services section ──
        ctk.CTkLabel(
            body, text="SERVICES",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=MUTED
        ).pack(anchor="w", pady=(0, 8))

        svc_frame = ctk.CTkFrame(body, fg_color="transparent")
        svc_frame.pack(fill="x")

        self.svc_rows = {}
        for name, color in SERVICE_COLORS.items():
            row = self._build_service_row(svc_frame, name, color)
            row.pack(fill="x", pady=(0, 4))
            self.svc_rows[name] = row

        # ── Resources section ──
        ctk.CTkLabel(
            body, text="RESOURCES",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=MUTED
        ).pack(anchor="w", pady=(20, 10))

        res_grid = ctk.CTkFrame(body, fg_color="transparent")
        res_grid.pack(fill="x")
        for c in range(4):
            res_grid.columnconfigure(c, weight=1, uniform="res")

        self.cpu_card  = self._build_resource_card(res_grid, "CPU",     0)
        self.ram_card  = self._build_resource_card(res_grid, "MEMORY",  1)
        self.disk_card = self._build_resource_card(res_grid, "DISK",    2)
        self.net_card  = self._build_resource_card(res_grid, "NETWORK", 3)

        # ── Activity section ──
        ctk.CTkLabel(
            body, text="ACTIVITY",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=MUTED
        ).pack(anchor="w", pady=(20, 8))

        act_frame = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10, border_width=1, border_color=BORDER)
        act_frame.pack(fill="both", expand=True)

        self.activity_text = ctk.CTkTextbox(
            act_frame, font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=CARD, text_color=DIM,
            corner_radius=10, wrap="none", state="disabled", border_width=0)
        self.activity_text.pack(fill="both", expand=True, padx=6, pady=6)

        # ═══ Footer ═══
        footer = ctk.CTkFrame(self, fg_color=SURFACE, height=28, corner_radius=0)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        self.total_ram_lbl = ctk.CTkLabel(
            footer, text="", font=ctk.CTkFont(size=10), text_color=MUTED)
        self.total_ram_lbl.pack(side="left", padx=(24, 0))

        ctk.CTkLabel(
            footer, text="LionByte Services",
            font=ctk.CTkFont(size=10), text_color=MUTED
        ).pack(side="right", padx=(0, 24))

    # ── Service row builder ──────────────────────────────────────────────
    def _build_service_row(self, parent, name, color):
        row = ctk.CTkFrame(parent, fg_color=CARD, height=44, corner_radius=8,
                           border_width=1, border_color=BORDER)
        row.pack_propagate(False)

        # Color accent left edge
        ctk.CTkFrame(row, fg_color=color, width=3, corner_radius=0).pack(side="left", fill="y")

        # Name
        ctk.CTkLabel(
            row, text=name,
            font=ctk.CTkFont(size=13, weight="bold"), text_color=WHITE
        ).pack(side="left", padx=(14, 0))

        # Right side: PID, RAM, Status
        status_lbl = ctk.CTkLabel(
            row, text="OFFLINE",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=RED)
        status_lbl.pack(side="right", padx=(0, 16))

        dot = ctk.CTkLabel(row, text="●", font=ctk.CTkFont(size=10), text_color=RED)
        dot.pack(side="right", padx=(0, 4))

        ram_lbl = ctk.CTkLabel(
            row, text="—",
            font=ctk.CTkFont(size=11), text_color=MUTED)
        ram_lbl.pack(side="right", padx=(0, 20))

        pid_lbl = ctk.CTkLabel(
            row, text="",
            font=ctk.CTkFont(size=11), text_color=MUTED)
        pid_lbl.pack(side="right", padx=(0, 20))

        row._status_lbl = status_lbl
        row._dot = dot
        row._ram_lbl = ram_lbl
        row._pid_lbl = pid_lbl
        row._color = color
        row._was_online = None
        return row

    # ── Resource card builder ────────────────────────────────────────────
    def _build_resource_card(self, parent, label, col):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10,
                            border_width=1, border_color=BORDER, height=100)
        card.grid(row=0, column=col, padx=(0 if col == 0 else 4, 0), sticky="nsew")
        card.grid_propagate(False)

        ctk.CTkLabel(
            card, text=label,
            font=ctk.CTkFont(size=10, weight="bold"), text_color=MUTED
        ).pack(anchor="w", padx=14, pady=(12, 0))

        val = ctk.CTkLabel(
            card, text="—",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"), text_color=WHITE)
        val.pack(anchor="w", padx=14, pady=(2, 0))

        sub = ctk.CTkLabel(
            card, text="",
            font=ctk.CTkFont(size=10), text_color=DIM)
        sub.pack(anchor="w", padx=14, pady=(0, 10))

        bar = ctk.CTkProgressBar(card, height=4, corner_radius=2,
                                 fg_color=BORDER_LT, progress_color=GREEN)
        bar.pack(fill="x", padx=14, pady=(0, 12))
        bar.set(0)

        card._val = val
        card._sub = sub
        card._bar = bar
        return card

    # ── Background scanner ───────────────────────────────────────────────
    def _bg_loop(self):
        while self.running:
            try:
                self._scan_processes()
            except Exception:
                pass
            time.sleep(1.5)

    def _scan_processes(self):
        bots = {n: {"running": False, "pid": None, "memory": 0} for n in SERVICE_DEFS}
        try:
            for proc in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
                try:
                    info = proc.info
                    cl = " ".join(info["cmdline"] or []).lower()
                    mem = info["memory_info"].rss / (1024**2) if info["memory_info"] else 0

                    if "python" in cl:
                        if "lionbytegg" in cl and "main.py" in cl \
                                and "master_terminal" not in cl and "lionshiftgg" not in cl:
                            bots["LionByteGG"] = {"running": True, "pid": info["pid"], "memory": mem}
                        elif "lionshiftgg" in cl and "main.py" in cl:
                            bots["LionShiftGG"] = {"running": True, "pid": info["pid"], "memory": mem}
                        elif "boilercraftgg" in cl and "bot.py" in cl:
                            bots["BoilerCraftGG"] = {"running": True, "pid": info["pid"], "memory": mem}
                        elif "run.py" in cl and "web" in cl:
                            bots["WebDashboard"] = {"running": True, "pid": info["pid"], "memory": mem}
                    elif ("node" in cl and "index.js" in cl) or ("java" in cl and "lavalink" in cl):
                        if "lionbeatsgg" in cl or "lavalink" in cl:
                            bots["LionBeatsGG"] = {"running": True, "pid": info["pid"], "memory": mem}
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
        self.cached_bots = bots

    # ── Tick ─────────────────────────────────────────────────────────────
    def _tick(self):
        if not self.running:
            return
        try:
            self._update_clock()
            self._update_services()
            self._update_resources()
            self._update_activity()
        except Exception:
            pass
        self.after(1000, self._tick)

    def _update_clock(self):
        now = datetime.now()
        self.clock_lbl.configure(text=now.strftime("%a  %b %d, %Y    %H:%M:%S"))
        up = now - self.start_time
        h, rem = divmod(int(up.total_seconds()), 3600)
        m, s = divmod(rem, 60)
        d, h = divmod(h, 24)
        txt = f"{d}d {h:02d}:{m:02d}:{s:02d}" if d else f"{h:02d}:{m:02d}:{s:02d}"
        self.uptime_lbl.configure(text=f"UP  {txt}")

    def _update_services(self):
        bots = self.cached_bots
        online = 0
        total_ram = 0

        for name, row in self.svc_rows.items():
            info = bots.get(name, {})
            is_on = info.get("running", False)
            mem = info.get("memory", 0)
            pid = info.get("pid")

            if is_on:
                online += 1
                total_ram += mem

            if is_on and row._was_online is not True:
                row._status_lbl.configure(text="ONLINE", text_color=GREEN)
                row._dot.configure(text_color=GREEN)
                row.configure(border_color=row._color)
                row._was_online = True
            elif not is_on and row._was_online is not False:
                row._status_lbl.configure(text="OFFLINE", text_color=RED)
                row._dot.configure(text_color=RED)
                row._ram_lbl.configure(text="—")
                row._pid_lbl.configure(text="")
                row.configure(border_color=BORDER)
                row._was_online = False

            if is_on:
                row._ram_lbl.configure(text=f"{mem:.0f} MB")
                row._pid_lbl.configure(text=f"PID {pid}" if pid else "")

        total = len(self.svc_rows)
        self.total_ram_lbl.configure(text=f"Total RAM: {total_ram:.0f} MB across {online} services")

        if online == total:
            self.status_lbl.configure(text="ALL SERVICES ONLINE", text_color=GREEN)
            self.banner.configure(fg_color="#0d1a14")
        elif online > 0:
            self.status_lbl.configure(text=f"{online} / {total} SERVICES ONLINE", text_color=AMBER)
            self.banner.configure(fg_color="#1a1708")
        else:
            self.status_lbl.configure(text="ALL SERVICES OFFLINE", text_color=RED)
            self.banner.configure(fg_color="#1a0d0d")

    def _update_resources(self):
        # CPU
        cpu = psutil.cpu_percent(interval=None)
        c = GREEN if cpu < 50 else AMBER if cpu < 80 else RED
        self.cpu_card._val.configure(text=f"{cpu:.0f}%", text_color=c)
        self.cpu_card._sub.configure(text=f"{psutil.cpu_count()} cores")
        self.cpu_card._bar.configure(progress_color=c)
        self.cpu_card._bar.set(max(0, min(cpu, 100)) / 100)

        # RAM
        mem = psutil.virtual_memory()
        mc = GREEN if mem.percent < 60 else AMBER if mem.percent < 85 else RED
        self.ram_card._val.configure(text=f"{mem.percent:.0f}%", text_color=mc)
        self.ram_card._sub.configure(text=f"{mem.used/(1024**3):.1f} / {mem.total/(1024**3):.1f} GB")
        self.ram_card._bar.configure(progress_color=mc)
        self.ram_card._bar.set(mem.percent / 100)

        # Disk
        try:
            dk = psutil.disk_usage("C:/" if os.name == "nt" else "/")
            dc = GREEN if dk.percent < 70 else AMBER if dk.percent < 90 else RED
            self.disk_card._val.configure(text=f"{dk.percent:.0f}%", text_color=dc)
            self.disk_card._sub.configure(text=f"{dk.used/(1024**3):.0f} / {dk.total/(1024**3):.0f} GB")
            self.disk_card._bar.configure(progress_color=dc)
            self.disk_card._bar.set(dk.percent / 100)
        except Exception:
            pass

        # Network
        now = time.time()
        elapsed = now - self._last_net_time
        if elapsed >= 1.0:
            net = psutil.net_io_counters()
            up = (net.bytes_sent - self._last_net.bytes_sent) / elapsed / 1024 / 1024
            dn = (net.bytes_recv - self._last_net.bytes_recv) / elapsed / 1024 / 1024
            self._last_net = net
            self._last_net_time = now
            self.net_card._val.configure(text=f"{dn:.1f} MB/s")
            self.net_card._sub.configure(text=f"Up {up:.2f}  /  Down {dn:.2f} MB/s")
            speed = min((up + dn) * 10, 100)
            self.net_card._bar.set(speed / 100)

    def _update_activity(self):
        try:
            if not os.path.exists(ACTIVITY_LOG_PATH):
                return
            with open(ACTIVITY_LOG_PATH, "r", encoding="utf-8") as f:
                entries = json.load(f)[:15]
        except Exception:
            return

        lines = []
        for e in entries:
            ts = e.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                t = dt.strftime("%H:%M:%S")
            except Exception:
                t = ts[:8] if len(ts) >= 8 else "--:--:--"
            act = str(e.get("action", "event")).title()
            u = e.get("user", {})
            un = u.get("name", "System") if isinstance(u, dict) else str(u)
            det = str(e.get("details", ""))[:55]
            lines.append(f"  {t}    {act:<14}  {un:<18}  {det}")

        self.activity_text.configure(state="normal")
        self.activity_text.delete("1.0", "end")
        self.activity_text.insert("1.0", "\n".join(lines))
        self.activity_text.configure(state="disabled")

    def _on_close(self):
        self.running = False
        self.destroy()


# ══════════════════════════════════════════════════════════════════════════════
def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    app = MasterTerminal()
    app.mainloop()


if __name__ == "__main__":
    main()
"""
LIONBYTE MASTER TERMINAL — GUI Dashboard
==========================================
A real-time GUI monitoring dashboard for all LionByte services.
Built with customtkinter for a modern, professional look.
"""

import os
import sys
import json
import threading
import time
import subprocess
from datetime import datetime

# ── Dependency bootstrap ────────────────────────────────────────────────────
def _ensure_deps():
    for pkg, imp in [("customtkinter", "customtkinter"), ("psutil", "psutil")]:
        try:
            __import__(imp)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

_ensure_deps()

import customtkinter as ctk
import psutil

# ── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ACTIVITY_LOG_PATH = os.path.join(DATA_DIR, "activity_log.json")
BOT_STATUS_PATH = os.path.join(DATA_DIR, "bot_status.json")
WORKSPACE_ROOT = os.path.dirname(BASE_DIR)

# ── Branding colors ────────────────────────────────────────────────────────
BG_DARK       = "#0f1117"
BG_PANEL      = "#1a1d27"
BG_CARD       = "#222633"
ACCENT_GOLD   = "#fbbf24"
ACCENT_GREEN  = "#22c55e"
ACCENT_RED    = "#ef4444"
ACCENT_BLUE   = "#3b82f6"
ACCENT_PURPLE = "#a855f7"
ACCENT_CYAN   = "#06b6d4"
ACCENT_ORANGE = "#f97316"
TEXT_PRIMARY   = "#f1f5f9"
TEXT_DIM       = "#64748b"
TEXT_MUTED     = "#475569"

# ── Bot definitions ─────────────────────────────────────────────────────────
BOT_DEFS = {
    "LionByteGG": {
        "icon": "🦁", "color": ACCENT_GOLD,
        "script": "main.py", "dir": BASE_DIR, "runtime": "python",
    },
    "LionShiftGG": {
        "icon": "⏰", "color": ACCENT_PURPLE,
        "script": "main.py", "dir": os.path.join(WORKSPACE_ROOT, "LionShiftGG"), "runtime": "python",
    },
    "BoilerCraftGG": {
        "icon": "⛏️", "color": ACCENT_RED,
        "script": "bot.py", "dir": os.path.join(WORKSPACE_ROOT, "BoilerCraftGG"), "runtime": "python",
    },
    "LionBeatsGG": {
        "icon": "🎵", "color": ACCENT_CYAN,
        "script": "src/index.js", "dir": os.path.join(WORKSPACE_ROOT, "LionBeatsGG", "bot"), "runtime": "node",
    },
    "WebDashboard": {
        "icon": "🌐", "color": ACCENT_BLUE,
        "script": "run.py", "dir": os.path.join(BASE_DIR, "web"), "runtime": "python",
    },
}


# ══════════════════════════════════════════════════════════════════════════════
#  Service Card Widget
# ══════════════════════════════════════════════════════════════════════════════
class ServiceCard(ctk.CTkFrame):
    """A card showing one bot/service with status, memory, PID, and action buttons."""

    def __init__(self, parent, name, definition, terminal_ref, **kw):
        super().__init__(parent, fg_color=BG_CARD, corner_radius=12, border_width=1,
                         border_color="#2d3348", **kw)
        self.name = name
        self.defn = definition
        self.terminal = terminal_ref
        self._online = None  # tri-state for first paint

        # ── Color accent bar at top ──
        accent = ctk.CTkFrame(self, fg_color=definition["color"], height=3, corner_radius=0)
        accent.pack(fill="x", padx=16, pady=(10, 0))

        # ── Header ──
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=14, pady=(8, 4))

        ctk.CTkLabel(
            hdr, text=f"{definition['icon']}  {name}",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=definition["color"],
        ).pack(side="left")

        self.status_dot = ctk.CTkLabel(
            hdr, text="●", font=ctk.CTkFont(size=14), text_color=ACCENT_RED)
        self.status_dot.pack(side="right", padx=(0, 2))

        self.status_label = ctk.CTkLabel(
            hdr, text="OFFLINE", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=ACCENT_RED)
        self.status_label.pack(side="right", padx=(0, 4))

        # ── Stats ──
        stats = ctk.CTkFrame(self, fg_color="transparent")
        stats.pack(fill="x", padx=14, pady=(0, 4))

        self.mem_label = ctk.CTkLabel(
            stats, text="RAM: —", font=ctk.CTkFont(size=12), text_color=TEXT_DIM)
        self.mem_label.pack(side="left")

        self.pid_label = ctk.CTkLabel(
            stats, text="PID: —", font=ctk.CTkFont(size=12), text_color=TEXT_MUTED)
        self.pid_label.pack(side="right")

        # ── Buttons ──
        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=(2, 12))

        self.start_btn = ctk.CTkButton(
            btns, text="▶  Start", width=86, height=30,
            font=ctk.CTkFont(size=12), fg_color=ACCENT_GREEN,
            hover_color="#16a34a", text_color="#000",
            corner_radius=8, command=self._start)
        self.start_btn.pack(side="left", padx=(0, 6))

        self.stop_btn = ctk.CTkButton(
            btns, text="■  Stop", width=86, height=30,
            font=ctk.CTkFont(size=12), fg_color=ACCENT_RED,
            hover_color="#dc2626", text_color="#fff",
            corner_radius=8, command=self._stop)
        self.stop_btn.pack(side="left", padx=(0, 6))

        self.restart_btn = ctk.CTkButton(
            btns, text="↻  Restart", width=86, height=30,
            font=ctk.CTkFont(size=12), fg_color=ACCENT_ORANGE,
            hover_color="#ea580c", text_color="#000",
            corner_radius=8, command=self._restart)
        self.restart_btn.pack(side="left")

    # ── Actions ──────────────────────────────────────────────────────────
    def _start(self):
        d = self.defn
        if not os.path.isdir(d["dir"]):
            self.terminal.log(f"ERROR: Directory not found — {d['dir']}")
            return
        runtime = sys.executable if d["runtime"] == "python" else "node"
        script = os.path.join(d["dir"], d["script"])
        self.terminal.log(f"Starting {self.name}...")
        try:
            subprocess.Popen(
                [runtime, script],
                cwd=d["dir"],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        except Exception as e:
            self.terminal.log(f"Failed to start {self.name}: {e}")

    def _stop(self):
        info = self.terminal.cached_bots.get(self.name, {})
        pid = info.get("pid")
        if pid:
            try:
                proc = psutil.Process(pid)
                for child in proc.children(recursive=True):
                    child.terminate()
                proc.terminate()
                self.terminal.log(f"Stopped {self.name} (PID {pid})")
            except Exception as e:
                self.terminal.log(f"Error stopping {self.name}: {e}")
        else:
            self.terminal.log(f"{self.name} is not running")

    def _restart(self):
        self.terminal.log(f"Restarting {self.name}...")
        self._stop()
        self.after(2500, self._start)

    # ── Update ───────────────────────────────────────────────────────────
    def update_status(self, running, memory=0, pid=None):
        if running and self._online is not True:
            self.status_dot.configure(text_color=ACCENT_GREEN)
            self.status_label.configure(text="ONLINE", text_color=ACCENT_GREEN)
            self.configure(border_color=self.defn["color"])
            self._online = True
        elif not running and self._online is not False:
            self.status_dot.configure(text_color=ACCENT_RED)
            self.status_label.configure(text="OFFLINE", text_color=ACCENT_RED)
            self.mem_label.configure(text="RAM: —")
            self.pid_label.configure(text="PID: —")
            self.configure(border_color="#2d3348")
            self._online = False

        if running:
            self.mem_label.configure(text=f"RAM: {memory:.0f} MB")
            self.pid_label.configure(text=f"PID: {pid or '—'}")


# ══════════════════════════════════════════════════════════════════════════════
#  Stat Bar Widget
# ══════════════════════════════════════════════════════════════════════════════
class StatBar(ctk.CTkFrame):
    """Horizontal labelled progress bar for a system metric."""

    def __init__(self, parent, label, icon, color=ACCENT_GREEN, **kw):
        super().__init__(parent, fg_color="transparent", **kw)
        self._color = color

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x")

        ctk.CTkLabel(
            top, text=f"{icon}  {label}",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT_PRIMARY).pack(side="left")

        self.value_label = ctk.CTkLabel(
            top, text="0%", font=ctk.CTkFont(size=13, weight="bold"),
            text_color=color)
        self.value_label.pack(side="right")

        self.bar = ctk.CTkProgressBar(
            self, height=14, corner_radius=7,
            fg_color="#2d3348", progress_color=color)
        self.bar.pack(fill="x", pady=(4, 0))
        self.bar.set(0)

        self.detail_label = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=11), text_color=TEXT_DIM)
        self.detail_label.pack(anchor="w", pady=(2, 0))

    def update_value(self, percent, detail="", color=None):
        if color and color != self._color:
            self._color = color
            self.bar.configure(progress_color=color)
            self.value_label.configure(text_color=color)
        self.bar.set(max(0, min(percent, 100)) / 100.0)
        self.value_label.configure(text=f"{percent:.1f}%")
        if detail:
            self.detail_label.configure(text=detail)


# ══════════════════════════════════════════════════════════════════════════════
#  Main Application
# ══════════════════════════════════════════════════════════════════════════════
class MasterTerminal(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("LionByte Master Terminal")
        self.geometry("1320x840")
        self.minsize(1020, 660)
        self.configure(fg_color=BG_DARK)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Try to set icon
        ico = os.path.join(DATA_DIR, "lion_icon.ico")
        if os.path.exists(ico):
            self.iconbitmap(ico)

        self.running = True
        self.start_time = datetime.now()
        self.cached_bots = {}
        self.activity_log = []
        self._last_activity_mtime = 0
        self._last_net = psutil.net_io_counters()
        self._last_net_time = time.time()

        psutil.cpu_percent(interval=None)  # prime first read

        self._build_ui()
        self._start_background()
        self._tick()

    # ── UI Construction ──────────────────────────────────────────────────
    def _build_ui(self):
        # ═══ Top bar ═══
        topbar = ctk.CTkFrame(self, fg_color=BG_PANEL, height=56, corner_radius=0)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        ctk.CTkLabel(
            topbar, text="  🦁  LIONBYTE",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=ACCENT_GOLD).pack(side="left", padx=(20, 4))

        ctk.CTkLabel(
            topbar, text="MASTER TERMINAL",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT_DIM).pack(side="left", padx=(0, 20))

        self.clock_label = ctk.CTkLabel(
            topbar, text="", font=ctk.CTkFont(size=12), text_color=TEXT_DIM)
        self.clock_label.pack(side="right", padx=(0, 20))

        self.uptime_label = ctk.CTkLabel(
            topbar, text="Uptime: 00:00:00",
            font=ctk.CTkFont(size=12), text_color=ACCENT_CYAN)
        self.uptime_label.pack(side="right", padx=(0, 16))

        self.online_summary = ctk.CTkLabel(
            topbar, text="●  0/5 Online",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=ACCENT_RED)
        self.online_summary.pack(side="right", padx=(0, 16))

        # ═══ Main content ═══
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=12, pady=(8, 12))

        # ── Left sidebar — system stats + actions ──
        left = ctk.CTkFrame(content, fg_color=BG_PANEL, width=310, corner_radius=14)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        ctk.CTkLabel(
            left, text="⚡  System Resources",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT_PRIMARY).pack(padx=16, pady=(16, 12), anchor="w")

        self.cpu_bar = StatBar(left, "CPU", "🔥", ACCENT_GREEN)
        self.cpu_bar.pack(fill="x", padx=16, pady=(0, 12))

        self.ram_bar = StatBar(left, "Memory", "💾", ACCENT_BLUE)
        self.ram_bar.pack(fill="x", padx=16, pady=(0, 12))

        self.disk_bar = StatBar(left, "Disk", "💿", ACCENT_PURPLE)
        self.disk_bar.pack(fill="x", padx=16, pady=(0, 14))

        # Network card
        net_card = ctk.CTkFrame(left, fg_color=BG_CARD, corner_radius=10)
        net_card.pack(fill="x", padx=16, pady=(0, 14))

        ctk.CTkLabel(
            net_card, text="🌐  Network",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT_PRIMARY).pack(padx=12, pady=(10, 4), anchor="w")

        net_row = ctk.CTkFrame(net_card, fg_color="transparent")
        net_row.pack(fill="x", padx=12, pady=(0, 10))

        self.net_up_label = ctk.CTkLabel(
            net_row, text="▲  0.00 MB/s",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=ACCENT_CYAN)
        self.net_up_label.pack(side="left")

        self.net_down_label = ctk.CTkLabel(
            net_row, text="▼  0.00 MB/s",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=ACCENT_PURPLE)
        self.net_down_label.pack(side="right")

        # Separator
        ctk.CTkFrame(left, fg_color=TEXT_MUTED, height=1).pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(
            left, text="Quick Actions",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT_PRIMARY).pack(padx=16, pady=(0, 8), anchor="w")

        ctk.CTkButton(
            left, text="▶  Start All Services", height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT_GREEN, hover_color="#16a34a",
            text_color="#000", corner_radius=10,
            command=self._start_all).pack(fill="x", padx=16, pady=(0, 6))

        ctk.CTkButton(
            left, text="■  Stop All Services", height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT_RED, hover_color="#dc2626",
            text_color="#fff", corner_radius=10,
            command=self._stop_all).pack(fill="x", padx=16, pady=(0, 6))

        ctk.CTkButton(
            left, text="↻  Restart All Services", height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT_ORANGE, hover_color="#ea580c",
            text_color="#000", corner_radius=10,
            command=self._restart_all).pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(
            left, text="Created with <3 by Jay",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED
        ).pack(side="bottom", pady=(0, 14))

        # ── Right area — services + activity ──
        right = ctk.CTkFrame(content, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)

        # Services header row
        svc_hdr = ctk.CTkFrame(right, fg_color="transparent")
        svc_hdr.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(
            svc_hdr, text="🤖  Bot Services",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT_PRIMARY).pack(side="left")

        self.total_ram_label = ctk.CTkLabel(
            svc_hdr, text="Total: — MB",
            font=ctk.CTkFont(size=12), text_color=TEXT_DIM)
        self.total_ram_label.pack(side="right")

        # Service cards grid
        grid = ctk.CTkFrame(right, fg_color="transparent")
        grid.pack(fill="x")

        self.service_cards = {}
        col = 0
        row = 0
        for name, defn in BOT_DEFS.items():
            card = ServiceCard(grid, name, defn, self)
            card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")
            self.service_cards[name] = card
            col += 1
            if col >= 3:
                col = 0
                row += 1
        for c in range(3):
            grid.columnconfigure(c, weight=1)

        # Activity log
        ctk.CTkLabel(
            right, text="📊  Live Activity Log",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT_PRIMARY).pack(anchor="w", pady=(14, 6))

        act_frame = ctk.CTkFrame(right, fg_color=BG_PANEL, corner_radius=14)
        act_frame.pack(fill="both", expand=True)

        self.activity_text = ctk.CTkTextbox(
            act_frame, font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=BG_PANEL, text_color=TEXT_PRIMARY,
            corner_radius=14, wrap="none", state="disabled", border_width=0)
        self.activity_text.pack(fill="both", expand=True, padx=8, pady=8)

    # ── Background data loader ───────────────────────────────────────────
    def _start_background(self):
        threading.Thread(target=self._bg_loop, daemon=True).start()

    def _bg_loop(self):
        while self.running:
            try:
                if os.path.exists(ACTIVITY_LOG_PATH):
                    mt = os.path.getmtime(ACTIVITY_LOG_PATH)
                    if mt != self._last_activity_mtime:
                        self._last_activity_mtime = mt
                        with open(ACTIVITY_LOG_PATH, "r", encoding="utf-8") as f:
                            self.activity_log = json.load(f)[:30]
                self._scan_processes()
            except Exception:
                pass
            time.sleep(1.5)

    def _scan_processes(self):
        bots = {n: {"running": False, "pid": None, "memory": 0} for n in BOT_DEFS}
        try:
            for proc in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
                try:
                    info = proc.info
                    cl = " ".join(info["cmdline"] or []).lower()
                    mem = info["memory_info"].rss / (1024**2) if info["memory_info"] else 0

                    if "python" in cl:
                        if "lionbytegg" in cl and "main.py" in cl \
                                and "master_terminal" not in cl and "lionshiftgg" not in cl:
                            bots["LionByteGG"] = {"running": True, "pid": info["pid"], "memory": mem}
                        elif "lionshiftgg" in cl and "main.py" in cl:
                            bots["LionShiftGG"] = {"running": True, "pid": info["pid"], "memory": mem}
                        elif "boilercraftgg" in cl and "bot.py" in cl:
                            bots["BoilerCraftGG"] = {"running": True, "pid": info["pid"], "memory": mem}
                        elif "run.py" in cl and "web" in cl:
                            bots["WebDashboard"] = {"running": True, "pid": info["pid"], "memory": mem}
                    elif ("node" in cl and "index.js" in cl) or ("java" in cl and "lavalink" in cl):
                        if "lionbeatsgg" in cl or "lavalink" in cl:
                            bots["LionBeatsGG"] = {"running": True, "pid": info["pid"], "memory": mem}
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
        self.cached_bots = bots

    # ── Periodic UI update (main thread) ─────────────────────────────────
    def _tick(self):
        if not self.running:
            return
        try:
            self._update_clock()
            self._update_system()
            self._update_services()
            self._update_activity()
        except Exception:
            pass
        self.after(1000, self._tick)

    def _update_clock(self):
        now = datetime.now()
        self.clock_label.configure(text=now.strftime("%a %b %d, %Y   %H:%M:%S"))
        up = now - self.start_time
        h, rem = divmod(int(up.total_seconds()), 3600)
        m, s = divmod(rem, 60)
        d, h = divmod(h, 24)
        txt = f"Uptime: {d}d {h:02d}:{m:02d}:{s:02d}" if d else f"Uptime: {h:02d}:{m:02d}:{s:02d}"
        self.uptime_label.configure(text=txt)

    def _update_system(self):
        cpu = psutil.cpu_percent(interval=None)
        cpu_c = ACCENT_GREEN if cpu < 50 else ACCENT_ORANGE if cpu < 80 else ACCENT_RED
        self.cpu_bar.update_value(cpu, f"{psutil.cpu_count()} cores", cpu_c)

        mem = psutil.virtual_memory()
        ram_c = ACCENT_GREEN if mem.percent < 60 else ACCENT_ORANGE if mem.percent < 85 else ACCENT_RED
        self.ram_bar.update_value(
            mem.percent, f"{mem.used / (1024**3):.1f} / {mem.total / (1024**3):.1f} GB", ram_c)

        try:
            dk = psutil.disk_usage("C:/" if os.name == "nt" else "/")
            dk_c = ACCENT_GREEN if dk.percent < 70 else ACCENT_ORANGE if dk.percent < 90 else ACCENT_RED
            self.disk_bar.update_value(
                dk.percent, f"{dk.used / (1024**3):.0f} / {dk.total / (1024**3):.0f} GB", dk_c)
        except Exception:
            pass

        now = time.time()
        elapsed = now - self._last_net_time
        if elapsed >= 1.0:
            net = psutil.net_io_counters()
            up = (net.bytes_sent - self._last_net.bytes_sent) / elapsed / 1024 / 1024
            dn = (net.bytes_recv - self._last_net.bytes_recv) / elapsed / 1024 / 1024
            self._last_net = net
            self._last_net_time = now
            self.net_up_label.configure(text=f"▲  {up:.2f} MB/s")
            self.net_down_label.configure(text=f"▼  {dn:.2f} MB/s")

    def _update_services(self):
        bots = self.cached_bots
        online = 0
        for name, card in self.service_cards.items():
            info = bots.get(name, {})
            r = info.get("running", False)
            card.update_status(r, info.get("memory", 0), info.get("pid"))
            if r:
                online += 1
        total = len(self.service_cards)
        total_ram = sum(bots.get(n, {}).get("memory", 0) for n in self.service_cards)
        self.total_ram_label.configure(text=f"Total: {total_ram:.0f} MB")
        if online == total:
            self.online_summary.configure(
                text=f"●  {online}/{total} Online — All Systems Go", text_color=ACCENT_GREEN)
        elif online > 0:
            self.online_summary.configure(
                text=f"●  {online}/{total} Online", text_color=ACCENT_ORANGE)
        else:
            self.online_summary.configure(
                text=f"●  {online}/{total} Online", text_color=ACCENT_RED)

    def _update_activity(self):
        entries = self.activity_log[:20]
        if not entries:
            return
        icons = {
            "login": "🔓", "logout": "🔒", "warning": "⚠️", "kick": "👢",
            "ban": "🔨", "automod flag": "🚨", "command": "⌨️", "api": "🔌", "roster": "📋",
        }
        lines = []
        for e in entries:
            ts = e.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                t = dt.strftime("%H:%M:%S")
            except Exception:
                t = ts[:8] if len(ts) >= 8 else "—"
            act = str(e.get("action", "unknown")).lower()
            ic = icons.get(act, "📌")
            u = e.get("user", {})
            un = u.get("name", "Unknown") if isinstance(u, dict) else str(u)
            det = str(e.get("details", ""))[:60]
            lines.append(f"  {t}   {ic} {act.title():<14} {un:<20} {det}")

        self.activity_text.configure(state="normal")
        self.activity_text.delete("1.0", "end")
        self.activity_text.insert("1.0", "\n".join(lines))
        self.activity_text.configure(state="disabled")

    # ── Global actions ───────────────────────────────────────────────────
    def _start_all(self):
        self.log("Starting all services...")
        for card in self.service_cards.values():
            card._start()

    def _stop_all(self):
        self.log("Stopping all services...")
        for card in self.service_cards.values():
            card._stop()

    def _restart_all(self):
        self.log("Restarting all services...")
        self._stop_all()
        self.after(3000, self._start_all)

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"  {ts}   📌 {'System':<14} {'Terminal':<20} {msg}"
        self.activity_text.configure(state="normal")
        self.activity_text.insert("1.0", line + "\n")
        self.activity_text.configure(state="disabled")

    def _on_close(self):
        self.running = False
        self.destroy()


# ══════════════════════════════════════════════════════════════════════════════
#  Entry
# ══════════════════════════════════════════════════════════════════════════════
def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    app = MasterTerminal()
    app.mainloop()


if __name__ == "__main__":
    main()
