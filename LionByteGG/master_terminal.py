"""
LionByte Master Terminal — Kiosk Edition (PyQt6)
Ctrl+Alt+Q or EXIT button to close.
"""
import os, sys, json, time, subprocess, platform
from datetime import datetime

# ---------------------------------------------------------------------------
# Bootstrap dependencies
# ---------------------------------------------------------------------------
def _bootstrap():
    for pkg in ("PyQt6", "psutil"):
        try:
            __import__(pkg)
        except ImportError:
            subprocess.check_call(
                [sys.executable.replace("pythonw", "python"), "-m", "pip",
                 "install", pkg, "-q"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
_bootstrap()

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QFrame,
    QHBoxLayout, QVBoxLayout, QTextEdit, QDialog,
    QProgressBar, QSizePolicy, QScrollArea,
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QObject
from PyQt6.QtGui  import QPainter, QColor, QShortcut, QKeySequence, QIcon
import psutil

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
DATA_DIR       = os.path.join(BASE_DIR, "data")
ACTIVITY_PATH  = os.path.join(DATA_DIR, "activity_log.json")
WORKSPACE_ROOT = os.path.dirname(BASE_DIR)

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
C = {
    "bg":      "#07080f",
    "panel":   "#0c0e19",
    "border":  "#161929",
    "border2": "#1e2235",
    "muted":   "#2a2f45",
    "text":    "#c8d0e0",
    "dim":     "#44506a",
    "gold":    "#f59e0b",
    "green":   "#22c55e",
    "red":     "#ef4444",
    "orange":  "#f97316",
    "cyan":    "#06b6d4",
    "purple":  "#a855f7",
    "blue":    "#3b82f6",
    "slate":   "#94a3b8",
}

# ---------------------------------------------------------------------------
# Service definitions
# ---------------------------------------------------------------------------
SERVICES = {
    "LionByteGG":    {"letter":"L","sub":"Main Discord Bot",  "color":C["gold"],
                      "script":"main.py","dir":BASE_DIR,"runtime":"python"},
    "LionShiftGG":   {"letter":"S","sub":"Shift Manager",     "color":C["purple"],
                      "script":"main.py",
                      "dir":os.path.join(WORKSPACE_ROOT,"LionShiftGG"),"runtime":"python"},
    "BoilerCraftGG": {"letter":"B","sub":"Minecraft Bot",     "color":C["red"],
                      "script":"bot.py",
                      "dir":os.path.join(WORKSPACE_ROOT,"BoilerCraftGG"),"runtime":"python"},
    "LionBeatsGG":   {"letter":"M","sub":"Music Bot",         "color":C["cyan"],
                      "script":os.path.join("src","index.js"),
                      "dir":os.path.join(WORKSPACE_ROOT,"LionBeatsGG","bot"),"runtime":"node"},
    "Lavalink":      {"letter":"A","sub":"Audio Server",      "color":C["slate"],
                      "script":"Lavalink.jar",
                      "dir":os.path.join(WORKSPACE_ROOT,"LionBeatsGG","lavalink"),"runtime":"java"},
    "Nova":          {"letter":"N","sub":"Admin Panel",       "color":C["blue"],
                      "script":"run.py",
                      "dir":os.path.join(BASE_DIR,"web"),"runtime":"python"},
}
ORDER = ["LionByteGG","LionShiftGG","BoilerCraftGG","LionBeatsGG","Lavalink","Nova"]

# ---------------------------------------------------------------------------
# Global QSS  — transparent labels, no black boxes
# ---------------------------------------------------------------------------
GLOBAL_QSS = f"""
* {{
    font-family: 'Segoe UI', Arial, sans-serif;
}}
QWidget {{
    background: {C["bg"]};
    color: {C["text"]};
}}
QLabel {{
    background: transparent;
}}
QFrame {{
    background: transparent;
}}
QTextEdit#log {{
    background: {C["panel"]};
    border: 1px solid {C["border"]};
    border-radius: 8px;
    padding: 8px;
    font-family: Consolas, monospace;
    font-size: 10px;
    color: {C["dim"]};
}}
QScrollBar:vertical {{
    background: {C["panel"]};
    width: 4px; margin: 0; border: none;
}}
QScrollBar::handle:vertical {{
    background: {C["border2"]};
    border-radius: 2px;
    min-height: 16px;
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollArea {{
    border: none;
}}
"""


# ===========================================================================
# Stripe — solid painted coloured bar
# ===========================================================================
class Stripe(QWidget):
    def __init__(self, color: str, h: int = 2, parent=None):
        super().__init__(parent)
        self.setFixedHeight(h)
        self._c = QColor(color)
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), self._c)
        p.end()


