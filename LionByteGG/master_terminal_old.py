"""
LIONBYTE MASTER TERMINAL
=========================
A high-performance dashboard showing system stats, bot activity, and live logs.
Designed to be the central monitoring hub for all LionByte services.
"""

import os
import sys
import time
import json
import threading
import ctypes
from datetime import datetime, timedelta
from collections import deque
import subprocess

# Check and install dependencies
def install_deps():
    deps = ['rich', 'psutil']
    for dep in deps:
        try:
            __import__(dep)
        except ImportError:
            print(f"Installing {dep}...")
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', dep, '-q'])

install_deps()

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.text import Text
from rich.align import Align
from rich.columns import Columns
from rich import box
import psutil

# Constants
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ACTIVITY_LOG_PATH = os.path.join(DATA_DIR, "activity_log.json")
BOT_STATUS_PATH = os.path.join(DATA_DIR, "bot_status.json")

# Colors matching LionByte branding
LION_GOLD = "#fbbf24"
LION_BLUE = "#3b82f6"
LION_GREEN = "#22c55e"
LION_RED = "#ef4444"
LION_PURPLE = "#a855f7"
LION_CYAN = "#06b6d4"
LION_ORANGE = "#f97316"
LION_DIM = "#6b7280"

# ASCII Logo
LION_LOGO = r"""
   ██╗     ██╗  ██████╗  ███╗   ██╗ ██████╗  ██╗   ██╗ ████████╗ ███████╗
   ██║     ██║ ██╔═══██╗ ████╗  ██║ ██╔══██╗ ╚██╗ ██╔╝ ╚══██╔══╝ ██╔════╝
   ██║     ██║ ██║   ██║ ██╔██╗ ██║ ██████╔╝  ╚████╔╝     ██║    █████╗
   ██║     ██║ ██║   ██║ ██║╚██╗██║ ██╔══██╗   ╚██╔╝      ██║    ██╔══╝
   ███████╗██║ ╚██████╔╝ ██║ ╚████║ ██████╔╝    ██║       ██║    ███████╗
   ╚══════╝╚═╝  ╚═════╝  ╚═╝  ╚═══╝ ╚═════╝     ╚═╝       ╚═╝    ╚══════╝
"""

