"""
LionByteGG Web Dashboard Runner
Production-ready script for running the web dashboard.
Supports both development and production modes.
"""

import os
import sys
import socket
import time
import subprocess
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

def _kill_other_instances():
    """Terminate any OTHER python process running run.py, so only one web server
    ever exists. Prevents the duplicate-server problem that breaks logins."""
    me = os.getpid()
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -like '*run.py*' } | "
             "Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=15,
        )
        killed = 0
        for line in (out.stdout or "").split():
            pid = line.strip()
            if pid.isdigit() and int(pid) != me:
                r = subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=10)
                if r.returncode == 0:
                    killed += 1
                    print(f"[startup] Stopped duplicate server (PID {pid}) so only one runs.")
        if killed:
            time.sleep(1.5)  # let the OS release port 5000
    except Exception as e:
        print(f"[startup] Duplicate-instance check skipped: {e}")

def _port_in_use(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()

def _ensure_single_instance(port):
    """Guarantee exactly one server: kill other run.py instances, then wait for
    the port to free up."""
    _kill_other_instances()
    for _ in range(12):
        if not _port_in_use(port):
            return
        time.sleep(0.5)
    print(f"[startup] WARNING: port {port} is still in use by another program.")

def get_local_ip():
    """Get the local IP address for LAN access."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def run_development():
    """Run in development mode with Flask's built-in server"""
    _ensure_single_instance(int(os.environ.get('PORT', 5000)))
    local_ip = get_local_ip()
    print("=" * 60)
    print("LionByteGG Web Dashboard - DEVELOPMENT MODE")
    print("=" * 60)
    print(f"Local URL:   http://localhost:5000")
    print(f"LAN URL:     http://{local_ip}:5000")
    print("=" * 60)
    print("Share the LAN URL with others on your network!")
    print("Press CTRL+C to stop the server.")
    print("=" * 60)
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True,
        threaded=True
    )

def run_production():
    """Run in production mode with Waitress (Windows-compatible)"""
    try:
        from waitress import serve
    except ImportError:
        print("ERROR: waitress is not installed. Run: pip install waitress")
        print("Falling back to Flask development server...")
        run_development()
        return
    
    local_ip = get_local_ip()
    port = int(os.environ.get('PORT', 5000))
    _ensure_single_instance(port)
    
    print("=" * 60)
    print("LionByteGG Web Dashboard - PRODUCTION MODE")
    print("=" * 60)
    print(f"Server:      Waitress WSGI")
    print(f"Local URL:   http://localhost:{port}")
    print(f"LAN URL:     http://{local_ip}:{port}")
    print(f"Workers:     8 threads")
    print("=" * 60)
    print("Server is running. Press CTRL+C to stop.")
    print("=" * 60)
    
    serve(app, host='0.0.0.0', port=port, threads=8,
          channel_timeout=120, recv_bytes=65536)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='LionByteGG Web Dashboard')
    parser.add_argument('--production', '-p', action='store_true', 
                        help='Run in production mode with Waitress')
    parser.add_argument('--port', type=int, default=5000,
                        help='Port to run the server on (default: 5000)')
    args = parser.parse_args()
    
    if args.port != 5000:
        os.environ['PORT'] = str(args.port)
    
    if args.production or os.environ.get('FLASK_ENV') == 'production':
        run_production()
    else:
        run_development()