# ===========================================================================
# Thin progress bar (inline, no QSS inheritance issues)
# ===========================================================================
class TinyBar(QWidget):
    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color  = QColor(color)
        self._track  = QColor(C["border"])
        self._pct    = 0.0
        self.setFixedHeight(4)
        self.setMinimumWidth(60)

    def set_pct(self, pct: float, color: str = None):
        self._pct = max(0.0, min(pct, 100.0))
        if color:
            self._color = QColor(color)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        # track
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._track)
        p.drawRoundedRect(r, 2, 2)
        # fill
        fw = int(r.width() * self._pct / 100)
        if fw > 0:
            p.setBrush(self._color)
            p.drawRoundedRect(r.x(), r.y(), fw, r.height(), 2, 2)
        p.end()


# ===========================================================================
# Sidebar metric row (CPU / RAM / Disk)
# ===========================================================================
class MetricRow(QWidget):
    def __init__(self, label: str, accent: str, parent=None):
        super().__init__(parent)
        self._accent = accent
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self._lbl = QLabel(label)
        self._lbl.setStyleSheet(f"font-size:10px;font-weight:bold;color:{C['dim']};background:transparent;")
        self._val = QLabel("—")
        self._val.setStyleSheet(f"font-size:10px;font-weight:bold;color:{accent};background:transparent;")
        row.addWidget(self._lbl)
        row.addStretch()
        row.addWidget(self._val)
        v.addLayout(row)

        self._bar = TinyBar(accent)
        v.addWidget(self._bar)

        self._det = QLabel("")
        self._det.setStyleSheet(f"font-size:9px;color:{C['muted']};background:transparent;")
        v.addWidget(self._det)

    def set(self, pct: float, detail: str = "", accent: str = None):
        col = accent or self._accent
        if accent:
            self._accent = accent
            self._val.setStyleSheet(f"font-size:10px;font-weight:bold;color:{col};background:transparent;")
        self._bar.set_pct(pct, col)
        self._val.setText(f"{pct:.0f}%")
        if detail:
            self._det.setText(detail)


# ===========================================================================
# Service list row — each service is a horizontal row in a list
# ===========================================================================
class ServiceRow(QWidget):
    def __init__(self, name: str, defn: dict, parent=None):
        super().__init__(parent)
        self.name   = name
        self.defn   = defn
        self._state = None
        self._pid   = None
        color       = defn["color"]

        self.setFixedHeight(64)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._update_bg(False)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Left accent stripe
        outer.addWidget(Stripe(color, 3))

        # Content
        inner = QHBoxLayout()
        inner.setContentsMargins(14, 0, 14, 0)
        inner.setSpacing(0)
        outer.addLayout(inner, stretch=1)

        # Badge
        badge = QLabel(defn["letter"])
        badge.setFixedSize(36, 36)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background:{color};color:#06080f;border-radius:8px;"
            f"font-weight:800;font-size:15px;"
        )
        inner.addWidget(badge)
        inner.addSpacing(14)

        # Name + sub
        name_col = QVBoxLayout()
        name_col.setContentsMargins(0, 0, 0, 0)
        name_col.setSpacing(3)
        self._name_lbl = QLabel(name)
        self._name_lbl.setStyleSheet(
            f"font-size:14px;font-weight:bold;color:{color};background:transparent;"
        )
        self._sub_lbl = QLabel(defn["sub"])
        self._sub_lbl.setStyleSheet(
            f"font-size:10px;color:{C['dim']};background:transparent;"
        )
        name_col.addWidget(self._name_lbl)
        name_col.addWidget(self._sub_lbl)
        inner.addLayout(name_col)
        inner.addSpacing(16)

        inner.addStretch()

        # Memory text (no bar — clean display)
        self._mem_lbl = QLabel("—")
        self._mem_lbl.setFixedWidth(62)
        self._mem_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._mem_lbl.setStyleSheet(
            f"font-family:Consolas;font-size:10px;color:{C['dim']};background:transparent;"
        )
        inner.addWidget(self._mem_lbl)
        inner.addSpacing(20)

        # PID label
        self._pid_lbl = QLabel("PID  —")
        self._pid_lbl.setFixedWidth(88)
        self._pid_lbl.setStyleSheet(
            f"font-family:Consolas;font-size:10px;color:{C['muted']};background:transparent;"
        )
        inner.addWidget(self._pid_lbl)
        inner.addSpacing(16)

        # Status dot + text
        self._dot = QLabel("●")
        self._dot.setStyleSheet(f"font-size:16px;color:{C['red']};background:transparent;")
        self._status = QLabel("OFFLINE")
        self._status.setFixedWidth(66)
        self._status.setStyleSheet(
            f"font-size:11px;font-weight:bold;color:{C['red']};background:transparent;"
        )
        inner.addWidget(self._dot)
        inner.addSpacing(6)
        inner.addWidget(self._status)

    def _update_bg(self, online: bool):
        if online:
            self.setStyleSheet(f"ServiceRow{{background:{C['panel']};}}") 
        else:
            self.setStyleSheet(f"ServiceRow{{background:{C['bg']};}}")

    def refresh(self, running: bool, memory: float = 0.0, pid=None):
        if running != self._state:
            self._state = running
            self._update_bg(running)
            col = C["green"] if running else C["red"]
            self._dot.setStyleSheet(f"font-size:16px;color:{col};background:transparent;")
            self._status.setText("ONLINE" if running else "OFFLINE")
            self._status.setStyleSheet(
                f"font-size:11px;font-weight:bold;color:{col};background:transparent;"
            )

        if running:
            self._pid_lbl.setText(f"PID  {pid or '—'}")
            self._mem_lbl.setText(f"{memory:.0f} MB")
        else:
            self._pid_lbl.setText("PID  —")
            self._mem_lbl.setText("—")