class MasterTerminal:
    def __init__(self):
        self.console = Console()
        self.activity_log = []
        self.bot_status = {}
        self.start_time = datetime.now()
        self.running = True
        self.frame_count = 0
        
        # Cached system stats for smooth updates
        self.cached_stats = {
            'cpu': 0,
            'cpu_cores': psutil.cpu_count(),
            'ram': 0,
            'ram_used': 0,
            'ram_total': psutil.virtual_memory().total / (1024**3),
            'disk': 0,
            'disk_used': 0,
            'disk_total': 0,
            'net_up': 0,
            'net_down': 0,
        }
        
        # Network tracking
        self.last_net = psutil.net_io_counters()
        self.last_net_time = time.time()
        
        # Bot process cache
        self.cached_bots = {}
        self.last_bot_check = 0
        
        # Activity log cache
        self.last_activity_mtime = 0
        
        # Initial CPU read (first call always returns 0)
        psutil.cpu_percent(interval=None)
        
        # Start background data loader
        self.data_thread = threading.Thread(target=self._background_loader, daemon=True)
        self.data_thread.start()

    def _background_loader(self):
        """Background thread for loading data without blocking UI"""
        while self.running:
            try:
                # Load activity log if changed
                if os.path.exists(ACTIVITY_LOG_PATH):
                    mtime = os.path.getmtime(ACTIVITY_LOG_PATH)
                    if mtime != self.last_activity_mtime:
                        self.last_activity_mtime = mtime
                        with open(ACTIVITY_LOG_PATH, 'r', encoding='utf-8') as f:
                            self.activity_log = json.load(f)[:20]
                
                # Load bot status
                if os.path.exists(BOT_STATUS_PATH):
                    with open(BOT_STATUS_PATH, 'r', encoding='utf-8') as f:
                        self.bot_status = json.load(f)
            except Exception:
                pass
            
            time.sleep(0.5)  # Check every 500ms

    def update_system_stats(self):
        """Update system statistics - called every frame"""
        # CPU (non-blocking)
        self.cached_stats['cpu'] = psutil.cpu_percent(interval=None)
        
        # Memory
        mem = psutil.virtual_memory()
        self.cached_stats['ram'] = mem.percent
        self.cached_stats['ram_used'] = mem.used / (1024**3)
        
        # Disk (check less frequently)
        if self.frame_count % 10 == 0:
            try:
                disk = psutil.disk_usage('C:/' if os.name == 'nt' else '/')
                self.cached_stats['disk'] = disk.percent
                self.cached_stats['disk_used'] = disk.used / (1024**3)
                self.cached_stats['disk_total'] = disk.total / (1024**3)
            except:
                pass
        
        # Network speed
        now = time.time()
        elapsed = now - self.last_net_time
        if elapsed >= 1.0:
            net = psutil.net_io_counters()
            self.cached_stats['net_up'] = (net.bytes_sent - self.last_net.bytes_sent) / elapsed / 1024 / 1024
            self.cached_stats['net_down'] = (net.bytes_recv - self.last_net.bytes_recv) / elapsed / 1024 / 1024
            self.last_net = net
            self.last_net_time = now

    def get_bot_processes(self):
        """Check which bot processes are running - cached for performance"""
        # Only check every 2 seconds
        now = time.time()
        if now - self.last_bot_check < 2:
            return self.cached_bots
        
        self.last_bot_check = now
        
        bots = {
            'LionByteGG': {'running': False, 'pid': None, 'memory': 0},
            'LionShiftGG': {'running': False, 'pid': None, 'memory': 0},
            'LionBeatsGG': {'running': False, 'pid': None, 'memory': 0},
            'BoilerCraftGG': {'running': False, 'pid': None, 'memory': 0},
            'WebDashboard': {'running': False, 'pid': None, 'memory': 0},
        }
        
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_info']):
                try:
                    info = proc.info
                    cmdline_list = info['cmdline'] or []
                    cmdline = ' '.join(cmdline_list).lower()
                    cmdline_raw = ' '.join(cmdline_list)  # Keep original case for path detection
                    mem_mb = info['memory_info'].rss / (1024**2) if info['memory_info'] else 0
                    
                    # Skip if not a Python process
                    if 'python' not in cmdline:
                        # Check for Lavalink/Java
                        if 'java' in cmdline and 'lavalink' in cmdline:
                            bots['LionBeatsGG'] = {'running': True, 'pid': info['pid'], 'memory': mem_mb}
                        continue
                    
                    # Try to get cwd - this often fails due to permissions
                    cwd = ''
                    try:
                        cwd = proc.cwd().lower() if proc.cwd() else ''
                    except:
                        pass
                    
                    # Check cmdline for full paths (more reliable than cwd)
                    has_lionbytegg_path = 'lionbytegg' in cmdline_raw.lower() and 'lionshiftgg' not in cmdline_raw.lower()
                    has_lionshiftgg_path = 'lionshiftgg' in cmdline_raw.lower()
                    has_boilercraftgg_path = 'boilercraftgg' in cmdline_raw.lower()
                    has_lionbeatsgg_path = 'lionbeatsgg' in cmdline_raw.lower()
                    
                    # LionByteGG - main.py in LionByteGG folder (not master_terminal)
                    if has_lionbytegg_path and 'main.py' in cmdline and 'master_terminal' not in cmdline:
                        bots['LionByteGG'] = {'running': True, 'pid': info['pid'], 'memory': mem_mb}
                    # LionShiftGG - main.py in LionShiftGG folder
                    elif has_lionshiftgg_path and 'main.py' in cmdline:
                        bots['LionShiftGG'] = {'running': True, 'pid': info['pid'], 'memory': mem_mb}
                    # Fallback: Check cwd for lionshiftgg
                    elif 'lionshiftgg' in cwd and 'main.py' in cmdline:
                        bots['LionShiftGG'] = {'running': True, 'pid': info['pid'], 'memory': mem_mb}
                    # LionBeatsGG
                    elif has_lionbeatsgg_path:
                        bots['LionBeatsGG'] = {'running': True, 'pid': info['pid'], 'memory': mem_mb}
                    # BoilerCraftGG
                    elif has_boilercraftgg_path and 'bot.py' in cmdline:
                        bots['BoilerCraftGG'] = {'running': True, 'pid': info['pid'], 'memory': mem_mb}
                    # Fallback: Check cwd for boilercraftgg
                    elif 'boilercraftgg' in cwd and 'bot.py' in cmdline:
                        bots['BoilerCraftGG'] = {'running': True, 'pid': info['pid'], 'memory': mem_mb}
                    # WebDashboard - run.py with web in path
                    elif 'run.py' in cmdline and ('web' in cmdline_raw.lower() or 'web' in cwd):
                        bots['WebDashboard'] = {'running': True, 'pid': info['pid'], 'memory': mem_mb}
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                    continue
        except Exception:
            pass
        
        self.cached_bots = bots
        return bots

    def make_progress_bar(self, percent, width=20, color=LION_GREEN):
        """Create a smooth gradient progress bar"""
        filled = int(width * percent / 100)
        partial = (width * percent / 100) - filled
        empty = width - filled - (1 if partial > 0.5 else 0)
        
        bar = Text()
        bar.append("▐", style=f"dim {color}")
        bar.append("█" * filled, style=color)
        if partial > 0.5:
            bar.append("▓", style=color)
        bar.append("░" * max(0, empty), style=f"dim {LION_DIM}")
        bar.append("▌", style=f"dim {color}")
        bar.append(f" {percent:5.1f}%", style=f"bold {color}")
        return bar

    def make_header(self):
        """Create the header panel with ASCII logo"""
        uptime = datetime.now() - self.start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)
        
        # Animated spinner
        spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        spinner = spinner_chars[self.frame_count % len(spinner_chars)]
        
        header = Text()
        for line in LION_LOGO.strip().split('\n'):
            header.append(line + "\n", style=f"bold {LION_GOLD}")
        header.append("\n")
        header.append(f"  {spinner} ", style=f"bold {LION_GREEN}")
        header.append("MASTER TERMINAL", style=f"bold white")
        header.append(f"  {spinner}", style=f"bold {LION_GREEN}")
        header.append("     ", style="dim")
        
        if days > 0:
            header.append(f"Uptime: {days}d {hours:02d}:{minutes:02d}:{seconds:02d}", style=f"dim {LION_CYAN}")
        else:
            header.append(f"Uptime: {hours:02d}:{minutes:02d}:{seconds:02d}", style=f"dim {LION_CYAN}")
        header.append("  │  ", style="dim")
        header.append(f"{datetime.now().strftime('%a %b %d, %Y  %H:%M:%S')}", style=f"dim {LION_CYAN}")
        
        return Panel(
            Align.center(header),
            style=f"bold {LION_GOLD}",
            box=box.HEAVY,
            padding=(0, 1)
        )

    def make_system_panel(self):
        """Create system monitoring panel"""
        stats = self.cached_stats
        
        table = Table(box=None, show_header=False, padding=(0, 1), expand=True)
        table.add_column("Label", style="bold white", width=10)
        table.add_column("Bar", width=30)
        table.add_column("Value", style="dim white", width=20)
        
        # CPU with color coding
        cpu_color = LION_GREEN if stats['cpu'] < 50 else LION_ORANGE if stats['cpu'] < 80 else LION_RED
        table.add_row(
            "🔥 CPU",
            self.make_progress_bar(stats['cpu'], color=cpu_color),
            f"({stats['cpu_cores']} cores)"
        )
        
        # RAM
        ram_color = LION_GREEN if stats['ram'] < 60 else LION_ORANGE if stats['ram'] < 85 else LION_RED
        table.add_row(
            "💾 RAM",
            self.make_progress_bar(stats['ram'], color=ram_color),
            f"{stats['ram_used']:.1f} / {stats['ram_total']:.1f} GB"
        )
        
        # Disk
        disk_color = LION_GREEN if stats['disk'] < 70 else LION_ORANGE if stats['disk'] < 90 else LION_RED
        table.add_row(
            "💿 Disk",
            self.make_progress_bar(stats['disk'], color=disk_color),
            f"{stats['disk_used']:.0f} / {stats['disk_total']:.0f} GB"
        )
        
        # Network (separate row, no bar)
        table.add_row("", "", "")
        net_text = Text()
        net_text.append(f"  ▲ {stats['net_up']:6.2f} MB/s", style=f"bold {LION_CYAN}")
        net_text.append(f"    ▼ {stats['net_down']:6.2f} MB/s", style=f"bold {LION_PURPLE}")
        table.add_row("🌐 Net", net_text, "")
        
        return Panel(
            table,
            title="[bold white]⚡ System Resources[/]",
            border_style=LION_BLUE,
            box=box.ROUNDED,
            padding=(1, 1)
        )

    def make_bots_panel(self):
        """Create bot status panel"""
        bots = self.get_bot_processes()
        
        table = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1), expand=True,
                      header_style=f"bold {LION_GOLD}")
        table.add_column("Service", style="bold white", width=16)
        table.add_column("Status", width=14, justify="center")
        table.add_column("Memory", width=10, justify="right")
        table.add_column("PID", width=8, justify="right", style="dim")
        
        bot_config = {
            'LionByteGG': ('🦁', LION_GOLD),
            'LionShiftGG': ('⏰', LION_PURPLE),
            'LionBeatsGG': ('🎵', LION_CYAN),
            'BoilerCraftGG': ('⛏️', LION_RED),
            'WebDashboard': ('🌐', LION_BLUE),
        }
        
        # Pulsing animation frames
        pulse_frames = ["●", "◉", "○", "◉"]
        pulse_idx = self.frame_count // 2 % len(pulse_frames)
        
        for name, info in bots.items():
            icon, color = bot_config.get(name, ('🤖', 'white'))
            
            if info['running']:
                pulse = pulse_frames[pulse_idx]
                status = Text(f" {pulse} ONLINE ", style=f"bold {LION_GREEN}")
                memory = Text(f"{info['memory']:.0f} MB", style=f"bold white")
                pid = str(info['pid'])
            else:
                status = Text(" ○ OFFLINE", style=f"bold {LION_RED}")
                memory = Text("—", style="dim")
                pid = "—"
            
            name_text = Text()
            name_text.append(f"{icon} ", style="white")
            name_text.append(name, style=f"bold {color}")
            
            table.add_row(name_text, status, memory, pid)
        
        # Summary line
        online = sum(1 for b in bots.values() if b['running'])
        total = len(bots)
        summary_color = LION_GREEN if online == total else LION_ORANGE if online > 0 else LION_RED
        
        summary = Text()
        summary.append(f"\n  {online}/{total} services online", style=f"bold {summary_color}")
        if online == total:
            summary.append("  ✓ All systems operational", style=f"bold {LION_GREEN}")
        elif online == 0:
            summary.append("  ✗ All services down!", style=f"bold {LION_RED}")
        
        from rich.console import Group
        content = Group(table, summary)
        
        return Panel(
            content,
            title="[bold white]🤖 Bot Services[/]",
            border_style=LION_GREEN,
            box=box.ROUNDED,
            padding=(1, 1)
        )

    def make_activity_panel(self):
        """Create activity log panel"""
        table = Table(box=box.SIMPLE, show_header=True, padding=(0, 1), expand=True,
                      header_style=f"bold {LION_PURPLE}")
        table.add_column("Time", style=f"dim {LION_CYAN}", width=10)
        table.add_column("Action", width=16)
        table.add_column("User", width=18, overflow="ellipsis")
        table.add_column("Details", overflow="ellipsis", ratio=1)
        
        action_styles = {
            'login': (LION_GREEN, '🔓'),
            'logout': (LION_ORANGE, '🔒'),
            'warning': (LION_ORANGE, '⚠️'),
            'kick': (LION_RED, '👢'),
            'ban': (LION_RED, '🔨'),
            'automod flag': (LION_ORANGE, '🚨'),
            'command': (LION_BLUE, '⌨️'),
            'api': (LION_PURPLE, '🔌'),
            'roster': (LION_CYAN, '📋'),
        }
        
        # Show last 12 activities
        activities = self.activity_log[:12] if self.activity_log else []
        
        for entry in activities:
            try:
                timestamp = entry.get('timestamp', '')
                if timestamp:
                    try:
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        time_str = dt.strftime('%H:%M:%S')
                    except:
                        time_str = timestamp[:8] if len(timestamp) >= 8 else '—'
                else:
                    time_str = '—'
                
                action = str(entry.get('action', 'unknown')).lower()
                color, icon = action_styles.get(action, ('white', '📌'))
                
                user_info = entry.get('user', {})
                if isinstance(user_info, dict):
                    user_name = user_info.get('name', 'Unknown')[:18]
                else:
                    user_name = str(user_info)[:18]
                
                details = str(entry.get('details', ''))[:50]
                
                action_text = Text()
                action_text.append(f"{icon} ", style="white")
                action_text.append(action.title()[:12], style=f"bold {color}")
                
                table.add_row(time_str, action_text, user_name, details)
            except Exception:
                continue
        
        if not activities:
            table.add_row("", Text("No recent activity", style="dim"), "", "")
        
        return Panel(
            table,
            title="[bold white]📊 Live Activity[/]",
            border_style=LION_PURPLE,
            box=box.ROUNDED,
            padding=(1, 1)
        )

    def make_quick_stats(self):
        """Create quick stats bar"""
        bots = self.get_bot_processes()
        online_bots = sum(1 for b in bots.values() if b['running'])
        total_bots = len(bots)
        total_memory = sum(b['memory'] for b in bots.values() if b['running'])
        
        stats = Text()
        stats.append(f" 🤖 Bots: {online_bots}/{total_bots} ", 
                    style=f"bold {LION_GREEN if online_bots == total_bots else LION_ORANGE}")
        stats.append("  │  ", style="dim")
        stats.append(f"💾 Bot RAM: {total_memory:.0f} MB ", style=f"bold {LION_BLUE}")
        stats.append("  │  ", style="dim")
        stats.append(f"🔥 CPU: {self.cached_stats['cpu']:.0f}% ", style=f"bold {LION_ORANGE}")
        stats.append("  │  ", style="dim")
        stats.append(f"📝 Logs: {len(self.activity_log)} ", style=f"bold {LION_PURPLE}")
        
        return Panel(Align.center(stats), box=box.SIMPLE, style="dim", padding=(0, 0))

    def make_footer(self):
        """Create the footer with keyboard hints"""
        footer = Text()
        footer.append("  CTRL+C", style=f"bold {LION_GOLD}")
        footer.append(" Exit", style="dim white")
        footer.append("   │   ", style="dim")
        footer.append("Created with <3 by Jay", style=f"bold {LION_GOLD}")
        footer.append("   │   ", style="dim")
        footer.append(f"Refresh: 4 FPS", style=f"dim {LION_CYAN}")
        return Panel(Align.center(footer), box=box.SIMPLE, style="dim", padding=(0, 0))

    def generate_display(self):
        """Generate the full display layout"""
        self.frame_count += 1
        self.update_system_stats()
        
        layout = Layout()
        layout.split(
            Layout(name="header", size=11),
            Layout(name="stats_bar", size=3),
            Layout(name="main", ratio=1),
            Layout(name="activity", size=18),
            Layout(name="footer", size=3)
        )
        
        layout["main"].split_row(
            Layout(name="system", ratio=1),
            Layout(name="bots", ratio=1)
        )
        
        layout["header"].update(self.make_header())
        layout["stats_bar"].update(self.make_quick_stats())
        layout["system"].update(self.make_system_panel())
        layout["bots"].update(self.make_bots_panel())
        layout["activity"].update(self.make_activity_panel())
        layout["footer"].update(self.make_footer())
        
        return layout

    def run(self):
        """Run the master terminal with fast refresh"""
        try:
            with Live(
                self.generate_display(), 
                console=self.console, 
                refresh_per_second=4,  # 4 FPS for smooth updates
                screen=True,
                transient=False
            ) as live:
                while self.running:
                    try:
                        live.update(self.generate_display())
                        time.sleep(0.25)  # 250ms between frames
                    except KeyboardInterrupt:
                        self.running = False
                        break
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False


def set_console_fullscreen():
    """Set console to fullscreen mode on Windows"""
    try:
        if os.name != 'nt':
            return
            
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            # Maximize window
            user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            
            # Set always on top
            HWND_TOPMOST = -1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
        
        # Set larger console buffer
        os.system('mode con: cols=170 lines=55')
    except Exception as e:
        print(f"Note: Could not set fullscreen: {e}")


def main():
    # Clear screen and set title
    os.system('cls' if os.name == 'nt' else 'clear')
    os.system('title LIONBYTE Master Terminal' if os.name == 'nt' else '')
    
    # Set fullscreen and always on top
    set_console_fullscreen()
    
    # Short startup message
    console = Console()
    console.print(f"\n[bold {LION_GOLD}]{LION_LOGO}[/]", justify="center")
    console.print(f"[bold white]MASTER TERMINAL[/]", justify="center")
    console.print(f"[dim {LION_CYAN}]Initializing dashboard...[/]\n", justify="center")
    time.sleep(0.5)
    
    # Run the terminal
    terminal = MasterTerminal()
    terminal.run()


if __name__ == "__main__":
    main()