# ===========================================================================
# Background worker
# ===========================================================================
class Worker(QObject):
    bots_signal     = pyqtSignal(dict)
    activity_signal = pyqtSignal(list)

    def __init__(self, app):
        super().__init__()
        self.app        = app
        self._running   = True
        self._act_mtime = 0.0
        self._proc_cpu  = {}   # pid -> psutil.Process for cpu_percent

    def stop(self): self._running = False

    def run(self):
        while self._running:
            try:
                self.bots_signal.emit(self._scan())
            except Exception:
                pass
            try:
                self._load_activity()
            except Exception:
                pass
            time.sleep(2.0)

    def _scan(self) -> dict:
        result = {n: {"running": False, "pid": None, "memory": 0.0, "cpu": 0.0}
                  for n in SERVICES}

        # Stored-PID fast path
        for name, row in self.app.rows.items():
            if row._pid is None:
                continue
            try:
                p = psutil.Process(row._pid)
                if p.is_running() and p.status() not in (
                        psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
                    mem = p.memory_info().rss / (1024**2)
                    # cpu_percent non-blocking — returns 0 on first call per PID
                    if row._pid not in self._proc_cpu:
                        self._proc_cpu[row._pid] = p
                        p.cpu_percent(interval=None)
                        cpu = 0.0
                    else:
                        cpu = self._proc_cpu[row._pid].cpu_percent(interval=None)
                    result[name] = {"running": True, "pid": row._pid,
                                    "memory": mem, "cpu": cpu}
                    continue
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            row._pid = None
            self._proc_cpu.pop(row._pid, None)

        # CWD scan
        cwd_map = {
            os.path.normcase(os.path.normpath(d["dir"])): n
            for n, d in SERVICES.items()
        }
        try:
            for proc in psutil.process_iter(["pid","name","cmdline","memory_info"]):
                try:
                    info  = proc.info
                    pid   = info["pid"]
                    if pid == os.getpid():
                        continue
                    cl    = " ".join(info["cmdline"] or []).lower()
                    if "master_terminal" in cl:
                        continue
                    pname = (info["name"] or "").lower()
                    mem   = (info["memory_info"].rss/(1024**2)) if info["memory_info"] else 0.0
                    try:
                        cwd = os.path.normcase(os.path.normpath(proc.cwd()))
                    except Exception:
                        cwd = ""
                    matched = cwd_map.get(cwd)
                    is_py   = "python" in pname
                    is_node = "node"   in pname
                    is_java = "java"   in pname
                    if is_py and matched and matched not in ("LionBeatsGG","Lavalink"):
                        if not result[matched]["running"]:
                            if pid not in self._proc_cpu:
                                self._proc_cpu[pid] = proc
                                proc.cpu_percent(interval=None)
                                cpu = 0.0
                            else:
                                cpu = self._proc_cpu[pid].cpu_percent(interval=None)
                            result[matched] = {"running":True,"pid":pid,"memory":mem,"cpu":cpu}
                    elif is_node and (matched == "LionBeatsGG" or "index.js" in cl):
                        if not result["LionBeatsGG"]["running"]:
                            result["LionBeatsGG"] = {"running":True,"pid":pid,"memory":mem,"cpu":0.0}
                    elif is_java and (matched == "Lavalink" or "lavalink" in cl):
                        if not result["Lavalink"]["running"]:
                            result["Lavalink"] = {"running":True,"pid":pid,"memory":mem,"cpu":0.0}
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass

        # Clean dead pids from cpu tracker
        live = {v["pid"] for v in result.values() if v["pid"]}
        for dead in list(self._proc_cpu):
            if dead not in live:
                del self._proc_cpu[dead]

        return result

    def _load_activity(self):
        try:
            if not os.path.exists(ACTIVITY_PATH):
                return
            mt = os.path.getmtime(ACTIVITY_PATH)
            if mt == self._act_mtime:
                return
            self._act_mtime = mt
            with open(ACTIVITY_PATH, encoding="utf-8") as f:
                self.activity_signal.emit(json.load(f)[:25])
        except Exception:
            pass


# ===========================================================================
# Confirm dialog
# ===========================================================================
class ConfirmDialog(QDialog):
    def __init__(self, parent, title: str, body: str, ok_text: str, ok_color: str):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(480, 180)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        box = QFrame(self)
        box.setStyleSheet(
            f"QFrame{{background:{C['panel']};border:1px solid {C['border2']};"
            f"border-radius:12px;}}"
        )
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        bl.addWidget(Stripe(ok_color, 3))

        inner = QVBoxLayout()
        inner.setContentsMargins(30, 18, 30, 22)
        inner.setSpacing(6)

        ttl = QLabel(title)
        ttl.setStyleSheet(
            f"font-size:14px;font-weight:bold;color:{C['text']};background:transparent;"
        )
        ttl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(ttl)

        bd = QLabel(body)
        bd.setStyleSheet(
            f"font-size:10px;color:{C['dim']};background:transparent;"
        )
        bd.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bd.setWordWrap(True)
        inner.addWidget(bd)
        inner.addSpacing(14)

        btns = QHBoxLayout()
        btns.setSpacing(10)
        btns.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setFixedSize(120, 34)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(
            f"QPushButton{{background:{C['border2']};color:{C['text']};border:none;"
            f"border-radius:6px;font-weight:bold;font-size:11px;}}"
            f"QPushButton:hover{{background:{C['muted']};}}"
        )
        cancel.clicked.connect(self.reject)

        ok = QPushButton(ok_text)
        ok.setFixedSize(130, 34)
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.setStyleSheet(
            f"QPushButton{{background:{ok_color};color:#fff;border:none;"
            f"border-radius:6px;font-weight:bold;font-size:11px;}}"
            f"QPushButton:hover{{background:{ok_color};opacity:0.85;}}"
        )
        ok.clicked.connect(self.accept)

        btns.addWidget(cancel)
        btns.addWidget(ok)
        btns.addStretch()
        inner.addLayout(btns)
        bl.addLayout(inner)
        outer.addWidget(box)

        QShortcut(QKeySequence("Escape"), self).activated.connect(self.reject)
        scr = QApplication.primaryScreen().geometry()
        self.move(
            scr.x() + (scr.width()  - self.width())  // 2,
            scr.y() + (scr.height() - self.height()) // 2,
        )


# ===========================================================================
# Main window
# ===========================================================================
class MasterTerminal(QWidget):
    log_sig = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LionByte Master Terminal")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        scr = QApplication.primaryScreen().geometry()
        self.setGeometry(scr)
        self.setStyleSheet(GLOBAL_QSS)

        ico = os.path.join(DATA_DIR, "lion_icon.ico")
        if os.path.isfile(ico):
            self.setWindowIcon(QIcon(ico))

        self.start_time  = datetime.now()
        self._bots       = {n: {"running":False,"pid":None,"memory":0.0,"cpu":0.0}
                            for n in SERVICES}
        self._act_lines  = []
        self._sys_msgs   = []
        self._last_net   = psutil.net_io_counters()
        self._last_net_t = time.time()
        self.rows: dict[str, ServiceRow] = {}
        self._total_ram  = psutil.virtual_memory().total / (1024**2)  # MB
        psutil.cpu_percent(interval=None)

        self._build()
        self.log_sig.connect(self._append_sys)

        QShortcut(QKeySequence("Ctrl+Alt+Q"), self).activated.connect(self._exit_prompt)

        self._worker = Worker(self)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._worker.bots_signal.connect(self._on_bots)
        self._worker.activity_signal.connect(self._on_activity)
        self._thread.started.connect(self._worker.run)
        self._thread.start()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    # -----------------------------------------------------------------------
    def _btn(self, text: str, color: str, w=None, h=32, fs=9, full=False) -> QPushButton:
        b = QPushButton(text)
        if w:
            b.setFixedSize(w, h)
        else:
            b.setFixedHeight(h)
        if full:
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background:{color}20;color:{color};"
            f"border:1px solid {color}50;border-radius:5px;"
            f"font-weight:bold;font-size:{fs}px;padding:0 8px;}}"
            f"QPushButton:hover{{background:{color}40;}}"
        )
        return b

    # -----------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ─────────────────────────────────────────────────────────
        topbar = QWidget()
        topbar.setFixedHeight(52)
        topbar.setStyleSheet(
            f"background:{C['panel']};border-bottom:1px solid {C['border']};"
        )
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(20, 0, 16, 0)
        tb.setSpacing(0)

        logo = QLabel("LIONBYTE")
        logo.setStyleSheet(
            f"font-size:20px;font-weight:900;color:{C['gold']};background:transparent;"
        )
        sub = QLabel("  MASTER TERMINAL")
        sub.setStyleSheet(
            f"font-size:10px;font-weight:bold;color:{C['dim']};background:transparent;"
            f"letter-spacing:1px;"
        )
        tb.addWidget(logo)
        tb.addWidget(sub)
        tb.addStretch()

        self._online_lbl = QLabel("0 / 6  ONLINE")
        self._online_lbl.setStyleSheet(
            f"font-size:11px;font-weight:bold;color:{C['red']};background:transparent;"
        )
        tb.addWidget(self._online_lbl)
        tb.addSpacing(24)

        self._uptime_lbl = QLabel("UP  00:00:00")
        self._uptime_lbl.setStyleSheet(
            f"font-size:10px;color:{C['cyan']};background:transparent;"
        )
        tb.addWidget(self._uptime_lbl)
        tb.addSpacing(24)

        self._clock_lbl = QLabel("")
        self._clock_lbl.setStyleSheet(
            f"font-family:Consolas;font-size:10px;color:{C['muted']};background:transparent;"
        )
        tb.addWidget(self._clock_lbl)
        tb.addSpacing(20)

        exit_btn = self._btn("EXIT", C["red"], w=72, h=28, fs=9)
        exit_btn.clicked.connect(self._exit_prompt)
        tb.addWidget(exit_btn)

        root.addWidget(topbar)
        root.addWidget(Stripe(C["gold"], 2))

        # ── Body ────────────────────────────────────────────────────────────
        body = QWidget()
        body.setStyleSheet(f"background:{C['bg']};")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(12, 10, 12, 8)
        bl.setSpacing(10)
        root.addWidget(body, stretch=1)

        # ── Sidebar ─────────────────────────────────────────────────────────
        sidebar = QWidget()
        sidebar.setFixedWidth(280)
        sidebar.setStyleSheet(
            f"background:{C['panel']};border:1px solid {C['border']};"
            f"border-radius:10px;"
        )
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(16, 16, 16, 16)
        sl.setSpacing(0)
        bl.addWidget(sidebar)

        def sect_hdr(txt: str) -> QLabel:
            l = QLabel(txt.upper())
            l.setStyleSheet(
                f"font-size:8px;font-weight:bold;color:{C['gold']};"
                f"letter-spacing:2px;background:transparent;"
            )
            return l

        def hrule() -> QFrame:
            f = QFrame()
            f.setFixedHeight(1)
            f.setStyleSheet(f"background:{C['border']};")
            return f

        sl.addWidget(sect_hdr("System Resources"))
        sl.addSpacing(10)
        self._cpu  = MetricRow("CPU",    C["green"])
        self._ram  = MetricRow("Memory", C["blue"])
        self._disk = MetricRow("Disk",   C["purple"])
        for bar in (self._cpu, self._ram, self._disk):
            sl.addWidget(bar)
            sl.addSpacing(10)

        sl.addWidget(hrule())
        sl.addSpacing(12)
        sl.addWidget(sect_hdr("Network I/O"))
        sl.addSpacing(8)

        net_row = QHBoxLayout()
        net_row.setContentsMargins(0, 0, 0, 0)
        self._up_lbl = QLabel("↑  0.00 MB/s")
        self._up_lbl.setStyleSheet(
            f"font-size:11px;font-weight:bold;color:{C['cyan']};background:transparent;"
        )
        self._dn_lbl = QLabel("↓  0.00 MB/s")
        self._dn_lbl.setStyleSheet(
            f"font-size:11px;font-weight:bold;color:{C['purple']};background:transparent;"
        )
        net_row.addWidget(self._up_lbl)
        net_row.addStretch()
        net_row.addWidget(self._dn_lbl)
        sl.addLayout(net_row)
        sl.addSpacing(14)

        sl.addWidget(hrule())
        sl.addSpacing(12)

        # System info
        cores = psutil.cpu_count(logical=True)
        phys  = psutil.cpu_count(logical=False)
        mem_t = psutil.virtual_memory().total / (1024**3)
        info  = QLabel(
            f"OS    {platform.system()} {platform.release()}\n"
            f"CPU   {phys}c / {cores}t\n"
            f"RAM   {mem_t:.1f} GB\n"
            f"Py    {sys.version.split()[0]}"
        )
        info.setStyleSheet(
            f"font-family:Consolas;font-size:9px;color:{C['muted']};line-height:1.9;"
            f"background:transparent;"
        )
        sl.addWidget(info)
        sl.addSpacing(14)

        sl.addWidget(hrule())
        sl.addSpacing(14)
        sl.addWidget(sect_hdr("System Power"))
        sl.addSpacing(10)

        rb = self._btn("RESTART SERVER", "#c2410c", full=True, h=34)
        rb.clicked.connect(lambda: self._power_prompt(
            "Restart Server",
            "Warning: Restarting the server will immediately terminate all active\n"
            "services. The entire LionByteGG infrastructure — including all bots\n"
            "and Nova — will go offline until the machine has fully rebooted.",
            "Restart Now", "#c2410c",
            lambda: os.system("shutdown /r /t 3"),
        ))
        sl.addWidget(rb)
        sl.addSpacing(6)

        sb = self._btn("SHUTDOWN PC", C["red"], full=True, h=34)
        sb.clicked.connect(lambda: self._power_prompt(
            "Shut Down PC",
            "This will power off the computer.\nAll services will be terminated.",
            "Shut Down", C["red"],
            lambda: os.system("shutdown /s /t 3"),
        ))
        sl.addWidget(sb)
        sl.addStretch()

        credit = QLabel("LionByteGG  ·  made with \u2665 by Jay Moon")
        credit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credit.setStyleSheet(
            f"font-size:8px;color:{C['muted']};background:transparent;"
        )
        sl.addWidget(credit)

        # ── Right panel ──────────────────────────────────────────────────────
        right = QWidget()
        right.setStyleSheet(f"background:{C['bg']};")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        bl.addWidget(right, stretch=1)

        # Status banner
        self._banner = QWidget()
        self._banner.setFixedHeight(32)
        self._banner.setStyleSheet(
            f"background:{C['panel']};border:1px solid {C['border']};"
            f"border-radius:7px;"
        )
        ban_l = QHBoxLayout(self._banner)
        ban_l.setContentsMargins(14, 0, 14, 0)
        self._banner_lbl = QLabel("INITIALISING...")
        self._banner_lbl.setStyleSheet(
            f"font-size:11px;font-weight:bold;color:{C['dim']};background:transparent;"
        )
        ban_l.addWidget(self._banner_lbl)
        rl.addWidget(self._banner)

        # ── Service list ────────────────────────────────────────────────────
        list_hdr = QLabel("Services")
        list_hdr.setStyleSheet(
            f"font-size:9px;font-weight:bold;color:{C['gold']};"
            f"letter-spacing:2px;background:transparent;"
        )
        rl.addWidget(list_hdr)

        # Column headers
        col_hdr = QWidget()
        col_hdr.setStyleSheet(f"background:{C['panel']};border-radius:6px;")
        ch = QHBoxLayout(col_hdr)
        ch.setContentsMargins(66, 4, 14, 4)
        ch.setSpacing(0)
        for txt, w in [("SERVICE", 220), ("", 0), ("MEM", 84), ("PID", 106), ("STATUS", 80)]:
            lbl = QLabel(txt)
            lbl.setStyleSheet(
                f"font-size:8px;font-weight:bold;color:{C['muted']};"
                f"letter-spacing:1px;background:transparent;"
            )
            if w:
                lbl.setFixedWidth(w)
            else:
                lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            ch.addWidget(lbl)
        rl.addWidget(col_hdr)

        # Rows
        rows_container = QWidget()
        rows_container.setStyleSheet(
            f"background:{C['panel']};border:1px solid {C['border']};"
            f"border-radius:8px;"
        )
        rows_vbox = QVBoxLayout(rows_container)
        rows_vbox.setContentsMargins(0, 0, 0, 0)
        rows_vbox.setSpacing(0)

        for i, name in enumerate(ORDER):
            row = ServiceRow(name, SERVICES[name])
            rows_vbox.addWidget(row)
            if i < len(ORDER) - 1:
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(f"background:{C['border']};")
                rows_vbox.addWidget(sep)
            self.rows[name] = row
        rl.addWidget(rows_container)

        # ── Activity log ────────────────────────────────────────────────────
        act_hdr = QLabel("Activity Log")
        act_hdr.setStyleSheet(
            f"font-size:9px;font-weight:bold;color:{C['gold']};"
            f"letter-spacing:2px;background:transparent;"
        )
        rl.addWidget(act_hdr)

        self._log = QTextEdit()
        self._log.setObjectName("log")
        self._log.setReadOnly(True)
        self._log.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        rl.addWidget(self._log, stretch=1)

        # ── Footer ──────────────────────────────────────────────────────────
        footer = QWidget()
        footer.setFixedHeight(22)
        footer.setStyleSheet(
            f"background:{C['panel']};border-top:1px solid {C['border']};"
        )
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(16, 0, 16, 0)
        self._footer_l = QLabel("")
        self._footer_l.setStyleSheet(
            f"font-size:8px;color:{C['muted']};background:transparent;"
        )
        fl.addWidget(self._footer_l)
        fl.addStretch()
        hint = QLabel("LionByte Services  ·  Ctrl+Alt+Q to exit")
        hint.setStyleSheet(
            f"font-size:8px;color:{C['muted']};background:transparent;"
        )
        fl.addWidget(hint)
        root.addWidget(footer)

    # -----------------------------------------------------------------------
    # Slots
    # -----------------------------------------------------------------------
    def _on_bots(self, bots: dict):
        self._bots = bots
        self._refresh_services()

    def _on_activity(self, data: list):
        lines = []
        for e in data[:20]:
            ts = e.get("timestamp", "")
            try:
                t = datetime.fromisoformat(ts.replace("Z","+00:00")).strftime("%H:%M:%S")
            except Exception:
                t = ts[:8] if len(ts) >= 8 else "--:--:--"
            act = str(e.get("action","")).lower()
            u   = e.get("user", {})
            un  = u.get("name","System") if isinstance(u, dict) else str(u)
            det = str(e.get("details",""))[:55]
            lines.append(f"  {t}  {act.title():<16} {un:<20} {det}")
        self._act_lines = lines
        self._redraw_log()

    def _append_sys(self, line: str):
        self._sys_msgs.insert(0, line)
        self._sys_msgs = self._sys_msgs[:10]
        self._redraw_log()

    def _redraw_log(self):
        parts = list(self._sys_msgs)
        if self._act_lines:
            if parts:
                parts.append("  " + "─" * 64)
            parts.extend(self._act_lines)
        self._log.setPlainText("\n".join(parts))

    def log(self, msg: str):
        self.log_sig.emit(f"  {datetime.now().strftime('%H:%M:%S')}  {msg}")

    # -----------------------------------------------------------------------
    # Tick (every 1 s)
    # -----------------------------------------------------------------------
    def _tick(self):
        now = datetime.now()
        self._clock_lbl.setText(now.strftime("%a %b %d  %H:%M:%S"))
        up = now - self.start_time
        h, r = divmod(int(up.total_seconds()), 3600)
        m, s = divmod(r, 60)
        d, h = divmod(h, 24)
        self._uptime_lbl.setText(
            "UP  " + (f"{d}d " if d else "") + f"{h:02d}:{m:02d}:{s:02d}"
        )
        self._update_resources()

    def _update_resources(self):
        cpu   = psutil.cpu_percent(interval=None)
        cpu_c = C["green"] if cpu < 50 else C["orange"] if cpu < 80 else C["red"]
        self._cpu.set(cpu, f"{psutil.cpu_count()} threads", cpu_c)

        mem   = psutil.virtual_memory()
        mem_c = C["blue"] if mem.percent < 60 else C["orange"] if mem.percent < 85 else C["red"]
        self._ram.set(mem.percent,
                      f"{mem.used/(1024**3):.1f} / {mem.total/(1024**3):.1f} GB", mem_c)

        try:
            dk   = psutil.disk_usage("C:/" if os.name == "nt" else "/")
            dk_c = C["purple"] if dk.percent < 70 else C["orange"] if dk.percent < 90 else C["red"]
            self._disk.set(dk.percent,
                           f"{dk.used/(1024**3):.0f} / {dk.total/(1024**3):.0f} GB", dk_c)
        except Exception:
            pass

        now = time.time()
        el  = now - self._last_net_t
        if el >= 1.0:
            net  = psutil.net_io_counters()
            up_s = (net.bytes_sent - self._last_net.bytes_sent) / el / 1_048_576
            dn_s = (net.bytes_recv - self._last_net.bytes_recv) / el / 1_048_576
            self._last_net   = net
            self._last_net_t = now
            self._up_lbl.setText(f"↑  {up_s:.2f} MB/s")
            self._dn_lbl.setText(f"↓  {dn_s:.2f} MB/s")

    def _refresh_services(self):
        online    = 0
        total_ram = 0.0
        for name, row in self.rows.items():
            info = self._bots.get(name, {})
            r    = info.get("running", False)
            row.refresh(
                r,
                memory = info.get("memory", 0.0),
                pid    = info.get("pid"),
            )
            if r:
                online    += 1
                total_ram += info.get("memory", 0.0)

        total = len(self.rows)
        self._footer_l.setText(f"{total_ram:.0f} MB total  ·  {online}/{total} online")

        if online == total:
            self._online_lbl.setText(f"{online} / {total}  ALL ONLINE")
            self._online_lbl.setStyleSheet(
                f"font-size:11px;font-weight:bold;color:{C['green']};background:transparent;"
            )
            self._banner_lbl.setText("ALL SYSTEMS OPERATIONAL")
            self._banner_lbl.setStyleSheet(
                f"font-size:11px;font-weight:bold;color:{C['green']};background:transparent;"
            )
            self._banner.setStyleSheet(
                "background:#06130e;border:1px solid #0d2a1a;border-radius:7px;"
            )
        elif online > 0:
            self._online_lbl.setText(f"{online} / {total}  PARTIAL")
            self._online_lbl.setStyleSheet(
                f"font-size:11px;font-weight:bold;color:{C['orange']};background:transparent;"
            )
            self._banner_lbl.setText(f"PARTIAL — {online} / {total} SERVICES ONLINE")
            self._banner_lbl.setStyleSheet(
                f"font-size:11px;font-weight:bold;color:{C['orange']};background:transparent;"
            )
            self._banner.setStyleSheet(
                "background:#13100a;border:1px solid #2a1f08;border-radius:7px;"
            )
        else:
            self._online_lbl.setText(f"0 / {total}  OFFLINE")
            self._online_lbl.setStyleSheet(
                f"font-size:11px;font-weight:bold;color:{C['red']};background:transparent;"
            )
            self._banner_lbl.setText("ALL SERVICES OFFLINE")
            self._banner_lbl.setStyleSheet(
                f"font-size:11px;font-weight:bold;color:{C['red']};background:transparent;"
            )
            self._banner.setStyleSheet(
                "background:#130606;border:1px solid #2a0808;border-radius:7px;"
            )

    # -----------------------------------------------------------------------
    # Exit / power
    # -----------------------------------------------------------------------
    def _exit_prompt(self):
        dlg = ConfirmDialog(
            self, "Exit Master Terminal",
            "The dashboard will close. Running services are not affected\n"
            "and will continue running in their own windows.",
            "Exit", C["red"],
        )
        if dlg.exec():
            self._quit()

    def _power_prompt(self, title, body, ok_text, ok_color, action):
        dlg = ConfirmDialog(self, title, body, ok_text, ok_color)
        if dlg.exec():
            action()

    def _quit(self):
        self._timer.stop()
        self._worker.stop()
        self._thread.quit()
        self._thread.wait(2000)
        QApplication.quit()


# ===========================================================================
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("LionByte Master Terminal")
    app.setStyle("Fusion")
    w = MasterTerminal()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
